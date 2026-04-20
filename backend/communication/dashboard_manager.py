"""
communication/dashboard_manager.py
==================================
Manages browser dashboard WebSocket connections for real-time monitoring.

One instance is created at app startup and shared across all endpoints.
Broadcasts inference results, decisions, and system stats to all connected
browsers in real-time.

Thread-safe for async websocket operations.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class DashboardManager:
    """
    Manages concurrent dashboard browser connections.

    Responsibilities:
    - Accept WebSocket connections from a browser dashboard
    - Broadcast inference results and decisions to all connected clients
    - Handle graceful disconnection

    One instance created at app startup; shared across all /ws/dashboard endpoints.
    """

    def __init__(self) -> None:
        self._clients: Dict[str, WebSocket] = {}
        self._client_counter = 0

    # ── public API ────────────────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket) -> str:
        """
        Accept a new dashboard connection.

        Returns
        -------
        str
            A unique client ID for this connection.
        """
        await websocket.accept()
        client_id = f"dashboard-{self._client_counter}"
        self._client_counter += 1
        self._clients[client_id] = websocket
        logger.info(
            "Dashboard client connected: '%s'  (total=%d)",
            client_id, len(self._clients)
        )
        # Send welcome message
        await websocket.send_json({
            "type":    "system",
            "message": "Connected to OptiVision dashboard",
            "client_id": client_id,
        })
        return client_id

    async def disconnect(self, client_id: str) -> None:
        """Remove a dashboard client."""
        self._clients.pop(client_id, None)
        logger.info("Dashboard client disconnected: '%s'  (total=%d)",
                   client_id, len(self._clients))

    async def broadcast_inference(self, result: dict) -> None:
        """
        Broadcast an inference result to all connected dashboards.

        Called with InferenceResult.to_dict() from the worker pool.
        """
        message = {
            "type":   "inference",
            "data":   result,
        }
        await self._broadcast(message)

    async def broadcast_decision(self, decision: dict) -> None:
        """
        Broadcast a decision (from DecisionEngine) to all connected dashboards.
        """
        message = {
            "type":   "decision",
            "data":   decision,
        }
        await self._broadcast(message)

    async def broadcast_stats(self, stats: dict) -> None:
        """
        Broadcast system statistics (queue size, frames processed, etc.)
        to all connected dashboards.
        """
        message = {
            "type":   "stats",
            "data":   stats,
        }
        await self._broadcast(message)

    @property
    def client_count(self) -> int:
        """Return number of active dashboard connections."""
        return len(self._clients)

    # ── internals ─────────────────────────────────────────────────────────────

    async def _broadcast(self, message: dict) -> None:
        """
        Send a message to all connected clients.
        Remove clients that have disconnected (dead connections).
        """
        dead = []
        for client_id, websocket in list(self._clients.items()):
            try:
                await websocket.send_json(message)
            except Exception as exc:
                logger.warning(
                    "Failed to send to dashboard client '%s': %s",
                    client_id, exc
                )
                dead.append(client_id)

        for client_id in dead:
            await self.disconnect(client_id)

    async def handle(self, websocket: WebSocket) -> None:
        """
        Main handler for a dashboard WebSocket connection.

        Clients send keep-alive messages; we respond with pings.
        Results are pushed to the client via broadcast_*.
        """
        client_id = await self.connect(websocket)
        try:
            # Keep the connection alive and listen for client messages
            # (clients typically just send periodic pings)
            async for message in websocket.iter_text():
                # Simple echo/heartbeat for now
                if message.strip():
                    logger.debug("Dashboard message from '%s': %s", client_id, message[:50])
        except WebSocketDisconnect:
            logger.info("Dashboard client '%s' disconnected normally.", client_id)
        except Exception as exc:
            logger.error("Dashboard client '%s' error: %s", client_id, exc, exc_info=True)
        finally:
            await self.disconnect(client_id)
