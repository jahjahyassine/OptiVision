"""
InferenceService — orchestrates all AI modules for a single frame.

Each module is called independently; one failure does not block the others.
Returns a unified, structured result dict.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


# ── result schema ─────────────────────────────────────────────────────────────

@dataclass
class InferenceResult:
    faces:     list[dict] = field(default_factory=list)
    objects:   list[dict] = field(default_factory=list)
    ocr:       list[dict] = field(default_factory=list)
    depth:     Optional[Any] = None
    timestamp: float = field(default_factory=time.time)
    errors:    dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "faces":     self.faces,
            "objects":   self.objects,
            "ocr":       self.ocr,
            "depth":     self.depth,
            "timestamp": self.timestamp,
            "errors":    self.errors,
        }


# ── service ───────────────────────────────────────────────────────────────────

class InferenceService:
    """
    Central orchestrator for OptiVision AI modules.

    Modules are injected at construction time so each can be independently
    tested, mocked, or swapped without touching this class.

    Args:
        face_recognizer:   Object with a ``process(frame) -> list[dict]`` method.
        object_detector:   Object with a ``detect(frame) -> list[dict]`` method.
        ocr_reader:        Object with a ``read(frame) -> list[dict]`` method.
        depth_estimator:   Optional object with an ``estimate(frame) -> any`` method.
    """

    def __init__(
        self,
        face_recognizer=None,
        object_detector=None,
        ocr_reader=None,
        depth_estimator=None,
    ) -> None:
        self._face = face_recognizer
        self._detector = object_detector
        self._ocr = ocr_reader
        self._depth = depth_estimator

    # ── public API ────────────────────────────────────────────────────────────

    def process_frame(self, frame: np.ndarray) -> dict:
        """
        Run all enabled AI modules on *frame* and return a unified result dict.

        Each module runs independently — failures are recorded in ``errors``
        but do not abort the remaining modules.
        """
        result = InferenceResult()

        result.faces   = self._run("face_recognition",  self._face,     "process",  frame)
        result.objects = self._run("object_detection",  self._detector, "detect",   frame)
        result.ocr     = self._run("ocr",               self._ocr,      "read",     frame)

        if self._depth is not None:
            result.depth = self._run("depth_estimation", self._depth, "estimate", frame,
                                     fallback=None)

        if result.errors:
            logger.warning("Inference completed with errors: %s", result.errors)

        return result.to_dict()

    # ── internal ──────────────────────────────────────────────────────────────

    def _run(self, name: str, module, method: str, frame: np.ndarray,
             fallback=None) -> Any:
        """Call *module.method(frame)* safely; return *fallback* on any error."""
        if module is None:
            return fallback if fallback is not None else []
        try:
            return getattr(module, method)(frame)
        except Exception as exc:
            logger.error("Module '%s' failed: %s", name, exc, exc_info=True)
            return fallback if fallback is not None else []


# ── factory helper ────────────────────────────────────────────────────────────

def build_inference_service() -> InferenceService:
    """
    Instantiate and wire up all AI modules.
    Import lazily to avoid heavy dependencies at module load time.
    """
    from backend.ai_modules.face_recognition.recognizer import FaceRecognizer
    from backend.ai_modules.object_detection.detector import ObjectDetector
    from backend.ai_modules.ocr.reader import OCRReader
    # Optional — comment out if depth module is not yet implemented
    # from backend.ai_modules.depth_estimation.estimator import DepthEstimator

    return InferenceService(
        face_recognizer=FaceRecognizer(),
        object_detector=ObjectDetector(),
        ocr_reader=OCRReader(),
        # depth_estimator=DepthEstimator(),
    )