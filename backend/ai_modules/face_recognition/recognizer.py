"""
recognizer.py
=============
InsightFace (ArcFace backbone) face recognition wrapper.

Project structure assumed:
    project-root/
    ├── backend/
    │   ├── ai_modules/face_recognition/  ← this file lives here
    │   └── main.py
    ├── database/face_embeddings/faces.db ← DB stored here
    └── dataset/faces/<Name>/             ← enrollment photos here

Public interface (Team A contract):
    rec = FaceRecognizer()
    results = rec.process(frame)          # frame = BGR numpy array

Result format:
    [
        {
            "name":       "Ronaldo",
            "label":      "Ronaldo",       # alias for Fusion Engine
            "confidence": 0.87,            # cosine similarity 0–1
            "bbox":       [x1, y1, x2, y2],
            "known":      True,
        },
        ...
    ]
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

try:
    from insightface.app import FaceAnalysis
except ImportError as e:
    raise ImportError(
        "InsightFace not installed.\n"
        "GPU : pip install insightface onnxruntime-gpu\n"
        "CPU : pip install insightface onnxruntime\n"
        "Note: Python 3.14 support in InsightFace is not yet official — "
        "use Python 3.11 if you hit build errors."
    ) from e

from .embedding_db import EmbeddingDB

logger = logging.getLogger(__name__)

# ── path resolution ────────────────────────────────────────────────────────
# __file__ = project-root/backend/ai_modules/face_recognition/recognizer.py
# parents[0] = face_recognition/
# parents[1] = ai_modules/
# parents[2] = backend/
# parents[3] = project-root/

_PROJECT_ROOT    = Path(__file__).parents[3]
_DEFAULT_DB_PATH = _PROJECT_ROOT / "database" / "face_embeddings" / "faces.db"
_DEFAULT_MODEL_ROOT = Path(__file__).parent / "models" / "insightface"

# Cosine similarity threshold for a confirmed match.
# Raise to 0.55 to reduce false positives; lower to 0.35 if you're getting
# too many "Unknown" results on good-quality frames.
SIMILARITY_THRESHOLD = 0.45

# Ignore face detections smaller than this (pixels on the short side)
MIN_FACE_SIZE_PX = 40


class FaceRecognizer:
    """
    Real-time face recognition using InsightFace (ArcFace / buffalo_l model).

    Parameters
    ----------
    db_path             : SQLite file path.  Defaults to database/face_embeddings/faces.db
    model_name          : 'buffalo_l'  → most accurate, ~300 MB  ← RECOMMENDED
                          'buffalo_sc' → small/fast,   ~30 MB
    ctx_id              : 0 = GPU (CUDA), -1 = CPU only
    similarity_threshold: Cosine similarity cutoff for a confirmed match.
    model_root          : Where InsightFace caches downloaded weights.
    """

    def __init__(
        self,
        db_path: str | Path = _DEFAULT_DB_PATH,
        model_name: str = "buffalo_l",
        ctx_id: int = 0,
        similarity_threshold: float = SIMILARITY_THRESHOLD,
        model_root: Path = _DEFAULT_MODEL_ROOT,
    ):
        self.threshold = similarity_threshold
        self.db = EmbeddingDB(db_path)

        model_root.mkdir(parents=True, exist_ok=True)

        logger.info("Loading InsightFace model '%s' (ctx_id=%d) …", model_name, ctx_id)
        self._app = FaceAnalysis(
            name=model_name,
            root=str(model_root),
            providers=(
                ["CUDAExecutionProvider", "CPUExecutionProvider"]
                if ctx_id >= 0
                else ["CPUExecutionProvider"]
            ),
        )
        self._app.prepare(ctx_id=ctx_id, det_size=(640, 640))
        logger.info("InsightFace ready.")

    # ──────────────────────────── public API ──────────────────────────────────

    def process(self, frame: np.ndarray) -> list[dict]:
        """
        Main entry point — called every frame by the worker pool.

        Parameters
        ----------
        frame : BGR uint8 numpy array (direct from OpenCV / WebSocket ingestion).

        Returns
        -------
        List of face dicts (see module docstring). Empty list if no faces found.
        """
        if frame is None or frame.size == 0:
            return []

        faces = self._app.get(frame)
        if not faces:
            return []

        results = []
        for face in faces:
            bbox = [int(v) for v in face.bbox.tolist()]  # [x1, y1, x2, y2]

            face_h = bbox[3] - bbox[1]
            face_w = bbox[2] - bbox[0]
            if min(face_h, face_w) < MIN_FACE_SIZE_PX:
                continue

            embedding: np.ndarray = face.embedding   # shape (512,) float32
            name, similarity = self.db.find_closest(embedding)
            known = name is not None and similarity >= self.threshold

            results.append({
                "name":       name if known else "Unknown",
                "label":      name if known else "Unknown",
                "confidence": float(similarity) if known else 0.0,
                "bbox":       bbox,
                "known":      known,
                "_embedding": embedding,   # stripped before HTTP/WS responses
            })

        return results

    # ──────────────────────────── enrollment ──────────────────────────────────

    def enroll_from_frame(
        self,
        frame: np.ndarray,
        name: str,
        relationship: str = "",
    ) -> bool:
        """
        Detect the largest face in `frame`, extract its embedding, and store it.
        Returns True on success, False if no face detected.
        """
        faces = self._app.get(frame)
        if not faces:
            logger.warning("enroll_from_frame: no face detected.")
            return False

        largest = max(
            faces,
            key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
        )
        self.db.add_face(name=name, relationship=relationship, embedding=largest.embedding)
        logger.info("Enrolled '%s' (%s).", name, relationship or "—")
        return True

    def enroll_from_image_path(
        self,
        image_path: str | Path,
        name: str,
        relationship: str = "",
    ) -> bool:
        """Load an image from disk and enroll the detected face."""
        img = cv2.imread(str(image_path))
        if img is None:
            raise FileNotFoundError(f"Cannot read image: {image_path}")
        return self.enroll_from_frame(img, name, relationship)

    def enroll_from_multiple_images(
        self,
        image_paths: list[str | Path],
        name: str,
        relationship: str = "",
    ) -> int:
        """
        Enroll from several photos — more embeddings = more robust recognition.
        Returns the count of successfully stored embeddings.
        """
        count = 0
        for path in image_paths:
            try:
                if self.enroll_from_image_path(path, name, relationship):
                    count += 1
            except Exception as exc:
                logger.warning("Skipping %s: %s", path, exc)
        logger.info("Enrolled %d/%d images for '%s'.", count, len(image_paths), name)
        return count

    def enroll_from_dataset_folder(
        self,
        person_dir: str | Path,
        name: str | None = None,
        relationship: str = "",
    ) -> int:
        """
        Enroll all images inside a folder like:
            dataset/faces/Ronaldo/image.png
            dataset/faces/Ronaldo/image2.png

        `name` defaults to the folder name if not provided.
        Supports: .jpg, .jpeg, .png, .bmp, .webp
        """
        person_dir = Path(person_dir)
        if not person_dir.is_dir():
            raise NotADirectoryError(f"Not a directory: {person_dir}")

        resolved_name = name or person_dir.name
        image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        images = [p for p in sorted(person_dir.iterdir()) if p.suffix.lower() in image_exts]

        if not images:
            logger.warning("No images found in %s", person_dir)
            return 0

        return self.enroll_from_multiple_images(images, resolved_name, relationship)

    # ──────────────────────────── database helpers ────────────────────────────

    def list_enrolled(self) -> list[dict]:
        return self.db.list_all()

    def remove_person(self, name: str) -> int:
        return self.db.delete_person(name)

    # ──────────────────────────── debug / visualisation ──────────────────────

    def draw_results(
        self,
        frame: np.ndarray,
        results: list[dict],
        font_scale: float = 0.6,
    ) -> np.ndarray:
        """Overlay bounding boxes and name labels. Green = known, Red = unknown."""
        out = frame.copy()
        for r in results:
            x1, y1, x2, y2 = r["bbox"]
            color = (0, 200, 0) if r["known"] else (0, 0, 220)
            label = (
                f"{r['name']}  {r['confidence']:.0%}" if r["known"] else "Unknown"
            )
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                out, label, (x1, max(y1 - 8, 12)),
                cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, 2, cv2.LINE_AA,
            )
        return out