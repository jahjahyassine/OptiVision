"""
websocket_server.py
===================
Async WebSocket server — receives frames from ESP32 cameras and feeds
them into the FrameQueue for downstream inference.

Supported frame formats
-----------------------
1. JSON text:   { "frame": "<base64-encoded JPEG>", "camera_id": "cam0" }
2. Plain text:  raw base64 string (data-URI prefix stripped automatically)
3. Binary:      raw JPEG bytes sent as WebSocket binary message

The handler NEVER blocks the event loop:
- Frame decoding is done inline (fast, <1 ms on typical ESP32 frames)
- FrameQueue.put() uses put_nowait — drops oldest frame if full, never blocks
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Dict

import cv2
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from backend.core.frame_queue import FrameQueue

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages all concurrent ESP32 WebSocket connections.

    One instance is created at app startup and shared across all endpoints.
    Thread-safe for reads; dict mutations happen only in the async event loop.
    """

    def __init__(self, frame_queue: FrameQueue) -> None:
        self._active: Dict[str, WebSocket] = {}
        self._frame_queue = frame_queue

    # ── public API ────────────────────────────────────────────────────────────

    async def handle(self, camera_id: str, websocket: WebSocket) -> None:
        """
        Accept a connection, receive frames until disconnect, clean up.
        This coroutine is the body of the /ws/{camera_id} endpoint.
        """
        await self._connect(camera_id, websocket)
        try:
            await self._receive_loop(camera_id, websocket)
        except WebSocketDisconnect:
            logger.info("Camera '%s' disconnected normally.", camera_id)
        except Exception as exc:
            logger.error("Camera '%s' error: %s", camera_id, exc, exc_info=True)
        finally:
            self._disconnect(camera_id)

    @property
    def active_count(self) -> int:
        return len(self._active)

    # ── internals ─────────────────────────────────────────────────────────────

    async def _connect(self, camera_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._active[camera_id] = websocket
        logger.info("Camera connected: '%s'  (total=%d)", camera_id, self.active_count)
        # Acknowledge connection
        await websocket.send_json({"status": "connected", "camera_id": camera_id})

    def _disconnect(self, camera_id: str) -> None:
        self._active.pop(camera_id, None)
        logger.info("Camera removed: '%s'  (total=%d)", camera_id, self.active_count)

    async def _receive_loop(self, camera_id: str, websocket: WebSocket) -> None:
        """
        Continuously receive messages from one camera and push decoded frames
        to the shared FrameQueue.

        Handles both text (base64/JSON) and binary (raw JPEG) messages.
        """
        frames_received = 0
        frames_dropped  = 0

        async for message in websocket.iter_bytes():
            # Binary path: raw JPEG bytes
            frame = _decode_binary_frame(message)
            if frame is not None:
                dropped = self._frame_queue.put(frame)
                if dropped:
                    frames_dropped += 1
                frames_received += 1
                if frames_received % 100 == 0:
                    logger.debug(
                        "Camera '%s': %d frames received, %d dropped",
                        camera_id, frames_received, frames_dropped,
                    )

    async def _receive_text_loop(self, camera_id: str, websocket: WebSocket) -> None:
        """
        Text-mode receive loop — for ESP32 firmware that sends JSON or plain base64.
        Switch to this in the endpoint if the ESP32 is configured for text mode.
        """
        async for message in websocket.iter_text():
            frame = _decode_text_frame(message)
            if frame is not None:
                self._frame_queue.put(frame)

    async def broadcast_result(self, result: dict) -> None:
        """Push an inference result back to ALL connected cameras (optional)."""
        dead = []
        for cam_id, ws in self._active.items():
            try:
                await ws.send_json(result)
            except Exception:
                dead.append(cam_id)
        for cam_id in dead:
            self._disconnect(cam_id)


# ── frame decoders ────────────────────────────────────────────────────────────

def _decode_binary_frame(data: bytes) -> np.ndarray | None:
    """Decode raw JPEG bytes → BGR numpy array."""
    try:
        buf   = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("cv2.imdecode returned None (not a valid JPEG?)")
        return frame
    except Exception as exc:
        logger.warning("Binary frame decode failed: %s", exc)
        return None


def _decode_text_frame(raw: str) -> np.ndarray | None:
    """
    Decode a text message that is either:
      - plain base64 string
      - data-URI:  data:image/jpeg;base64,<data>
      - JSON:      { "frame": "<base64>", ... }
    """
    try:
        # JSON envelope
        if raw.lstrip().startswith("{"):
            payload = json.loads(raw)
            raw = payload.get("frame", "")

        # Strip optional data-URI prefix
        if "," in raw:
            raw = raw.split(",", 1)[1]

        jpg_bytes = base64.b64decode(raw)
        return _decode_binary_frame(jpg_bytes)
    except Exception as exc:
        logger.warning("Text frame decode failed: %s", exc)
        return None