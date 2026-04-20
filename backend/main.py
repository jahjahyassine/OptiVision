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

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

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
_broadcast_queue:   Optional[asyncio.Queue] = None  # Thread-safe broadcast queue
_event_loop:        Optional[asyncio.AbstractEventLoop] = None  # Main app event loop


# ── lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot all heavy components before accepting requests; tear down cleanly."""
    global frame_queue, worker_pool, connection_manager, dashboard_manager, decision_engine, audio_queue, state_manager, _broadcast_queue, _event_loop

    logger.info("OptiVision startup …")

    # Store reference to the main event loop for thread-safe operations
    _event_loop = asyncio.get_event_loop()
    _broadcast_queue = asyncio.Queue(maxsize=100)

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

    # 7. Background task to drain broadcast queue (runs in asyncio event loop)
    async def _broadcast_worker() -> None:
        """
        Drains the broadcast queue and sends messages to dashboard.
        Runs continuously in the asyncio event loop.
        """
        while True:
            try:
                msg = await asyncio.wait_for(_broadcast_queue.get(), timeout=1.0)
                if msg is None:  # Sentinel value for shutdown
                    break
                msg_type, payload = msg
                try:
                    if msg_type == "inference":
                        await dashboard_manager.broadcast_inference(payload)
                    elif msg_type == "decision":
                        await dashboard_manager.broadcast_decision(payload)
                except Exception as exc:
                    logger.warning("Dashboard broadcast (%s) failed: %s", msg_type, exc)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                logger.error("Broadcast worker error: %s", exc, exc_info=True)
                break

    # Create broadcast worker task
    broadcast_task = asyncio.create_task(_broadcast_worker())

    # 8. Worker pool — each worker: get frame → infer → decide → queue broadcast → audio
    def _on_result(raw: dict) -> None:
        """
        Callback from worker thread after inference completes.
        Chain: inference → decision → audio + async broadcast (non-blocking).
        
        Uses asyncio.run_coroutine_threadsafe() to safely notify the event loop
        from worker threads WITHOUT creating new event loops.
        """
        # Convert raw inference dict → decision
        decision = decision_engine.decide(raw)
        logger.debug(
            "Decision [score=%d] '%s'",
            decision["priority_score"], decision["alert_text"]
        )

        # Enqueue to audio system (thread-safe, fast, non-blocking)
        audio_queue.enqueue(decision)

        # Queue broadcast messages for async processing
        # This is thread-safe and non-blocking — just appends to queue
        if _event_loop and _broadcast_queue:
            try:
                # Use put_nowait to avoid blocking the worker thread
                _broadcast_queue.put_nowait(("inference", raw))
                _broadcast_queue.put_nowait(("decision", decision))
            except asyncio.QueueFull:
                logger.debug("Broadcast queue full — dropping oldest message")

    worker_pool = WorkerPool(
        frame_queue=frame_queue,
        inference_fn=inference_service.process_frame,
        n_workers=settings.N_WORKERS,
        on_result=_on_result,
    )
    worker_pool.start()

    # 9. WebSocket connection manager (receives frames from cameras)
    connection_manager = ConnectionManager(frame_queue=frame_queue, dashboard_manager=dashboard_manager)

    logger.info("OptiVision ready — listening for cameras.")
    yield  # ← application runs here (broadcast_task continues running)

    # ── shutdown ──────────────────────────────────────────────────────────────
    logger.info("OptiVision shutting down …")
    if worker_pool:
        worker_pool.stop()
    if audio_queue:
        audio_queue.stop()
    if inference_service:
        inference_service.shutdown()
    
    # Signal broadcast worker to stop
    if _broadcast_queue:
        try:
            _broadcast_queue.put_nowait(None)  # Sentinel
        except asyncio.QueueFull:
            pass
    
    # Wait for broadcast task to finish
    if broadcast_task:
        try:
            await asyncio.wait_for(broadcast_task, timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning("Broadcast worker did not exit within timeout")
            broadcast_task.cancel()
    
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
    """System health check — returns detailed component status."""
    import time
    
    # Check each component
    frame_queue_stats = frame_queue.stats if frame_queue else {}
    active_cameras = len(connection_manager._active) if connection_manager else 0
    audio_queue_size = audio_queue.qsize if hasattr(audio_queue, 'qsize') and audio_queue else 0
    worker_running = worker_pool.is_running if worker_pool else False
    
    # Determine overall health
    all_ok = (
        frame_queue is not None and
        worker_pool is not None and
        connection_manager is not None and
        worker_running and
        audio_queue is not None
    )
    
    return {
        "status":          "ok" if all_ok else "degraded",
        "timestamp":       time.time(),
        "components": {
            "frame_queue": {
                "ready": frame_queue is not None,
                "size": frame_queue_stats.get("size", 0),
                "total_received": frame_queue_stats.get("total_received", 0),
                "total_dropped": frame_queue_stats.get("total_dropped", 0),
                "drop_rate": frame_queue_stats.get("drop_rate", 0.0),
            },
            "worker_pool": {
                "ready": worker_pool is not None,
                "running": worker_running,
                "workers": settings.N_WORKERS,
            },
            "decision_engine": {
                "ready": decision_engine is not None,
            },
            "audio_queue": {
                "ready": audio_queue is not None,
                "pending": audio_queue_size,
            },
            "websocket": {
                "active_cameras": active_cameras,
            },
        },
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