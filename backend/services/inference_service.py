"""
services/inference_service.py
==============================
Central AI orchestrator — runs all 4 modules on a single frame
CONCURRENTLY using a dedicated ThreadPoolExecutor, with a shared
150 ms hard deadline across all modules.

Parallelism model:
  All 4 futures are submitted simultaneously.
  Results are collected with the REMAINING time to the shared deadline.
  If a module stalls, only its result is dropped — others still land.

Called from WorkerPool worker threads (not the asyncio event loop).
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from backend.core.config import settings

logger = logging.getLogger(__name__)

# 150 ms hard budget — matches the Fusion Engine spec
_INFERENCE_TIMEOUT_S = settings.INFERENCE_TIMEOUT_MS / 1000

# ── result schema ─────────────────────────────────────────────────────────────

@dataclass
class InferenceResult:
    """Unified output for one frame processed through all AI modules."""

    faces:     list[dict]     = field(default_factory=list)
    objects:   list[dict]     = field(default_factory=list)
    ocr:       list[dict]     = field(default_factory=list)
    depth:     Optional[Any]  = None
    timestamp: float          = field(default_factory=time.time)
    camera_id: str            = ""
    errors:    dict[str, str] = field(default_factory=dict)
    latency_ms: float         = 0.0

    def to_dict(self) -> dict:
        depth_out = self.depth
        if hasattr(depth_out, "tolist"):
            depth_out = depth_out.tolist()
        return {
            "faces":      self.faces,
            "objects":    self.objects,
            "ocr":        self.ocr,
            "depth":      depth_out,
            "timestamp":  self.timestamp,
            "camera_id":  self.camera_id,
            "errors":     self.errors,
            "latency_ms": round(self.latency_ms, 1),
        }


# ── service ───────────────────────────────────────────────────────────────────

class InferenceService:
    """
    Orchestrates all AI modules for a single frame using parallel execution.

    All modules run concurrently via a ThreadPoolExecutor.
    A shared 150 ms deadline ensures the pipeline never stalls waiting
    for a slow module — timed-out results are replaced with empty defaults.

    Module interfaces expected
    --------------------------
    face_recognizer  : .process(frame: ndarray) -> list[dict]
    object_detector  : .detect(frame: ndarray)  -> list[dict]
    ocr_reader       : .read(frame: ndarray)     -> list[dict]
    depth_estimator  : .estimate(frame: ndarray) -> dict | None
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

        # One dedicated executor for AI sub-tasks.
        # max_workers=4: one thread per module, all run simultaneously.
        self._executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="ai-module",
        )

        active = [
            name for name, mod in [
                ("face_recognition", face_recognizer),
                ("object_detection", object_detector),
                ("ocr",              ocr_reader),
                ("depth_estimation", depth_estimator),
            ] if mod is not None
        ]
        logger.info("InferenceService ready — active modules: %s", active)

    def shutdown(self) -> None:
        """Release thread pool resources. Call once at app shutdown."""
        self._executor.shutdown(wait=False)

    # ── public API ────────────────────────────────────────────────────────────

    def process_frame(self, frame: np.ndarray, camera_id: str = "") -> dict:
        """
        Run all enabled AI modules concurrently on *frame*.

        All 4 futures are submitted simultaneously.  Results are collected
        with the remaining wall-clock time to a 150 ms shared deadline.
        A module that exceeds the deadline is cancelled; its result defaults
        to [] / None so the pipeline continues unblocked.

        Returns a plain dict safe for JSON serialisation.
        """
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            logger.warning("process_frame: invalid frame — skipped")
            return InferenceResult(camera_id=camera_id).to_dict()

        t_start  = time.monotonic()
        deadline = t_start + _INFERENCE_TIMEOUT_S
        errors: dict[str, str] = {}

        # ── Submit all tasks simultaneously ───────────────────────────────────
        task_specs = [
            ("faces",   self._face,    "process",  []),
            ("objects", self._objects, "detect",   []),
            ("ocr",     self._ocr,     "read",     []),
            ("depth",   self._depth,   "estimate", None),
        ]

        futures: list[tuple[str, concurrent.futures.Future, Any]] = []
        for key, module, method, default in task_specs:
            if module is None:
                continue
            fut = self._executor.submit(self._call_module, key, module, method, frame)
            futures.append((key, fut, default))

        # ── Collect results with per-remaining-time timeout ───────────────────
        results: dict[str, Any] = {
            "faces": [], "objects": [], "ocr": [], "depth": None,
        }

        for key, fut, default in futures:
            remaining = deadline - time.monotonic()
            try:
                results[key] = fut.result(timeout=max(0.001, remaining))
            except concurrent.futures.TimeoutError:
                fut.cancel()
                results[key] = default
                errors[key]  = f"timeout > {settings.INFERENCE_TIMEOUT_MS:.0f}ms"
                logger.warning("Module '%s' exceeded %.0f ms budget — dropped",
                               key, settings.INFERENCE_TIMEOUT_MS)
            except Exception as exc:
                results[key] = default
                errors[key]  = str(exc)
                logger.error("Module '%s' failed: %s", key, exc, exc_info=True)

        latency_ms = (time.monotonic() - t_start) * 1000
        if latency_ms > settings.INFERENCE_TIMEOUT_MS:
            logger.warning("Frame inference total=%.1f ms exceeded budget", latency_ms)

        return InferenceResult(
            faces      = results["faces"]   or [],
            objects    = results["objects"] or [],
            ocr        = results["ocr"]     or [],
            depth      = results["depth"],
            camera_id  = camera_id,
            errors     = errors,
            latency_ms = latency_ms,
        ).to_dict()

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _call_module(name: str, module: Any, method: str, frame: np.ndarray) -> Any:
        """
        Execute module.method(frame) in a sub-thread.
        Propagates exceptions so the caller can distinguish timeout vs error.
        """
        fn = getattr(module, method)
        return fn(frame)


