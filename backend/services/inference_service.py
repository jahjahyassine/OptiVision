"""
services/inference_service.py
==============================
Central AI orchestrator — runs all modules on a single frame and
returns a unified, structured result dict.

Design principles:
- Module isolation: one failure never kills the others.
- Synchronous: called from worker threads, not the async event loop.
- Lazy imports: heavy AI models are only loaded when build_inference_service()
  is explicitly called (keeps test imports fast).
- No disk I/O: everything stays in memory.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


# ── result schema ─────────────────────────────────────────────────────────────

@dataclass
class InferenceResult:
    """Unified output structure for one frame processed through all AI modules."""

    faces:     list[dict]     = field(default_factory=list)
    objects:   list[dict]     = field(default_factory=list)
    ocr:       list[dict]     = field(default_factory=list)
    depth:     Optional[Any]  = None          # numpy array or summary dict
    timestamp: float          = field(default_factory=time.time)
    camera_id: str            = ""
    errors:    dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        depth_out = self.depth
        # Convert numpy arrays to list so they're JSON-serialisable
        if hasattr(depth_out, "tolist"):
            depth_out = depth_out.tolist()
        return {
            "faces":     self.faces,
            "objects":   self.objects,
            "ocr":       self.ocr,
            "depth":     depth_out,
            "timestamp": self.timestamp,
            "camera_id": self.camera_id,
            "errors":    self.errors,
        }


# ── service ───────────────────────────────────────────────────────────────────

class InferenceService:
    """
    Orchestrates all AI modules for a single frame.

    All modules are injected at construction so they can be independently
    mocked in tests or disabled via config.

    Expected module interfaces
    --------------------------
    face_recognizer  : .process(frame: ndarray) -> list[dict]
    object_detector  : .detect(frame: ndarray)  -> list[dict]
    ocr_reader       : .read(frame: ndarray)     -> list[dict]
    depth_estimator  : .estimate(frame: ndarray) -> dict | ndarray | None
    """

    def __init__(
        self,
        face_recognizer=None,
        object_detector=None,
        ocr_reader=None,
        depth_estimator=None,
    ) -> None:
        self._face    = face_recognizer
        self._objects = object_detector
        self._ocr     = ocr_reader
        self._depth   = depth_estimator

        active = [
            name for name, mod in [
                ("face_recognition", face_recognizer),
                ("object_detection", object_detector),
                ("ocr",              ocr_reader),
                ("depth_estimation", depth_estimator),
            ] if mod is not None
        ]
        logger.info("InferenceService ready — active modules: %s", active)

    # ── public API ────────────────────────────────────────────────────────────

    def process_frame(self, frame: np.ndarray, camera_id: str = "") -> dict:
        """
        Run all enabled AI modules on *frame*.

        Failures per-module are caught and recorded in result.errors;
        they do NOT abort the remaining modules.

        Returns a plain dict (safe for JSON serialisation).
        """
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            logger.warning("process_frame received an empty/invalid frame — skipped")
            return InferenceResult(camera_id=camera_id).to_dict()

        result     = InferenceResult(camera_id=camera_id)
        last_errors: dict[str, str] = {}

        result.faces   = self._safe_run("face_recognition", self._face,    "process",  frame, last_errors)
        result.objects = self._safe_run("object_detection", self._objects,  "detect",   frame, last_errors)
        result.ocr     = self._safe_run("ocr",              self._ocr,      "read",     frame, last_errors)

        if self._depth is not None:
            depth_raw = self._safe_run("depth_estimation", self._depth, "estimate", frame, last_errors,
                                       fallback=None)
            result.depth = depth_raw

        result.errors = last_errors

        if result.errors:
            logger.warning("Inference finished with errors: %s", list(result.errors))

        return result.to_dict()

    # ── internals ─────────────────────────────────────────────────────────────

    def _safe_run(
        self,
        name:       str,
        module:     Any,
        method:     str,
        frame:      np.ndarray,
        errors:     dict,
        fallback:   Any = None,
    ) -> Any:
        """Call module.method(frame) safely, returning fallback on any error."""
        if module is None:
            return fallback if fallback is not None else []
        try:
            fn = getattr(module, method)
            return fn(frame)
        except AttributeError:
            logger.error("Module '%s' has no method '%s'", name, method)
            errors[name] = f"no method '{method}'"
            return fallback if fallback is not None else []
        except Exception as exc:
            logger.error("Module '%s.%s' failed: %s", name, method, exc, exc_info=True)
            errors[name] = str(exc)
            return fallback if fallback is not None else []


# ── factory ───────────────────────────────────────────────────────────────────

def build_inference_service() -> InferenceService:
    """
    Instantiate all AI modules and wire them into InferenceService.
    Heavy models are loaded here — call this once at app startup.
    """
    from backend.core.config import settings

    # ── Face Recognition ──────────────────────────────────────────────────────
    face_recognizer = None
    try:
        from backend.ai_modules.face_recognition.recognizer import FaceRecognizer
        face_recognizer = FaceRecognizer(
            db_path=settings.FACE_DB_PATH,
            model_name=settings.FACE_MODEL,
            ctx_id=settings.FACE_CTX_ID,
            similarity_threshold=settings.FACE_SIMILARITY_THRESHOLD,
        )
        logger.info("FaceRecognizer loaded.")
    except Exception as exc:
        logger.error("FaceRecognizer failed to load: %s", exc)

    # ── Object Detection ──────────────────────────────────────────────────────
    object_detector = None
    try:
        from backend.ai_modules.object_detection.detector import ObjectDetector
        object_detector = ObjectDetector(
            model_path=settings.YOLO_MODEL_PATH,
            confidence=settings.YOLO_CONFIDENCE,
            img_size=settings.YOLO_IMG_SIZE,
            device=settings.YOLO_DEVICE,
        )
        logger.info("ObjectDetector loaded.")
    except Exception as exc:
        logger.error("ObjectDetector failed to load: %s", exc)

    # ── OCR ───────────────────────────────────────────────────────────────────
    ocr_reader = None
    try:
        from backend.ai_modules.ocr.reader import OCRReader
        ocr_reader = OCRReader(
            languages=settings.OCR_LANGUAGES,
            gpu=settings.OCR_GPU,
            confidence_threshold=settings.OCR_CONFIDENCE_THRESHOLD,
        )
        logger.info("OCRReader loaded.")
    except Exception as exc:
        logger.error("OCRReader failed to load: %s", exc)

    # ── Depth Estimation (optional) ───────────────────────────────────────────
    depth_estimator = None
    if settings.DEPTH_ENABLED:
        try:
            from backend.ai_modules.depth_estimation.depth_estimator import DepthEstimator
            depth_estimator = DepthEstimator(
                model_name=settings.DEPTH_MODEL,
                device=settings.DEPTH_DEVICE,
            )
            logger.info("DepthEstimator loaded.")
        except Exception as exc:
            logger.error("DepthEstimator failed to load: %s", exc)

    return InferenceService(
        face_recognizer=face_recognizer,
        object_detector=object_detector,
        ocr_reader=ocr_reader,
        depth_estimator=depth_estimator,
    )