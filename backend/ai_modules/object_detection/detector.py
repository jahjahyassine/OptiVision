"""
ai_modules/object_detection/detector.py
========================================
YOLOv8 obstacle/object detection wrapper.

Public interface (matches InferenceService contract):
    detector = ObjectDetector()
    results  = detector.detect(frame)      # frame = BGR numpy array

Result format:
    [
        {
            "label":         "person",
            "confidence":    0.87,
            "bbox":          [x1, y1, x2, y2],   # pixel coords
            "distance_est":  "close",              # heuristic based on bbox height
        },
        ...
    ]

Model weights:
    The default path is:
        backend/ai_modules/object_detection/models/yolov8n.pt
    If the file does not exist, ultralytics will download it automatically
    from the Ultralytics CDN on first run.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Absolute default model path (resolved from this file's location so it works
# regardless of the current working directory)
_DEFAULT_MODEL_PATH = (
    Path(__file__).parent / "models" / "yolov8n.pt"
)


class ObjectDetector:
    """
    YOLOv8-based object detector.

    Parameters
    ----------
    model_path  : Path to a YOLOv8 .pt weights file.
                  If the file does not exist, ultralytics downloads it.
    confidence  : Minimum detection confidence (0–1).
    img_size    : Inference image size (smaller = faster, lower accuracy).
    device      : "cuda" | "cpu" | "mps"
    """

    def __init__(
        self,
        model_path: str | Path = _DEFAULT_MODEL_PATH,
        confidence: float       = 0.45,
        img_size:   int         = 416,
        device:     str         = "cuda",
    ) -> None:
        self.confidence = confidence
        self.img_size   = img_size
        self.device     = device

        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ImportError(
                "ultralytics not installed — run: pip install ultralytics"
            ) from exc

        model_path = Path(model_path)
        if not model_path.exists():
            logger.warning(
                "Model file not found at %s — ultralytics will attempt to download yolov8n.pt",
                model_path,
            )
            # Fall back to model name so ultralytics handles the download
            model_path = Path(model_path.name)

        logger.info("Loading YOLO model: %s (device=%s)", model_path, device)
        self._model = YOLO(str(model_path))
        logger.info("YOLO model ready.")

    # ── public API ────────────────────────────────────────────────────────────

    def detect(self, frame: np.ndarray) -> list[dict]:
        """
        Run YOLOv8 on *frame* and return a list of detection dicts.

        Parameters
        ----------
        frame : BGR uint8 numpy array (direct from OpenCV).

        Returns
        -------
        List of detection dicts; empty list if nothing detected.
        """
        if frame is None or frame.size == 0:
            return []

        results = self._model(
            frame,
            conf=self.confidence,
            imgsz=self.img_size,
            verbose=False,
            device=self.device,
        )

        detections: list[dict] = []
        for box in results[0].boxes:
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
            label      = self._model.names[int(box.cls)]
            confidence = float(box.conf)
            height     = y2 - y1

            detections.append({
                "label":        label,
                "confidence":   round(confidence, 3),
                "bbox":         [x1, y1, x2, y2],
                "distance_est": self._estimate_distance(height),
            })

        return detections

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _estimate_distance(bbox_height_px: int) -> str:
        """
        Rough distance heuristic based on bounding-box height.
        Assumes a standard 480-px tall frame.
        Calibrate these thresholds to your actual camera/lens combination.
        """
        if bbox_height_px > 300:
            return "very_close"   # < ~0.5 m
        elif bbox_height_px > 150:
            return "close"        # ~0.5 – 1.5 m
        elif bbox_height_px > 70:
            return "medium"       # ~1.5 – 3 m
        return "far"              # > ~3 m


# ── backward-compat alias (the old name used in tests / scripts) ──────────────
ObstacleDetector = ObjectDetector