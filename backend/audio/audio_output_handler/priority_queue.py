"""
audio/audio_output_handler/priority_queue.py
=============================================
Thread-safe TTS priority queue with:

  - heapq-based ordering (lower priority_score = dequeued first)
  - 3-second per-type cooldown suppression
  - 5-frame persistence deduplication (delegates counter to StateManager)
  - CRITICAL alerts (score=1) bypass cooldown AND interrupt current playback
  - Background worker thread handles TTS synthesis + playback

Call start() at app startup and stop() at shutdown.
Enqueue decisions from the on_result callback in WorkerPool.
"""

from __future__ import annotations

import heapq
import logging
import threading
import time
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)

# Per-type cooldown — identical alert types won't speak again for this long
COOLDOWN_SECS = 3.0

# Suppress an alert that has appeared in N or more consecutive frames
PERSISTENCE_THRESHOLD = 5

# Maximum items held in the heap (oldest low-priority items dropped when full)
_MAX_HEAP_SIZE = 20


class AlertItem:
    """
    Heap entry.  Ordered by (priority_score, sequence_number) so that:
      - lower score = higher urgency = dequeued first
      - ties broken by insertion order (FIFO within same priority)
    """
    __slots__ = ("score", "seq", "text", "alert_type", "is_critical")

    def __init__(
        self,
        score:      int,
        seq:        int,
        text:       str,
        alert_type: str,
        is_critical: bool,
    ) -> None:
        self.score       = score
        self.seq         = seq
        self.text        = text
        self.alert_type  = alert_type
        self.is_critical = is_critical

    def __lt__(self, other: "AlertItem") -> bool:
        if self.score != other.score:
            return self.score < other.score
        return self.seq < other.seq


