"""
fusion_engine/decision_engine.py
=================================
Merges raw AI module outputs into a single, actionable Decision.

Numeric priority scores (1 = highest urgency, 5 = lowest):
  1  CRITICAL  — depth-confirmed imminent collision         → interrupts TTS
  2  HIGH      — known face OR very close obstacle
  3  MEDIUM    — objects at moderate confidence / distance
  4  LOW       — OCR text OR unknown faces
  5  INFO      — empty / generic scene

Alert text contract:
  Every alert_text is enforced to ≤ 10 words before being returned.

Output SceneContext is a dataclass; .to_dict() is JSON-safe.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.fusion_engine.priority_system import (
    Priority,
    PriorityScore,
    get_priority,
    is_critical,
)

logger = logging.getLogger(__name__)

# Maximum words allowed in an alert_text (TTS readability constraint)
_MAX_WORDS = 10


# ── data structures ───────────────────────────────────────────────────────────

@dataclass
class SceneContext:
    """Aggregated per-frame input to the DecisionEngine."""
    faces:     list[dict]
    objects:   list[dict]
    ocr:       list[dict]
    depth:     Optional[dict]
    timestamp: float = field(default_factory=time.time)
    camera_id: str   = ""

    @classmethod
    def from_inference(cls, result: dict) -> "SceneContext":
        return cls(
            faces     = result.get("faces",   []),
            objects   = result.get("objects", []),
            ocr       = result.get("ocr",     []),
            depth     = result.get("depth"),
            timestamp = result.get("timestamp", time.time()),
            camera_id = result.get("camera_id", ""),
        )


@dataclass
class Decision:
    """Structured output from DecisionEngine for one frame."""
    priority_score: int          # 1 (CRITICAL) – 5 (INFORMATIONAL)
    priority_name:  str          # human-readable level name
    alert_text:     str          # ≤10 words, ready for TTS
    is_critical:    bool         # True → audio queue must interrupt playback
    confidence:     float        # 0.0 – 1.0
    alert_type:     str          # key into AudioPriorityQueue cooldown map
    details:        dict         = field(default_factory=dict)
    actions:        list[str]    = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "priority_score": self.priority_score,
            "priority_name":  self.priority_name,
            "alert_text":     self.alert_text,
            "is_critical":    self.is_critical,
            "confidence":     round(self.confidence, 3),
            "alert_type":     self.alert_type,
            "details":        self.details,
            "actions":        self.actions,
        }


# ── engine ────────────────────────────────────────────────────────────────────

class DecisionEngine:
    """
    Converts InferenceService output into a Decision with a numeric
    priority score and a TTS-ready ≤10-word alert string.

    Parameters
    ----------
    confidence_threshold:
        Minimum per-detection confidence to include in decisions.
    identity_priority:
        If True (default), a recognised face takes precedence over obstacles.
    obstacle_alert_priority:
        If True (default), depth-confirmed obstacles outrank generic scenes.
    """

    _DISTANCE_RANK = {"very_close": 0, "close": 1, "medium": 2, "far": 3}

    def __init__(
        self,
        confidence_threshold:    float = 0.5,
        identity_priority:       bool  = True,
        obstacle_alert_priority: bool  = True,
    ) -> None:
        self._conf_thresh   = confidence_threshold
        self._identity_prio = identity_priority
        self._obstacle_prio = obstacle_alert_priority

    # ── public API ────────────────────────────────────────────────────────────

    def decide(self, inference_result: dict) -> dict:
        """
        Convert InferenceService output to a Decision dict.
        Always returns a valid dict — never raises.
        """
        try:
            ctx      = SceneContext.from_inference(inference_result)
            decision = self._evaluate(ctx)
            logger.debug(
                "Decision [%d/%s] '%s'  conf=%.2f  critical=%s",
                decision.priority_score, decision.priority_name,
                decision.alert_text, decision.confidence, decision.is_critical,
            )
            return decision.to_dict()
        except Exception as exc:
            logger.error("DecisionEngine.decide failed: %s", exc, exc_info=True)
            return _fallback_decision().to_dict()

    # ── evaluation logic ──────────────────────────────────────────────────────

    def _evaluate(self, ctx: SceneContext) -> Decision:
        """Priority ladder — first match wins."""

        # ── Priority 1: depth-confirmed imminent collision ────────────────────
        if self._obstacle_prio and isinstance(ctx.depth, dict):
            depth = ctx.depth
            nearest_val  = depth.get("nearest_value", 0.0)
            nearest_zone = depth.get("nearest_zone",  "center")
            # nearest_value is normalised [0,1]; 1.0 = closest.
            # Flag CRITICAL only when center zone is extremely close.
            if depth.get("obstacle_alert") and nearest_zone == "center" and nearest_val >= 0.90:
                ps = get_priority("collision_imminent")
                return Decision(
                    priority_score = ps.score,
                    priority_name  = Priority(ps.score).name,
                    alert_text     = _truncate("Obstacle très proche devant vous maintenant"),
                    is_critical    = True,
                    confidence     = float(nearest_val),
                    alert_type     = "collision_imminent",
                    details        = {"depth": depth, "objects": ctx.objects},
                    actions        = ["tts", "audio_alert", "log"],
                )

        # ── Priority 2a: known face ───────────────────────────────────────────
        if self._identity_prio:
            known = [
                f for f in ctx.faces
                if f.get("known") and f.get("name") not in (None, "", "Unknown")
            ]
            if known:
                top = max(known, key=lambda f: f.get("confidence", 0))
                ps  = get_priority("face_known")
                return Decision(
                    priority_score = ps.score,
                    priority_name  = Priority(ps.score).name,
                    alert_text     = _truncate(f"Personne reconnue : {top['name']}"),
                    is_critical    = ps.is_critical,
                    confidence     = float(top.get("confidence", 1.0)),
                    alert_type     = f"face_{top['name']}",
                    details        = {"face": _strip_emb(top), "all_faces": _strip_embs(ctx.faces)},
                    actions        = ["tts", "log"],
                )

        # ── Priority 2b: depth-confirmed close obstacle (non-critical) ────────
        if self._obstacle_prio and isinstance(ctx.depth, dict) and ctx.depth.get("obstacle_alert"):
            depth = ctx.depth
            zone  = depth.get("nearest_zone", "devant")
            val   = depth.get("nearest_value", 0.0)
            ps    = get_priority("obstacle_close")
            return Decision(
                priority_score = ps.score,
                priority_name  = Priority(ps.score).name,
                alert_text     = _truncate(f"Obstacle proche à {zone}"),
                is_critical    = ps.is_critical,
                confidence     = float(val),
                alert_type     = "obstacle_close",
                details        = {"depth": depth, "objects": ctx.objects},
                actions        = ["tts", "audio_alert", "log"],
            )

        # ── Priority 3: objects above confidence threshold ────────────────────
        confident_objs = [
            o for o in ctx.objects
            if o.get("confidence", 0) >= self._conf_thresh
        ]
        if confident_objs:
            confident_objs.sort(
                key=lambda o: self._DISTANCE_RANK.get(o.get("distance_est", "far"), 3)
            )
            labels   = [o.get("label", "objet") for o in confident_objs[:3]]
            top_conf = max(o.get("confidence", 0) for o in confident_objs)
            top_dist = confident_objs[0].get("distance_est", "medium")

            event_type = "obstacle_very_close" if top_dist == "very_close" else "object_detected"
            ps         = get_priority(event_type)

            return Decision(
                priority_score = ps.score,
                priority_name  = Priority(ps.score).name,
                alert_text     = _truncate("Objets détectés : " + ", ".join(labels)),
                is_critical    = ps.is_critical,
                confidence     = float(top_conf),
                alert_type     = "object_detected",
                details        = {
                    "objects": confident_objs,
                    "faces":   _strip_embs(ctx.faces),
                    "depth":   ctx.depth,
                },
                actions = ["tts", "log"],
            )

        # ── Priority 4: OCR text ──────────────────────────────────────────────
        if ctx.ocr:
            snippet = " | ".join(
                item.get("text", "") for item in ctx.ocr[:3] if item.get("text")
            ).strip()
            if snippet:
                ps = get_priority("text_found")
                return Decision(
                    priority_score = ps.score,
                    priority_name  = Priority(ps.score).name,
                    alert_text     = _truncate(f"Texte : {snippet}"),
                    is_critical    = ps.is_critical,
                    confidence     = ctx.ocr[0].get("confidence", 0.9) if ctx.ocr else 0.9,
                    alert_type     = "text_found",
                    details        = {"ocr": ctx.ocr},
                    actions        = ["tts"],
                )

        # ── Priority 4: unknown faces ─────────────────────────────────────────
        unknown_count = len(ctx.faces)
        if unknown_count:
            ps = get_priority("face_unknown")
            return Decision(
                priority_score = ps.score,
                priority_name  = Priority(ps.score).name,
                alert_text     = _truncate(f"{unknown_count} visage(s) inconnu(s) détecté(s)"),
                is_critical    = ps.is_critical,
                confidence     = 0.5,
                alert_type     = "face_unknown",
                details        = {"faces": _strip_embs(ctx.faces)},
                actions        = ["tts", "log"],
            )

        # ── Priority 5: empty / generic scene ────────────────────────────────
        ps = get_priority("empty_scene")
        return Decision(
            priority_score = ps.score,
            priority_name  = Priority(ps.score).name,
            alert_text     = "Aucun contenu significatif détecté",
            is_critical    = False,
            confidence     = 0.0,
            alert_type     = "empty_scene",
            details        = {},
            actions        = ["log"],
        )


# ── helpers ───────────────────────────────────────────────────────────────────

def _truncate(text: str) -> str:
    """Hard-enforce the ≤10-word contract for TTS alert strings."""
    words = text.split()
    if len(words) <= _MAX_WORDS:
        return text
    truncated = " ".join(words[:_MAX_WORDS])
    logger.debug("Alert truncated from %d to 10 words: '%s'", len(words), truncated)
    return truncated


def _fallback_decision() -> Decision:
    ps = get_priority("empty_scene")
    return Decision(
        priority_score = ps.score,
        priority_name  = "INFORMATIONAL",
        alert_text     = "Erreur interne du moteur de décision",
        is_critical    = False,
        confidence     = 0.0,
        alert_type     = "error",
        details        = {},
        actions        = ["log"],
    )


def _strip_emb(face: dict) -> dict:
    return {k: v for k, v in face.items() if k != "_embedding"}

def _strip_embs(faces: list[dict]) -> list[dict]:
    return [_strip_emb(f) for f in faces]