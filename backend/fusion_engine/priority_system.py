"""
fusion_engine/priority_system.py
=================================
Priority constants for the OptiVision fusion pipeline.

Priority ladder (1 = highest urgency, 5 = lowest):
  1  CRITICAL      — Imminent collision / obstacle confirmed by depth
  2  HIGH          — Known face recognised, or very close object
  3  MEDIUM        — Objects detected at moderate distance
  4  LOW           — OCR text found, or unknown faces present
  5  INFORMATIONAL — No actionable scene content

These values flow from DecisionEngine → AudioPriorityQueue.
The audio queue uses them as heap keys (lower = dequeued first).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Priority(IntEnum):
    CRITICAL      = 1
    HIGH          = 2
    MEDIUM        = 3
    LOW           = 4
    INFORMATIONAL = 5


@dataclass(frozen=True)
class PriorityScore:
    """Immutable descriptor for one priority level."""
    level:       Priority
    score:       int    # 1–5, equals level.value
    is_critical: bool   # True only for score == 1 (triggers audio interrupt)


# ── Scoring table ─────────────────────────────────────────────────────────────
# Maps a semantic event type → PriorityScore used by DecisionEngine.

PRIORITY_TABLE: dict[str, PriorityScore] = {
    # Score 1 — CRITICAL (always interrupts current TTS playback)
    "collision_imminent": PriorityScore(Priority.CRITICAL, 1, True),
    "obstacle_very_close": PriorityScore(Priority.CRITICAL, 1, True),

    # Score 2 — HIGH
    "face_known":         PriorityScore(Priority.HIGH, 2, False),
    "obstacle_close":     PriorityScore(Priority.HIGH, 2, False),

    # Score 3 — MEDIUM
    "object_detected":    PriorityScore(Priority.MEDIUM, 3, False),
    "obstacle_medium":    PriorityScore(Priority.MEDIUM, 3, False),

    # Score 4 — LOW
    "text_found":         PriorityScore(Priority.LOW, 4, False),
    "face_unknown":       PriorityScore(Priority.LOW, 4, False),

    # Score 5 — INFORMATIONAL
    "generic":            PriorityScore(Priority.INFORMATIONAL, 5, False),
    "empty_scene":        PriorityScore(Priority.INFORMATIONAL, 5, False),
}


def get_priority(event_type: str) -> PriorityScore:
    """
    Look up a PriorityScore by event type.
    Falls back to INFORMATIONAL for unknown types.
    """
    return PRIORITY_TABLE.get(event_type, PRIORITY_TABLE["generic"])


def is_critical(score: int) -> bool:
    return score == Priority.CRITICAL