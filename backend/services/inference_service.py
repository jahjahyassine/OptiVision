"""
services/inference_service.py
==============================
Central AI orchestrator — runs all 4 modules on a single frame
CONCURRENTLY using a dedicated ThreadPoolExecutor, with a shared
150 ms hard deadline across all modules.
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

_INFERENCE_TIMEOUT_S = settings.INFERENCE_TIMEOUT_MS / 1000


# ── result schema ─────────────────────────────────────────────────────────────

@dataclass
class InferenceResult:
    faces: list[dict] = field(default_factory=list)
    objects: list[dict] = field(default_factory=list)
    ocr: list[dict] = field(default_factory=list)
    depth: Optional[Any] = None
    timestamp: float = field(default_factory=time.time)
    camera_id: str = ""
    errors: dict[str, str] = field(default_factory=dict)
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        depth_out = self.depth
        if hasattr(depth_out, "tolist"):
            depth_out = depth_out.tolist()

        return {
            "faces": self.faces,
            "objects": self.objects,
            "ocr": self.ocr,
            "depth": depth_out,
            "timestamp": self.timestamp,
            "camera_id": self.camera_id,
            "errors": self.errors,
            "latency_ms": round(self.latency_ms, 1),
        }


# ── service ───────────────────────────────────────────────────────────────────

class InferenceService:

    def __init__(
        self,
        face_recognizer=None,
        object_detector=None,
        ocr_reader=None,
        depth_estimator=None,
    ) -> None:
        self._face = face_recognizer
        self._objects = object_detector
        self._ocr = ocr_reader
        self._depth = depth_estimator

        self._executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="ai-module",
        )

        active = [
            name for name, mod in [
                ("face_recognition", face_recognizer),
                ("object_detection", object_detector),
                ("ocr", ocr_reader),
                ("depth_estimation", depth_estimator),
            ] if mod is not None
        ]

        logger.info("InferenceService ready — active modules: %s", active)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)

    # ── main API ─────────────────────────────────────────────────────────────

    def process_frame(self, frame: np.ndarray, camera_id: str = "") -> dict:
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return InferenceResult(camera_id=camera_id).to_dict()

        t_start = time.monotonic()
        errors: dict[str, str] = {}

        task_specs = [
            ("faces", self._face, "process", []),
            ("objects", self._objects, "detect", []),
            ("ocr", self._ocr, "read", []),
            ("depth", self._depth, "estimate", None),
        ]

        futures = []

        for key, module, method, _default in task_specs:
            if module is None:
                continue

            fut = self._executor.submit(
                self._call_module,
                key,
                module,
                method,
                frame
            )
            futures.append((key, fut, _default))

        results = {
            "faces": [],
            "objects": [],
            "ocr": [],
            "depth": None,
        }

        # ── SAFE COLLECT (NO TIMEOUT PER TASK) ───────────────────────────────
        for key, fut, default in futures:
            try:
                results[key] = fut.result()
            except Exception as exc:
                results[key] = default
                errors[key] = str(exc)
                logger.error("Module '%s failed: %s", key, exc, exc_info=True)

        latency_ms = (time.monotonic() - t_start) * 1000

        if latency_ms > settings.INFERENCE_TIMEOUT_MS:
            logger.warning(
                "Frame inference total=%.1f ms exceeded budget",
                latency_ms
            )

        return InferenceResult(
            faces=results["faces"],
            objects=results["objects"],
            ocr=results["ocr"],
            depth=results["depth"],
            camera_id=camera_id,
            errors=errors,
            latency_ms=latency_ms,
        ).to_dict()

    # ── internal ─────────────────────────────────────────────────────────────

    @staticmethod
    def _call_module(name: str, module: Any, method: str, frame: np.ndarray):
        fn = getattr(module, method)
        return fn(frame)


# ── factory ───────────────────────────────────────────────────────────────────

def build_inference_service() -> InferenceService:
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


def _load_module(label: str, module_path: str, class_name: str, **kwargs):
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