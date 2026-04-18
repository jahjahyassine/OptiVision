"""
ai_modules.face_recognition
============================
InsightFace-based real-time face recognition module.

Quick start
-----------
    from ai_modules.face_recognition import FaceRecognizer

    rec = FaceRecognizer()                            # loads model on first run
    rec.enroll_from_image_path("photos/john.jpg", name="John", relationship="friend")

    # In the frame loop:
    results = rec.process(frame)
    # results = [{"name": "John", "confidence": 0.87, "bbox": [...], "known": True}]
"""

from .recognizer import FaceRecognizer
from .embedding_db import EmbeddingDB

__all__ = ["FaceRecognizer", "EmbeddingDB"]