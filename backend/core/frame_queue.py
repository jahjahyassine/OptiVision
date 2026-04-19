"""
FrameQueue — thread-safe buffer between the WebSocket receiver and the worker pool.

Designed for use across threads (asyncio + thread-pool workers).
Drops the oldest frame when the queue is full to avoid memory build-up
during inference slowdowns (back-pressure strategy).
"""

import logging
import queue
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_SENTINEL = object()  # signals worker shutdown


class FrameQueue:
    """
    Thread-safe, bounded FIFO queue of OpenCV frames.

    Args:
        maxsize: Maximum number of frames held before the oldest is dropped.
                 Set to 0 for an unbounded queue (not recommended in production).
    """

    def __init__(self, maxsize: int = 30) -> None:
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=maxsize)

    # ── public API ────────────────────────────────────────────────────────────

    def put(self, frame: np.ndarray) -> None:
        """
        Add a frame. If the queue is full, discard the oldest frame first
        so we always have the most recent data.
        """
        if self._q.full():
            try:
                self._q.get_nowait()
                logger.debug("FrameQueue full — oldest frame dropped")
            except queue.Empty:
                pass
        try:
            self._q.put_nowait(frame)
        except queue.Full:
            logger.warning("FrameQueue put failed — frame discarded")

    def get(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        """
        Block until a frame is available or *timeout* seconds elapse.
        Returns None on timeout so the caller can loop safely.
        """
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def task_done(self) -> None:
        """Signal that a previously retrieved frame has been processed."""
        self._q.task_done()

    def empty(self) -> bool:
        return self._q.empty()

    def qsize(self) -> int:
        return self._q.qsize()

    # ── shutdown signalling ───────────────────────────────────────────────────

    def send_stop_signal(self, n_workers: int = 1) -> None:
        """Enqueue *n_workers* sentinel values to gracefully stop workers."""
        for _ in range(n_workers):
            self._q.put(_SENTINEL)

    @staticmethod
    def is_stop_signal(item: object) -> bool:
        return item is _SENTINEL