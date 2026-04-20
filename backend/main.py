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
from backend.communication.dashboard_manager import DashboardManager
from backend.services.inference_service import build_inference_service
from backend.fusion_engine.decision_engine import DecisionEngine
from backend.fusion_engine.state_manager import StateManager
from backend.audio.audio_factory import build_audio_priority_queue
from backend.api.routes.faces import router as faces_router

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── global singletons (initialised inside lifespan) ───────────────────────────
frame_queue:        FrameQueue | None        = None
worker_pool:        WorkerPool | None        = None
connection_manager: ConnectionManager | None = None
dashboard_manager:  DashboardManager | None  = None
decision_engine:    DecisionEngine | None    = None
audio_queue:        object | None            = None  # AudioPriorityQueue
state_manager:      StateManager | None      = None


# ── lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot all heavy components before accepting requests; tear down cleanly."""
    global frame_queue, worker_pool, connection_manager, dashboard_manager, decision_engine, audio_queue, state_manager

    logger.info("OptiVision startup …")

    # 1. Build AI pipeline
    inference_service = build_inference_service()

    # 2. State manager for persistence tracking (used by audio queue)
    state_manager = StateManager()

    # 3. Decision engine (converts inference results → actionable decisions)
    decision_engine = DecisionEngine(
        confidence_threshold=settings.DECISION_CONFIDENCE_THRESHOLD,
        identity_priority=settings.DECISION_IDENTITY_PRIORITY,
    )

    # 4. Audio system (TTS + priority queue for alerts)
    audio_queue = build_audio_priority_queue(state_manager=state_manager)
    audio_queue.start()

    # 5. Dashboard manager (broadcasts results to browser clients)
    dashboard_manager = DashboardManager()

    # 6. Frame queue (thread-safe, bounded)
    frame_queue = FrameQueue(maxsize=settings.FRAME_QUEUE_SIZE)

    # 7. Worker pool — each worker: get frame → infer → decide → broadcast → TTS
    def _on_result(raw: dict) -> None:
        """
        Callback from worker thread after inference completes.
        Chain: inference → decision → audio/dashboard broadcast.
        """
        import asyncio

        # Convert raw inference dict → decision
        decision = decision_engine.decide(raw)
        logger.info(
            "Decision [score=%d] '%s'",
            decision["priority_score"], decision["alert_text"]
        )

        # Chain inference result → decision → audio queue
        audio_queue.enqueue(decision)

        # Broadcast to dashboard (async, non-blocking)
        # We schedule this in the event loop to avoid blocking the worker thread
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(dashboard_manager.broadcast_inference(raw))
            loop.run_until_complete(dashboard_manager.broadcast_decision(decision))
        except Exception as exc:
            logger.warning("Dashboard broadcast failed: %s", exc)

    worker_pool = WorkerPool(
        frame_queue=frame_queue,
        inference_fn=inference_service.process_frame,
        n_workers=settings.N_WORKERS,
        on_result=_on_result,
    )
    worker_pool.start()

    # 8. WebSocket connection manager (receives frames from cameras)
    connection_manager = ConnectionManager(frame_queue=frame_queue, dashboard_manager=dashboard_manager)

    logger.info("OptiVision ready — listening for cameras.")
    yield  # ← application runs here

    # ── shutdown ──────────────────────────────────────────────────────────────
    logger.info("OptiVision shutting down …")
    if worker_pool:
        worker_pool.stop()
    if audio_queue:
        audio_queue.stop()
    if inference_service:
        inference_service.shutdown()
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


@app.websocket("/ws/dashboard")
async def dashboard_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for browser-based dashboard monitoring.

    Clients connect here to receive real-time updates:
    - Inference results (faces, objects, OCR, depth)
    - Decisions (priority, alert text, confidence)
    - System statistics

    Messages sent to this endpoint are reflected back (heartbeat mechanism).
    """
    if dashboard_manager is None:
        await websocket.close(code=1011, reason="Server not ready")
        return
    await dashboard_manager.handle(websocket)


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