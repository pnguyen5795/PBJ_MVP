"""PB&J's canonical editable-timeline domain.

The timeline is the single editorial source of truth. AI and manual changes use
the same typed operations; FFmpeg only compiles an immutable export snapshot.
"""

from .contracts import AUDIO_SAMPLE_RATE, TIMELINE_FPS, canonical_hash, empty_timeline
from .storage import StaleTimelineError, TimelineStore
from .validation import TimelineValidationError, validate_timeline

__all__ = [
    "AUDIO_SAMPLE_RATE", "TIMELINE_FPS", "StaleTimelineError", "TimelineStore",
    "TimelineValidationError", "canonical_hash", "empty_timeline", "validate_timeline",
]
