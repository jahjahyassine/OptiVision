"""
fusion_engine/state_manager.py
================================
Multi-frame scene-persistence tracker for the OptiVision pipeline.

Responsibilities
----------------
- Count consecutive frames where the same scene label appears.
- Expose is_persistent() so AudioPriorityQueue can suppress repeated alerts
  after PERSISTENCE_THRESHOLD frames.
- Reset a label's counter when a new, different scene displaces it (allows
  re-announcement if the same hazard reappears after going away).
- Periodically clean up stale counters to prevent unbounded growth.

Thread safety
-------------
All public methods acquire self._lock.  StateManager is shared between
the DecisionEngine (which writes) and the AudioPriorityQueue (which reads).
Both live in worker threads, not the asyncio event loop.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter

logger = logging.getLogger(__name__)

# Suppress a repeated alert after this many consecutive identical frames
PERSISTENCE_THRESHOLD = 5

# Remove stale labels that haven't been seen in this many seconds
_STALE_WINDOW_S = 5.0


class StateManager:
    """
    Tracks how many consecutive frames each scene label has persisted.

    Usage
    -----
    state = StateManager()

    # In the decision callback:
    persistent = state.update(decision["alert_text"])
    if persistent:
        # scene has been the same for 5+ frames — audio queue will suppress

    # When a new scene appears, older labels auto-decay via _cleanup().
    """

    def __init__(
        self,
        persistence_threshold: int   = PERSISTENCE_THRESHOLD,
        stale_window_s:        float = _STALE_WINDOW_S,
    ) -> None:
        self._threshold   = persistence_threshold
        self._stale_win   = stale_window_s
        self._lock        = threading.Lock()
        self._counts:     Counter          = Counter()
        self._last_seen:  dict[str, float] = {}
        self._last_clean: float            = time.monotonic()

    # ── public API ────────────────────────────────────────────────────────────

    def update(self, label: str) -> bool:
        """
        Record that *label* appeared in the current frame.

        Returns
        -------
        bool
            True if *label* has now reached the persistence threshold
            (i.e. the audio queue should suppress this repeated alert).
        """
        now = time.monotonic()
        with self._lock:
            self._maybe_cleanup(now)
            self._counts[label]    += 1
            self._last_seen[label]  = now
            return self._counts[label] >= self._threshold

    def is_persistent(self, label: str) -> bool:
        """Return True if *label* has met or exceeded the threshold."""
        with self._lock:
            return self._counts[label] >= self._threshold

    def get_count(self, label: str) -> int:
        """Return the current consecutive frame count for *label*."""
        with self._lock:
            return self._counts[label]

    def reset(self, label: str) -> None:
        """
        Manually reset a label's counter.
        Call when the scene changes so the same label can be re-announced
        if it reappears later.
        """
        with self._lock:
            self._counts.pop(label, None)
            self._last_seen.pop(label, None)
        logger.debug("StateManager: reset persistence counter for '%s'", label)

    def reset_all(self) -> None:
        """Clear all counters — useful at app startup or after a long pause."""
        with self._lock:
            self._counts.clear()
            self._last_seen.clear()

    @property
    def active_labels(self) -> dict[str, int]:
        """Snapshot of {label: count} for all currently tracked labels."""
        with self._lock:
            return dict(self._counts)

    # ── internals ─────────────────────────────────────────────────────────────

    def _maybe_cleanup(self, now: float) -> None:
        """
        Remove labels that haven't been seen in _stale_win seconds.
        Called inside the lock; only runs every _stale_win seconds.
        """
        if now - self._last_clean < self._stale_win:
            return
        expired = [
            label
            for label, ts in self._last_seen.items()
            if now - ts >= self._stale_win
        ]
        for label in expired:
            del self._counts[label]
            del self._last_seen[label]
        if expired:
            logger.debug("StateManager: expired %d stale label(s)", len(expired))
        self._last_clean = now