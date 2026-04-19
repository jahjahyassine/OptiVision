"""
fusion_engine/decision_engine.py
=================================
Merges raw AI module outputs into a single, actionable Decision.

Priority ladder (highest → lowest):
  1. identity  — known face recognised
  2. obstacle  — depth-confirmed close obstacle
  3. scene     — objects detected with sufficient confidence
  4. text      — OCR text found
  5. generic   — fallback (unknown faces / empty scene)

The engine is intentionally stateless per-call; multi-frame state
(e.g. tracking, de-duplication) belongs in StateManager.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── output schema ─────────────────────────────────────────────────────────────

@dataclass
class Decision:
    priority:      str
    primary_label: str
    details:       dict
    actions:       list[str] = field(default_factory=list)
    confidence:    float     = 0.0

    def to_dict(self) -> dict:
        return {
            "priority":      self.priority,
            "primary_label": self.primary_label,
            "details":       self.details,
            "actions":       self.actions,
            "confidence":    round(self.confidence, 3),
        }


# ── engine ────────────────────────────────────────────────────────────────────

class DecisionEngine:
    """
    Combines InferenceService output into a final Decision.

    Parameters
    ----------
    confidence_threshold:
        Minimum YOLO/OCR confidence to promote a detection into the decision.
    identity_priority:
        If True (default), a recognised face overrides all other detections.
    obstacle_alert_priority:
        If True (default), a depth-confirmed close obstacle is surfaced before
        generic scene descriptions (but after identity).
    """

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
        Accept the dict produced by InferenceService.process_frame and
        return a Decision dict ready for TTS / API response.
        """
        faces   = inference_result.get("faces",   [])
        objects = inference_result.get("objects", [])
        ocr     = inference_result.get("ocr",     [])
        depth   = inference_result.get("depth")

        decision = self._evaluate(faces, objects, ocr, depth)
        logger.debug("Decision: [%s] %s", decision.priority, decision.primary_label)
        return decision.to_dict()

    # ── evaluation logic ──────────────────────────────────────────────────────

    def _evaluate(
        self,
        faces:   list[dict],
        objects: list[dict],
        ocr:     list[dict],
        depth:   Optional[Any],
    ) -> Decision:

        # 1. Known face recognised
        if self._identity_prio:
            known = [f for f in faces if f.get("known") and f.get("name") != "Unknown"]
            if known:
                top = max(known, key=lambda f: f.get("confidence", 0))
                return Decision(
                    priority      = "identity",
                    primary_label = f"Personne reconnue : {top['name']}",
                    details       = {
                        "face":      _strip_embedding(top),
                        "all_faces": _strip_embeddings(faces),
                    },
                    actions    = ["tts", "log"],
                    confidence = top.get("confidence", 1.0),
                )

        # 2. Depth-confirmed close obstacle
        if self._obstacle_prio and isinstance(depth, dict) and depth.get("obstacle_alert"):
            zone  = depth.get("nearest_zone", "devant")
            value = depth.get("nearest_value", 0.0)
            return Decision(
                priority      = "obstacle",
                primary_label = f"Obstacle proche {zone}",
                details       = {"depth": depth, "objects": objects},
                actions       = ["tts", "audio_alert", "log"],
                confidence    = float(value),
            )

        # 3. Objects above confidence threshold
        confident_objs = [
            o for o in objects if o.get("confidence", 0) >= self._conf_thresh
        ]
        if confident_objs:
            _DISTANCE_RANK = {"very_close": 0, "close": 1, "medium": 2, "far": 3}
            confident_objs.sort(
                key=lambda o: _DISTANCE_RANK.get(o.get("distance_est", "far"), 3)
            )
            labels   = [o.get("label", "objet") for o in confident_objs[:3]]
            top_conf = max(o.get("confidence", 0) for o in confident_objs)
            return Decision(
                priority      = "scene",
                primary_label = "Scène : " + ", ".join(labels),
                details       = {
                    "objects": confident_objs,
                    "faces":   _strip_embeddings(faces),
                    "depth":   depth,
                },
                actions    = ["tts", "log"],
                confidence = top_conf,
            )

        # 4. OCR text detected
        if ocr:
            snippet = " | ".join(
                item.get("text", "") for item in ocr[:3] if item.get("text")
            ).strip()
            if snippet:
                return Decision(
                    priority      = "text",
                    primary_label = f"Texte : {snippet[:100]}",
                    details       = {"ocr": ocr},
                    actions       = ["tts"],
                    confidence    = ocr[0].get("confidence", 0.9) if ocr else 0.9,
                )

        # 5. Fallback
        unknown_count = len(faces)
        label = (
            f"Scène avec {unknown_count} visage(s) inconnu(s)"
            if unknown_count
            else "Aucun contenu significatif détecté"
        )
        return Decision(
            priority      = "generic",
            primary_label = label,
            details       = {
                "faces":   _strip_embeddings(faces),
                "objects": objects,
                "ocr":     ocr,
            },
            actions    = ["log"],
            confidence = 0.0,
        )


# ── utilities ─────────────────────────────────────────────────────────────────

def _strip_embedding(face: dict) -> dict:
    return {k: v for k, v in face.items() if k != "_embedding"}

def _strip_embeddings(faces: list[dict]) -> list[dict]:
    return [_strip_embedding(f) for f in faces]