"""
DecisionEngine — merges raw AI module outputs into a single, actionable decision.

Priority order (highest → lowest):
  1. Recognised face   → identity-first response
  2. Detected objects  → annotated scene description
  3. OCR text present  → surface readable content
  4. Baseline          → generic scene summary

The engine is intentionally stateless per-call; long-term state (e.g. tracking
across frames) belongs in StateManager.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── decision schema ───────────────────────────────────────────────────────────

@dataclass
class Decision:
    priority:      str              # "identity" | "scene" | "text" | "generic"
    primary_label: str              # human-readable headline
    details:       dict             # full enriched payload
    actions:       list[str] = field(default_factory=list)   # e.g. ["tts", "log"]
    confidence:    float = 1.0

    def to_dict(self) -> dict:
        return {
            "priority":      self.priority,
            "primary_label": self.primary_label,
            "details":       self.details,
            "actions":       self.actions,
            "confidence":    self.confidence,
        }


# ── engine ────────────────────────────────────────────────────────────────────

class DecisionEngine:
    """
    Combines outputs from InferenceService into a final Decision object.

    Args:
        confidence_threshold: Minimum confidence to accept a detection.
        identity_priority:    If True (default), a recognised face always wins.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.5,
        identity_priority: bool = True,
    ) -> None:
        self._conf_thresh = confidence_threshold
        self._identity_priority = identity_priority

    # ── public API ────────────────────────────────────────────────────────────

    def decide(self, inference_result: dict) -> dict:
        """
        Accept the dict produced by ``InferenceService.process_frame``
        and return a ``Decision`` dict.
        """
        faces   = inference_result.get("faces", [])
        objects = inference_result.get("objects", [])
        ocr     = inference_result.get("ocr", [])
        depth   = inference_result.get("depth")

        decision = self._evaluate(faces, objects, ocr, depth)
        logger.debug("Decision: %s — %s", decision.priority, decision.primary_label)
        return decision.to_dict()

    # ── internal priority logic ───────────────────────────────────────────────

    def _evaluate(
        self,
        faces: list[dict],
        objects: list[dict],
        ocr: list[dict],
        depth: Optional[Any],
    ) -> Decision:

        # 1 — Recognised face
        if self._identity_priority:
            known = [f for f in faces if f.get("name") and f.get("name") != "unknown"]
            if known:
                top = max(known, key=lambda f: f.get("confidence", 0))
                return Decision(
                    priority="identity",
                    primary_label=f"Recognised: {top['name']}",
                    details={"face": top, "all_faces": faces, "objects": objects},
                    actions=["tts", "log"],
                    confidence=top.get("confidence", 1.0),
                )

        # 2 — Objects detected above threshold
        confident_objs = [
            o for o in objects
            if o.get("confidence", 0) >= self._conf_thresh
        ]
        if confident_objs:
            labels = [o.get("label", "object") for o in confident_objs]
            return Decision(
                priority="scene",
                primary_label="Scene: " + ", ".join(labels[:3]),
                details={
                    "objects": confident_objs,
                    "faces":   faces,
                    "depth":   depth,
                },
                actions=["tts", "log"],
                confidence=max(o.get("confidence", 0) for o in confident_objs),
            )

        # 3 — OCR text detected
        if ocr:
            text_snippet = " ".join(
                item.get("text", "") for item in ocr[:2] if item.get("text")
            ).strip()
            if text_snippet:
                return Decision(
                    priority="text",
                    primary_label=f"Text: {text_snippet[:80]}",
                    details={"ocr": ocr},
                    actions=["tts"],
                    confidence=0.9,
                )

        # 4 — Fallback
        unknown_faces = len(faces)
        label = (
            f"Scene with {unknown_faces} unidentified face(s)"
            if unknown_faces
            else "No significant content detected"
        )
        return Decision(
            priority="generic",
            primary_label=label,
            details={"faces": faces, "objects": objects, "ocr": ocr},
            actions=["log"],
            confidence=0.0,
        )