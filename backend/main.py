"""
backend/main.py
===============
FastAPI application entry point for OptiVision.

Startup sequence:
  1. Build InferenceService (loads all AI models)
  2. Create FrameQueue
  3. Start WorkerPool (N background threads)
  4. Start ConnectionManager (WebSocket handler)
  5. Register /ws/{camera_id} WebSocket endpoint
  6. Register /api/* HTTP REST routes

Run:
    cd project-root
    uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

# ── path setup (allows running from project-root OR from backend/) ────────────
_BACKEND_DIR  = Path(__file__).parent.resolve()
_PROJECT_ROOT = _BACKEND_DIR.parent.resolve()
for _p in (str(_PROJECT_ROOT), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── internal imports ──────────────────────────────────────────────────────────
from backend.core.config import settings
from backend.core.frame_queue import FrameQueue
from backend.core.worker_pool import WorkerPool
from backend.communication.websocket_server.websocket_server import ConnectionManager
from backend.services.inference_service import build_inference_service
from backend.fusion_engine.decision_engine import DecisionEngine
from backend.api.routes.faces import router as faces_router

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── global singletons (initialised inside lifespan) ───────────────────────────
frame_queue:        FrameQueue | None       = None
worker_pool:        WorkerPool | None       = None
connection_manager: ConnectionManager | None = None
decision_engine:    DecisionEngine | None   = None


# ── lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot all heavy components before accepting requests; tear down cleanly."""
    global frame_queue, worker_pool, connection_manager, decision_engine

    logger.info("OptiVision startup …")

    # 1. Build AI pipeline
    inference_service = build_inference_service()
    decision_engine   = DecisionEngine(
        confidence_threshold=settings.DECISION_CONFIDENCE_THRESHOLD,
        identity_priority=settings.DECISION_IDENTITY_PRIORITY,
    )

    # 2. Frame queue (thread-safe, bounded)
    frame_queue = FrameQueue(maxsize=settings.FRAME_QUEUE_SIZE)

    # 3. Worker pool — each worker: get frame → infer → decide → log/TTS
    def _on_result(raw: dict) -> None:
        decision = decision_engine.decide(raw)
        logger.info("Decision: [%s] %s", decision["priority"], decision["primary_label"])

    worker_pool = WorkerPool(
        frame_queue=frame_queue,
        inference_fn=inference_service.process_frame,
        n_workers=settings.N_WORKERS,
        on_result=_on_result,
    )
    worker_pool.start()

    # 4. WebSocket connection manager
    connection_manager = ConnectionManager(frame_queue=frame_queue)

    logger.info("OptiVision ready — listening for cameras.")
    yield  # ← application runs here

    # ── shutdown ──────────────────────────────────────────────────────────────
    logger.info("OptiVision shutting down …")
    if worker_pool:
        worker_pool.stop()
    logger.info("Shutdown complete.")


# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="OptiVision",
    description="Real-time AI vision pipeline for assistive navigation",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws/{camera_id}")
async def camera_endpoint(websocket: WebSocket, camera_id: str):
    """
    Main entry point for ESP32 cameras.

    Expected message format (JSON):
        { "frame": "<base64-encoded JPEG>" }

    Or raw binary JPEG bytes (set binaryType = 'arraybuffer' on the client).
    """
    if connection_manager is None:
        await websocket.close(code=1011, reason="Server not ready")
        return
    await connection_manager.handle(camera_id, websocket)


# ── REST API routes ───────────────────────────────────────────────────────────

app.include_router(faces_router, prefix="/api/faces", tags=["Face Recognition"])


@app.get("/health", tags=["System"])
async def health():
    """Liveness probe."""
    return {
        "status":         "ok",
        "queue_size":     frame_queue.qsize() if frame_queue else 0,
        "active_cameras": len(connection_manager._active) if connection_manager else 0,
    }


# ── dev runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level=settings.LOG_LEVEL.lower(),
    )