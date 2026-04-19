"""
WorkerPool — pulls frames from FrameQueue and dispatches them to InferenceService.

Each worker runs in its own daemon thread so it does not block the asyncio
event loop. Inference errors are caught per-frame; the worker never crashes.
"""

import logging
import threading
from typing import Callable, Optional

import numpy as np

from backend.core.frame_queue import FrameQueue

logger = logging.getLogger(__name__)

# Type alias for any callable that accepts a numpy frame and returns a result
InferenceCallable = Callable[[np.ndarray], dict]


class WorkerPool:
    """
    Pool of background threads that continuously drain *frame_queue* and
    call *inference_fn* on each frame.

    Args:
        frame_queue:  Shared FrameQueue instance.
        inference_fn: Callable matching ``inference_service.process_frame``.
        n_workers:    Number of parallel inference threads.
        on_result:    Optional callback invoked with (result_dict) after each frame.
    """

    def __init__(
        self,
        frame_queue: FrameQueue,
        inference_fn: InferenceCallable,
        n_workers: int = 2,
        on_result: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._queue = frame_queue
        self._inference_fn = inference_fn
        self._n_workers = n_workers
        self._on_result = on_result or _default_result_handler

        self._workers: list[threading.Thread] = []
        self._stop_event = threading.Event()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn all worker threads."""
        self._stop_event.clear()
        for i in range(self._n_workers):
            t = threading.Thread(
                target=self._worker_loop,
                args=(i,),
                name=f"optivision-worker-{i}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)
        logger.info("WorkerPool started with %d worker(s)", self._n_workers)

    def stop(self, join_timeout: float = 5.0) -> None:
        """Signal all workers to stop and wait for them to finish."""
        self._stop_event.set()
        self._queue.send_stop_signal(self._n_workers)
        for t in self._workers:
            t.join(timeout=join_timeout)
        self._workers.clear()
        logger.info("WorkerPool stopped")

    # ── internal ──────────────────────────────────────────────────────────────

    def _worker_loop(self, worker_id: int) -> None:
        logger.debug("Worker %d started", worker_id)
        while not self._stop_event.is_set():
            item = self._queue.get(timeout=1.0)

            if item is None:
                # Timed out — check stop flag and retry
                continue

            if FrameQueue.is_stop_signal(item):
                logger.debug("Worker %d received stop signal", worker_id)
                break

            frame: np.ndarray = item
            try:
                result = self._inference_fn(frame)
                self._on_result(result)
            except Exception as exc:
                logger.error("Worker %d inference error: %s", worker_id, exc, exc_info=True)
            finally:
                self._queue.task_done()

        logger.debug("Worker %d exiting", worker_id)


# ── default result handler ────────────────────────────────────────────────────

def _default_result_handler(result: dict) -> None:
    """Fallback: just log the result. Replace with WebSocket send / TTS / etc."""
    logger.info("Inference result: %s", result)