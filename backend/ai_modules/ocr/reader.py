"""
ai_modules/ocr/reader.py
=========================
EasyOCR-based text recognition wrapper.

Public interface (matches InferenceService contract):
    reader  = OCRReader()
    results = reader.read(frame)   # frame = BGR numpy array

Result format (list of dicts, sorted by confidence desc):
    [
        {"text": "STOP",    "confidence": 0.95},
        {"text": "100 km/h","confidence": 0.82},
        ...
    ]

NOTE: The module-level `process(frame)` function is preserved for
backward compatibility with older scripts that call it directly.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import cv2
import numpy as np

from backend.ai_modules.ocr.preprocessor import (
    preprocess_frame,
    get_scales,
    extract_color_regions,
)

logger = logging.getLogger(__name__)


class OCRReader:
    """
    Multi-scale EasyOCR text reader with colour-region cropping.

    Parameters
    ----------
    languages:             EasyOCR language codes, e.g. ["fr", "en"]
    gpu:                   Use GPU for EasyOCR inference (requires CUDA).
    confidence_threshold:  Minimum confidence to accept a text token.
    """

    def __init__(
        self,
        languages:            list[str] = None,
        gpu:                  bool      = False,
        confidence_threshold: float     = 0.3,
    ) -> None:
        if languages is None:
            languages = ["fr", "en"]

        self._threshold = confidence_threshold

        try:
            import easyocr as _easyocr
        except ImportError as exc:
            raise ImportError(
                "easyocr not installed — run: pip install easyocr"
            ) from exc

        logger.info("Loading EasyOCR (languages=%s, gpu=%s) …", languages, gpu)
        self._reader = _easyocr.Reader(languages, gpu=gpu)
        logger.info("EasyOCR ready.")

    # ── public API ────────────────────────────────────────────────────────────

    def read(self, frame: np.ndarray) -> list[dict]:
        """
        Run multi-scale OCR on *frame*.

        Returns
        -------
        List of {"text": str, "confidence": float} dicts sorted by confidence.
        Empty list if no text detected above threshold.
        """
        if frame is None or frame.size == 0:
            return []

        seen: dict[str, float] = {}

        # 1. Multi-scale scan of the full frame
        for scaled in get_scales(frame):
            preprocessed = preprocess_frame(scaled)
            self._scan_image(preprocessed, seen)

        # 2. Colour-region crops (signs, labels, etc.)
        for crop in extract_color_regions(frame):
            h, w = crop.shape[:2]
            crop_up = cv2.resize(crop, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
            preprocessed_crop = preprocess_frame(crop_up)
            self._scan_image(preprocessed_crop, seen, threshold=0.25)

        # 3. Sort by confidence and return
        sorted_items = sorted(seen.items(), key=lambda x: x[1], reverse=True)
        return [{"text": text, "confidence": round(conf, 3)} for text, conf in sorted_items]

    # ── internals ─────────────────────────────────────────────────────────────

    def _scan_image(
        self,
        image:     np.ndarray,
        seen:      dict,
        threshold: Optional[float] = None,
    ) -> None:
        """Run EasyOCR on *image* and update *seen* with best-confidence results."""
        limit = threshold if threshold is not None else self._threshold
        try:
            raw = self._reader.readtext(
                image,
                detail=1,
                paragraph=False,
                width_ths=0.7,
                contrast_ths=0.1,
            )
            for (_, text, confidence) in raw:
                cleaned = text.strip()
                if confidence >= limit and _is_useful(cleaned):
                    if cleaned not in seen or seen[cleaned] < confidence:
                        seen[cleaned] = confidence
        except Exception as exc:
            logger.debug("EasyOCR scan failed on sub-image: %s", exc)


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_useful(text: str) -> bool:
    """Reject empty strings and pure-punctuation noise."""
    text = text.strip()
    if len(text) < 2:
        return False
    if re.fullmatch(r"[^\w\s]+", text):
        return False
    return True


# ── backward-compat module-level function ────────────────────────────────────
# Older scripts that call `from ai_modules.ocr.reader import process` still work.

_default_reader: Optional[OCRReader] = None


def _get_default_reader() -> OCRReader:
    global _default_reader
    if _default_reader is None:
        _default_reader = OCRReader()
    return _default_reader


def process(frame: np.ndarray) -> dict:
    """
    Legacy module-level function kept for backward compatibility.
    Returns the old format: {"ocr_text": str, "details": list[dict]}
    """
    reader  = _get_default_reader()
    details = reader.read(frame)
    return {
        "ocr_text": " | ".join(d["text"] for d in details),
        "details":  details,
    }