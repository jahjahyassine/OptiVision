"""
WebSocket Server — receives base64 JPEG frames from ESP32 cameras.
Non-blocking, async, supports multiple concurrent clients.
"""

import asyncio
import base64
import logging
from typing import Dict

import cv2
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from backend.core.frame_queue import FrameQueue

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages multiple concurrent ESP32 WebSocket connections."""

    def __init__(self, frame_queue: FrameQueue):
        self._active: Dict[str, WebSocket] = {}
        self._frame_queue = frame_queue

    async def connect(self, client_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._active[client_id] = websocket
        logger.info("Client connected: %s  (total=%d)", client_id, len(self._active))

    def disconnect(self, client_id: str) -> None:
        self._active.pop(client_id, None)
        logger.info("Client disconnected: %s  (total=%d)", client_id, len(self._active))

    async def handle(self, client_id: str, websocket: WebSocket) -> None:
        """Main receive loop — decodes frames and pushes to FrameQueue."""
        await self.connect(client_id, websocket)
        try:
            async for message in websocket.iter_text():
                frame = _decode_frame(message)
                if frame is not None:
                    await asyncio.get_event_loop().run_in_executor(
                        None, self._frame_queue.put, frame
                    )
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.error("Error on client %s: %s", client_id, exc)
        finally:
            self.disconnect(client_id)


# ── helper ────────────────────────────────────────────────────────────────────

def _decode_frame(raw: str) -> np.ndarray | None:
    """Decode a base64 JPEG string into an OpenCV BGR numpy array."""
    try:
        # Strip optional data-URI prefix: "data:image/jpeg;base64,..."
        if "," in raw:
            raw = raw.split(",", 1)[1]
        jpg_bytes = base64.b64decode(raw)
        buf = np.frombuffer(jpg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("cv2.imdecode returned None")
        return frame
    except Exception as exc:
        logger.warning("Frame decode failed: %s", exc)
        return None


# ── FastAPI route integration ─────────────────────────────────────────────────
# Register this inside your FastAPI app:
#
#   manager = ConnectionManager(frame_queue)
#
#   @app.websocket("/ws/{client_id}")
#   async def camera_endpoint(websocket: WebSocket, client_id: str):
#       await manager.handle(client_id, websocket)