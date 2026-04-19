"""
ai_modules/depth_estimation/depth_estimator.py
===============================================
MiDaS-based monocular depth estimation wrapper.

Public interface (matches InferenceService contract):
    estimator = DepthEstimator()
    result    = estimator.estimate(frame)   # frame = BGR numpy array

Result format:
    {
        "depth_map":      [[...], ...],   # normalised 0-1 float32 2-D array
                                          #   (omitted from JSON if too large)
        "nearest_zone":   "left" | "center" | "right" | "none",
        "nearest_value":  0.87,           # 1.0 = closest, 0.0 = furthest
        "obstacle_alert": True,           # True if very_close obstacle detected
        "zones": {
            "left":   {"min": 0.72, "mean": 0.54},
            "center": {"min": 0.88, "mean": 0.61},
            "right":  {"min": 0.65, "mean": 0.43},
        }
    }

MiDaS note:
    MiDaS outputs INVERSE depth (higher value = closer).
    We normalise to [0, 1] so 1.0 always means "closest pixel".

Models (set DEPTH_MODEL in config or env):
    "MiDaS_small"  — fastest,  lowest accuracy  (~6 MB, CPU-friendly)
    "DPT_Hybrid"   — balanced, good accuracy     (~350 MB)
    "DPT_Large"    — slowest,  highest accuracy  (~1.3 GB)
"""

from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Obstacle threshold — if max normalised depth in center zone exceeds this,
# we flag obstacle_alert = True
OBSTACLE_THRESHOLD = 0.80


class DepthEstimator:
    """
    Monocular depth estimator using Intel MiDaS via torch.hub.

    Parameters
    ----------
    model_name : MiDaS model variant (see module docstring).
    device     : "cuda" | "cpu"
    """

    def __init__(
        self,
        model_name: str = "MiDaS_small",
        device:     str = "cuda",
    ) -> None:
        self.model_name = model_name

        try:
            import torch
        except ImportError as exc:
            raise ImportError(
                "PyTorch not installed — run: pip install torch torchvision"
            ) from exc

        import torch

        if device == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA not available — falling back to CPU for depth estimation")
            device = "cpu"

        self.device = torch.device(device)

        logger.info("Loading MiDaS model '%s' on %s …", model_name, device)
        self._model = torch.hub.load("intel-isl/MiDaS", model_name, trust_repo=True)
        self._model.to(self.device)
        self._model.eval()

        # Load the matching transform
        transforms = torch.hub.load("intel-isl/MiDaS", "transforms", trust_repo=True)
        if model_name in ("DPT_Large", "DPT_Hybrid"):
            self._transform = transforms.dpt_transform
        else:
            self._transform = transforms.small_transform

        logger.info("MiDaS ready.")
        self._torch = torch

    # ── public API ────────────────────────────────────────────────────────────

    def estimate(self, frame: np.ndarray) -> Optional[dict]:
        """
        Run depth estimation on *frame*.

        Parameters
        ----------
        frame : BGR uint8 numpy array.

        Returns
        -------
        dict (see module docstring) or None on error.
        """
        if frame is None or frame.size == 0:
            return None

        try:
            return self._run(frame)
        except Exception as exc:
            logger.error("DepthEstimator.estimate failed: %s", exc, exc_info=True)
            return None

    # ── internals ─────────────────────────────────────────────────────────────

    def _run(self, frame: np.ndarray) -> dict:
        import torch

        # MiDaS expects RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Apply model-specific transform → tensor
        input_batch = self._transform(rgb).to(self.device)

        with torch.no_grad():
            prediction = self._model(input_batch)
            # Interpolate back to original frame size
            prediction = torch.nn.functional.interpolate(
                prediction.unsqueeze(1),
                size=frame.shape[:2],
                mode="bicubic",
                align_corners=False,
            ).squeeze()

        depth_raw = prediction.cpu().numpy().astype(np.float32)

        # Normalise to [0, 1] — 1.0 = nearest
        d_min, d_max = depth_raw.min(), depth_raw.max()
        if d_max - d_min > 1e-6:
            depth_norm = (depth_raw - d_min) / (d_max - d_min)
        else:
            depth_norm = np.zeros_like(depth_raw)

        # Zone analysis (left / center / right thirds)
        h, w = depth_norm.shape
        zones = {
            "left":   depth_norm[:, :w // 3],
            "center": depth_norm[:, w // 3: 2 * w // 3],
            "right":  depth_norm[:, 2 * w // 3:],
        }

        zone_stats = {
            name: {
                "min":  round(float(arr.min()),  3),
                "mean": round(float(arr.mean()), 3),
            }
            for name, arr in zones.items()
        }

        # Find the zone with the highest "max depth" (closest obstacle)
        nearest_zone  = max(zones.keys(), key=lambda z: float(zones[z].max()))
        nearest_value = float(zones[nearest_zone].max())

        obstacle_alert = (
            nearest_zone == "center"
            and nearest_value >= OBSTACLE_THRESHOLD
        )

        return {
            # Full map omitted by default to keep JSON small.
            # Re-enable for debugging: "depth_map": depth_norm.tolist(),
            "nearest_zone":   nearest_zone,
            "nearest_value":  round(nearest_value, 3),
            "obstacle_alert": obstacle_alert,
            "zones":          zone_stats,
        }