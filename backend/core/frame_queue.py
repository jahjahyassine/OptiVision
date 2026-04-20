"""
core/frame_queue.py
===================
Thread-safe, bounded FIFO queue of OpenCV frames.

Design choices:
- Uses stdlib queue.Queue (GIL-safe, no asyncio dependency).
- When full: drops the OLDEST frame to make room for the newest (back-pressure
  strategy — real-time systems prefer fresh data over completeness).
- Returns (dropped: bool) from put() so callers can track drop rate.
- Exposes a stats dict for /health endpoint monitoring.
- Shutdown sentinels let WorkerPool signal threads to exit gracefully.
- Counter operations protected by mutex for thread safety.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_SENTINEL = object()  # unique object used as stop signal


class FrameQueue:
    """
    Thread-safe bounded frame buffer.

    Parameters
    ----------
    maxsize:
        Maximum frames held before the oldest is dropped.
        0 = unbounded (not recommended in production).
    """

    def __init__(self, maxsize: int = 30) -> None:
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()  # Protect counter operations
        self._total_received  = 0
        self._total_dropped   = 0
        self._total_processed = 0

    # ── write ─────────────────────────────────────────────────────────────────

    def put(self, frame: np.ndarray) -> bool:
        """
        Enqueue a frame. Drops the oldest entry if the queue is full.

        Returns
        -------
        bool
            True  — an old frame was dropped to make room.
            False — frame was enqueued without dropping anything.
        """
        with self._lock:
            self._total_received += 1
        dropped = False

        if self._q.full():
            try:
                self._q.get_nowait()  # discard oldest
                with self._lock:
                    self._total_dropped += 1
                dropped = True
                logger.debug("FrameQueue full — oldest frame discarded (drop #%d)",
                             self._total_dropped)
            except queue.Empty:
                pass  # race: another thread consumed it first — that's fine

        try:
            self._q.put_nowait(frame)
        except queue.Full:
            # Extremely rare race condition; log and move on
            logger.warning("FrameQueue put_nowait failed despite drop — frame lost")
            with self._lock:
                self._total_dropped += 1
            dropped = True

        return dropped

    # ── read ──────────────────────────────────────────────────────────────────

    def get(self, timeout: float = 1.0) -> Optional[object]:
        """
        Block until a frame (or stop sentinel) is available.

        Returns None on timeout, so callers can safely re-check a stop flag:

            while not stop_event.is_set():
                item = queue.get(timeout=1.0)
                if item is None:
                    continue
                if FrameQueue.is_stop_signal(item):
                    break
                process(item)
        """
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def task_done(self) -> None:
        """Signal that a retrieved frame has been fully processed."""
        try:
            self._q.task_done()
            with self._lock:
                self._total_processed += 1
        except ValueError:
            pass  # called more times than items retrieved — ignore

    # ── introspection ─────────────────────────────────────────────────────────

    def qsize(self) -> int:
        return self._q.qsize()

    def empty(self) -> bool:
        return self._q.empty()

    def full(self) -> bool:
        return self._q.full()

    @property
    def stats(self) -> dict:
        with self._lock:
            received = self._total_received
            dropped = self._total_dropped
            processed = self._total_processed
        
        drop_rate = (
            round(dropped / received, 3)
            if received
            else 0.0
        )
        
        return {
            "size":            self._q.qsize(),
            "total_received":  received,
            "total_dropped":   dropped,
            "total_processed": processed,
            "drop_rate":       drop_rate,
        }

    # ── shutdown signalling ───────────────────────────────────────────────────

    def send_stop_signal(self, n_workers: int = 1) -> None:
        """Enqueue *n_workers* sentinels to wake and stop all worker threads."""
        for _ in range(n_workers):
            self._q.put(_SENTINEL)

    @staticmethod
    def is_stop_signal(item: object) -> bool:
        """Check whether an item retrieved from get() is a stop sentinel."""
        return item is _SENTINEL