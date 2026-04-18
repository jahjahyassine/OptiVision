"""
routes/faces.py
===============
FastAPI router for face enrollment and management.

Mounted in backend/main.py as:
    from api.routes.faces import router as faces_router
    app.include_router(faces_router, prefix="/api/faces", tags=["Face Recognition"])

Endpoints
---------
POST   /api/faces/enroll      — multipart upload: enroll a face
GET    /api/faces/             — list all enrolled persons
DELETE /api/faces/{name}       — remove a person
POST   /api/faces/identify     — dev/test: identify a face in an uploaded image
"""

from __future__ import annotations

import logging

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

# Imports are relative to backend/ (the directory where main.py lives)
from ai_modules.face_recognition import FaceRecognizer

logger = logging.getLogger(__name__)
router = APIRouter()

# Module-level singleton — initialised once on first request, reused after that
_recognizer: FaceRecognizer | None = None


def get_recognizer() -> FaceRecognizer:
    global _recognizer
    if _recognizer is None:
        _recognizer = FaceRecognizer()   # picks up default DB path automatically
    return _recognizer


def _decode_image(data: bytes) -> np.ndarray:
    """Decode raw image bytes → BGR numpy array."""
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Cannot decode the uploaded image.")
    return img


# ─────────────────────────── endpoints ────────────────────────────────────────

@router.post("/enroll")
async def enroll_face(
    name: str         = Form(..., description="Person's display name"),
    relationship: str = Form("",  description="e.g. friend / family / colleague"),
    image: UploadFile = File(...,  description="Face photo (JPEG or PNG)"),
):
    """
    Enroll a new face from an uploaded image.

    curl:
        curl -X POST http://localhost:8000/api/faces/enroll \\
             -F "name=Ronaldo" -F "relationship=celebrity" \\
             -F "image=@dataset/faces/Ronaldo/image.png"
    """
    frame = _decode_image(await image.read())
    rec = get_recognizer()

    ok = rec.enroll_from_frame(frame, name=name, relationship=relationship)
    if not ok:
        raise HTTPException(
            status_code=422,
            detail=(
                "No face detected in the uploaded image. "
                "Please use a clear, well-lit frontal photo."
            ),
        )

    return {"status": "enrolled", "name": name, "relationship": relationship}


@router.get("/")
async def list_faces():
    """Return all enrolled persons and database statistics."""
    rec = get_recognizer()
    return {
        "total_embeddings": rec.db.count(),
        "total_persons":    rec.db.person_count(),
        "persons":          rec.list_enrolled(),
    }


@router.delete("/{name}")
async def delete_face(name: str):
    """Remove all embeddings for the given person name."""
    rec = get_recognizer()
    deleted = rec.remove_person(name)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"No person named '{name}' found.")
    return {"status": "deleted", "name": name, "embeddings_removed": deleted}


@router.post("/identify")
async def identify_face(
    image: UploadFile = File(..., description="Image containing a face to identify"),
):
    """
    Dev / test endpoint — identify a face in a single uploaded image.
    Not used in the real-time WebSocket pipeline.
    """
    frame = _decode_image(await image.read())
    rec = get_recognizer()
    results = rec.process(frame)

    # Strip internal _embedding field before serialising to JSON
    clean = [{k: v for k, v in r.items() if k != "_embedding"} for r in results]
    return {"faces_detected": len(clean), "results": clean}