class AudioPriorityQueue:
    """
    Manages the audio output pipeline:

      enqueue() → decide suppress/pass → heap → worker thread → TTS

    Parameters
    ----------
    tts_engine :
        Any object with a .speak(text, interrupt_event) method.
        Blocks until the utterance finishes or the event is set.
    state_manager :
        Optional StateManager for external persistence tracking.
        If None, the queue maintains its own internal counter.
    cooldown_secs :
        Per-type minimum interval between repeated announcements.
    persistence_threshold :
        Suppress after this many consecutive identical frames.
    """

    def __init__(
        self,
        tts_engine,
        state_manager=None,
        cooldown_secs:          float = COOLDOWN_SECS,
        persistence_threshold:  int   = PERSISTENCE_THRESHOLD,
        max_size:               int   = _MAX_HEAP_SIZE,
    ) -> None:
        self._tts          = tts_engine
        self._state_mgr    = state_manager
        self._cooldown     = cooldown_secs
        self._threshold    = persistence_threshold
        self._max_size     = max_size

        self._heap:     list[AlertItem] = []
        self._seq:      int             = 0
        self._lock      = threading.Lock()

        # Per-type last-spoken timestamp for cooldown enforcement
        self._cooldown_map: dict[str, float] = {}

        # Internal per-type frame counter (used when state_manager is None)
        self._persist_counts: Counter = Counter()

        # Event set by enqueue() when a CRITICAL alert arrives —
        # the TTS worker checks this between synthesis chunks and stops early
        self._interrupt_event = threading.Event()

        self._stop_event   = threading.Event()
        self._worker:       Optional[threading.Thread] = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background TTS worker. Call once at app startup."""
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._tts_loop,
            name="audio-worker",
            daemon=True,
        )
        self._worker.start()
        logger.info("AudioPriorityQueue started.")

    def stop(self, timeout: float = 4.0) -> None:
        """Signal the worker to stop and wait for it to exit."""
        self._stop_event.set()
        self._interrupt_event.set()   # unblock any in-progress TTS
        if self._worker:
            self._worker.join(timeout=timeout)
        logger.info("AudioPriorityQueue stopped.")

    # ── public API ────────────────────────────────────────────────────────────

    def enqueue(self, decision: dict) -> None:
        """
        Submit a Decision dict from DecisionEngine for possible TTS output.

        Suppression rules (checked in order):
          1. CRITICAL (score=1) → always enqueue + interrupt current playback
          2. Persistence threshold → suppress if same type appeared N+ frames
          3. Cooldown window → suppress if same type spoken < cooldown_secs ago
          4. Queue full → drop the lowest-priority item to make room
        """
        score       = decision.get("priority_score", 5)
        alert_type  = decision.get("alert_type",     "generic")
        alert_text  = decision.get("alert_text",     "")
        critical    = decision.get("is_critical",    False)

        if not alert_text.strip():
            return

        now = time.monotonic()

        # ── Rule 1: CRITICAL bypasses everything ─────────────────────────────
        if critical or score == 1:
            self._interrupt_event.set()   # signal worker to stop current TTS
            self._enqueue_item(score, alert_text, alert_type, is_critical=True)
            with self._lock:
                self._cooldown_map[alert_type]    = now
                self._persist_counts[alert_type]  = 0
            logger.warning("CRITICAL alert enqueued: '%s'", alert_text)
            return

        # ── Rule 2: Persistence deduplication ────────────────────────────────
        persistent = self._check_persistence(alert_type)
        if persistent:
            logger.debug("Suppressed (persistent %d+ frames): '%s'", self._threshold, alert_type)
            return

        # ── Rule 3: Cooldown suppression ──────────────────────────────────────
        with self._lock:
            last_spoken = self._cooldown_map.get(alert_type, 0.0)

        if now - last_spoken < self._cooldown:
            remaining = self._cooldown - (now - last_spoken)
            logger.debug(
                "Suppressed (cooldown %.1fs remaining): '%s'", remaining, alert_type
            )
            return

        # ── Rule 4: Enqueue (drop lowest-priority if full) ───────────────────
        self._enqueue_item(score, alert_text, alert_type, is_critical=False)

    def reset_persistence(self, alert_type: str) -> None:
        """
        Allow an alert_type to be re-announced.
        Call when the scene changes (e.g. the person leaves the frame).
        """
        with self._lock:
            self._persist_counts[alert_type] = 0
        if self._state_mgr:
            self._state_mgr.reset(alert_type)

    @property
    def qsize(self) -> int:
        with self._lock:
            return len(self._heap)

    # ── internals ─────────────────────────────────────────────────────────────

    def _check_persistence(self, alert_type: str) -> bool:
        """
        Increment and check the persistence counter for alert_type.
        Uses StateManager if available; otherwise uses _persist_counts.
        """
        if self._state_mgr is not None:
            return self._state_mgr.update(alert_type)

        with self._lock:
            self._persist_counts[alert_type] += 1
            return self._persist_counts[alert_type] > self._threshold

    def _enqueue_item(
        self,
        score:       int,
        text:        str,
        alert_type:  str,
        is_critical: bool,
    ) -> None:
        with self._lock:
            # Drop lowest-priority item if heap is full
            if len(self._heap) >= self._max_size:
                # Heap is a min-heap (lowest score = highest priority).
                # To drop the LOWEST priority (highest score), we need to find it.
                # We track it by temporarily converting to a max operation.
                worst_idx = max(range(len(self._heap)), key=lambda i: self._heap[i].score)
                if self._heap[worst_idx].score <= score:
                    # New item is even lower priority than the worst — drop it
                    logger.debug("Queue full: dropping new low-priority item '%s'", text)
                    return
                self._heap.pop(worst_idx)
                heapq.heapify(self._heap)
                logger.debug("Queue full: evicted lowest-priority item to make room")

            self._seq += 1
            item = AlertItem(score, self._seq, text, alert_type, is_critical)
            heapq.heappush(self._heap, item)

    def _dequeue(self) -> Optional[AlertItem]:
        with self._lock:
            return heapq.heappop(self._heap) if self._heap else None

    def _tts_loop(self) -> None:
        """
        Background thread: drains the heap and calls TTS.
        Checks _interrupt_event between chunks so CRITICAL alerts
        can preempt a running utterance within ~50 ms.
        """
        logger.debug("Audio worker started.")
        while not self._stop_event.is_set():
            item = self._dequeue()
            if item is None:
                time.sleep(0.05)   # nothing queued — idle poll
                continue

            self._interrupt_event.clear()
            logger.info(
                "TTS [score=%d] '%s'  type=%s  critical=%s",
                item.score, item.text, item.alert_type, item.is_critical,
            )

            try:
                self._tts.speak(item.text, interrupt_event=self._interrupt_event)
                # Record cooldown timestamp only after successful speech
                with self._lock:
                    self._cooldown_map[item.alert_type] = time.monotonic()
                    # Reset persistence so the same scene CAN be re-announced
                    # after a successful utterance
                    self._persist_counts[item.alert_type] = 0
                if self._state_mgr:
                    self._state_mgr.reset(item.alert_type)

            except Exception as exc:
                logger.error("TTS playback error: %s", exc, exc_info=True)

        logger.debug("Audio worker exited.")