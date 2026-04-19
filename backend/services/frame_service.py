"""
services/frame_service.py
==========================
Frame pre-processing service.

Responsibilities:
  - Resize oversized frames to a configured max dimension (keeps aspect ratio)
  - Validate frame integrity (non-null, non-empty, correct dtype)
  - Optional: flip, rotate, exposure normalisation

Called by WorkerPool workers BEFORE handing frames to InferenceService.
Keeps AI modules free of any normalisation logic.

Usage:
    service = FrameService(max_width=640, max_height=480)
    frame   = service.prepare(raw_frame)
    if frame is not None:
        result = inference_service.process_frame(frame)
"""

from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class FrameService:
    """
    Lightweight pre-processor for raw camera frames.

    Parameters
    ----------
    max_width  : Resize wider frames to this width (aspect-ratio preserved).
    max_height : Resize taller frames to this height (aspect-ratio preserved).
    flip_code  : cv2 flip code: None=no flip, 0=vertical, 1=horizontal, -1=both.
    """

    def __init__(
        self,
        max_width:  int = 640,
        max_height: int = 480,
        flip_code:  Optional[int] = None,
    ) -> None:
        self.max_width  = max_width
        self.max_height = max_height
        self.flip_code  = flip_code

    # ── public API ────────────────────────────────────────────────────────────

    def prepare(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Validate and pre-process a raw frame.

        Returns
        -------
        Processed numpy array, or None if the frame is invalid.
        """
        if not self._is_valid(frame):
            return None

        frame = self._resize_if_needed(frame)

        if self.flip_code is not None:
            frame = cv2.flip(frame, self.flip_code)

        return frame

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _is_valid(frame: Optional[np.ndarray]) -> bool:
        if frame is None:
            return False
        if not isinstance(frame, np.ndarray):
            logger.warning("FrameService: received non-ndarray frame (%s)", type(frame))
            return False
        if frame.size == 0:
            logger.warning("FrameService: received empty frame")
            return False
        if frame.ndim not in (2, 3):
            logger.warning("FrameService: unexpected frame dimensions: %d", frame.ndim)
            return False
        return True

    def _resize_if_needed(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if w <= self.max_width and h <= self.max_height:
            return frame

        scale = min(self.max_width / w, self.max_height / h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)