# ── factory ───────────────────────────────────────────────────────────────────

def build_inference_service() -> InferenceService:
    """
    Instantiate all AI modules and wire them into InferenceService.
    Heavy models are loaded here — call once at app startup.
    Module load failures are logged but do not abort startup.
    """
    from backend.core.config import settings

    face_recognizer = _load_module(
        "FaceRecognizer",
        "backend.ai_modules.face_recognition.recognizer",
        "FaceRecognizer",
        db_path=settings.FACE_DB_PATH,
        model_name=settings.FACE_MODEL,
        ctx_id=settings.FACE_CTX_ID,
        similarity_threshold=settings.FACE_SIMILARITY_THRESHOLD,
    )

    object_detector = _load_module(
        "ObjectDetector",
        "backend.ai_modules.object_detection.detector",
        "ObjectDetector",
        model_path=settings.YOLO_MODEL_PATH,
        confidence=settings.YOLO_CONFIDENCE,
        img_size=settings.YOLO_IMG_SIZE,
        device=settings.YOLO_DEVICE,
    )

    ocr_reader = _load_module(
        "OCRReader",
        "backend.ai_modules.ocr.reader",
        "OCRReader",
        languages=settings.OCR_LANGUAGES,
        gpu=settings.OCR_GPU,
        confidence_threshold=settings.OCR_CONFIDENCE_THRESHOLD,
    )

    depth_estimator = None
    if settings.DEPTH_ENABLED:
        depth_estimator = _load_module(
            "DepthEstimator",
            "backend.ai_modules.depth_estimation.depth_estimator",
            "DepthEstimator",
            model_name=settings.DEPTH_MODEL,
            device=settings.DEPTH_DEVICE,
        )

    return InferenceService(
        face_recognizer=face_recognizer,
        object_detector=object_detector,
        ocr_reader=ocr_reader,
        depth_estimator=depth_estimator,
    )


def _load_module(label: str, module_path: str, class_name: str, **kwargs) -> Any:
    """Import and instantiate an AI module; return None on failure."""
    import importlib
    try:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        instance = cls(**kwargs)
        logger.info("%s loaded.", label)
        return instance
    except Exception as exc:
        logger.error("%s failed to load: %s", label, exc)
        return None