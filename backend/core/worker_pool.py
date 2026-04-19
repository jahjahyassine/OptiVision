"""
core/worker_pool.py
===================
Thread-based worker pool that continuously drains FrameQueue and dispatches
frames to InferenceService.

Why threads (not asyncio coroutines)?
  InferenceService calls heavy CPU/GPU-bound AI libraries (InsightFace, YOLOv8,
  EasyOCR, MiDaS). These release the GIL during native C/CUDA calls, so threads
  give genuine parallelism without the complexity of running blocking code in
  asyncio executors.

Architecture
  ┌──────────────┐    put()   ┌────────────────┐
  │ WebSocket    │──────────►│  FrameQueue    │
  │ (async)      │           │  (thread-safe) │
  └──────────────┘           └───────┬────────┘
                                     │ get()
                            ┌────────▼────────┐
                            │  WorkerPool     │  N daemon threads
                            │  Thread 0 ──────►  inference_fn(frame)
                            │  Thread 1 ──────►  inference_fn(frame)
                            │  ...            │
                            └────────┬────────┘
                                     │ result dict
                            ┌────────▼────────┐
                            │  on_result()    │  DecisionEngine + TTS
                            └─────────────────┘
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import numpy as np

from backend.core.frame_queue import FrameQueue

logger = logging.getLogger(__name__)

InferenceFn    = Callable[[np.ndarray], dict]
ResultCallback = Callable[[dict], None]


class WorkerPool:
    """
    Pool of N background daemon threads that drain FrameQueue and run inference.

    Parameters
    ----------
    frame_queue:
        Shared FrameQueue instance (also used for stop-signal injection).
    inference_fn:
        Callable matching InferenceService.process_frame — must be thread-safe.
    n_workers:
        Number of parallel worker threads. Recommended: 1–2 on GPU, 1 on CPU.
    on_result:
        Called with the inference result dict after each frame. Runs in the
        worker thread — keep it fast (no blocking I/O). Default: just logs.
    """

    def __init__(
        self,
        frame_queue:  FrameQueue,
        inference_fn: InferenceFn,
        n_workers:    int = 2,
        on_result:    Optional[ResultCallback] = None,
    ) -> None:
        self._queue      = frame_queue
        self._infer      = inference_fn
        self._n_workers  = n_workers
        self._on_result  = on_result or _default_result_handler
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn all worker threads. Call once at app startup."""
        if self._threads:
            logger.warning("WorkerPool.start() called while already running — ignored.")
            return
        self._stop_event.clear()
        for i in range(self._n_workers):
            t = threading.Thread(
                target=self._worker_loop,
                args=(i,),
                name=f"optivision-worker-{i}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)
        logger.info("WorkerPool started: %d worker thread(s)", self._n_workers)

    def stop(self, join_timeout: float = 5.0) -> None:
        """
        Signal all workers to stop and wait for them to exit.
        Safe to call multiple times.
        """
        if not self._threads:
            return
        logger.info("WorkerPool stopping …")
        self._stop_event.set()
        # Inject sentinels to unblock any threads waiting inside queue.get()
        self._queue.send_stop_signal(len(self._threads))
        for t in self._threads:
            t.join(timeout=join_timeout)
            if t.is_alive():
                logger.warning("Worker thread '%s' did not exit within %.1fs",
                               t.name, join_timeout)
        self._threads.clear()
        logger.info("WorkerPool stopped.")

    @property
    def is_running(self) -> bool:
        return bool(self._threads) and not self._stop_event.is_set()

    # ── worker loop ───────────────────────────────────────────────────────────

    def _worker_loop(self, worker_id: int) -> None:
        logger.debug("Worker %d started", worker_id)
        consecutive_errors = 0

        while not self._stop_event.is_set():
            item = self._queue.get(timeout=1.0)

            if item is None:
                # Timeout — re-check stop flag
                continue

            if FrameQueue.is_stop_signal(item):
                logger.debug("Worker %d received stop signal", worker_id)
                break

            frame: np.ndarray = item  # type: ignore[assignment]
            try:
                result = self._infer(frame)
                self._on_result(result)
                consecutive_errors = 0
            except Exception as exc:
                consecutive_errors += 1
                logger.error(
                    "Worker %d inference error (consecutive=%d): %s",
                    worker_id, consecutive_errors, exc, exc_info=True,
                )
                # If the module keeps crashing, back off briefly
                if consecutive_errors >= 5:
                    logger.warning("Worker %d: %d consecutive errors — pausing 2s",
                                   worker_id, consecutive_errors)
                    import time; time.sleep(2.0)
                    consecutive_errors = 0
            finally:
                self._queue.task_done()

        logger.debug("Worker %d exited", worker_id)


# ── default result handler ────────────────────────────────────────────────────

def _default_result_handler(result: dict) -> None:
    """Fallback handler: just log the result summary."""
    faces   = len(result.get("faces",   []))
    objects = len(result.get("objects", []))
    ocr     = len(result.get("ocr",     []))
    logger.info(
        "Inference done — faces=%d  objects=%d  ocr_items=%d  ts=%.3f",
        faces, objects, ocr, result.get("timestamp", 0),
    )