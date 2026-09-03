"""Environment-specific FFmpeg resource controls."""

from __future__ import annotations

import os
from typing import List


def low_memory_mode() -> bool:
    """Return whether FFmpeg should bound parallel work for hosted renders."""
    enabled = {"1", "true", "yes", "on"}
    return (
        os.getenv("PBJ_HOSTED_MODE", "").strip().lower() in enabled
        or os.getenv("PBJ_LOW_MEMORY_MODE", "").strip().lower() in enabled
    )


def global_options() -> List[str]:
    if not low_memory_mode():
        return []
    return ["-filter_threads", "1", "-filter_complex_threads", "1"]


def input_options() -> List[str]:
    """Bound per-input probing buffers when one timeline opens many clips."""
    if not low_memory_mode():
        return []
    return ["-threads", "1", "-probesize", "1M", "-analyzeduration", "2M"]


def video_encoder_options() -> List[str]:
    if not low_memory_mode():
        return ["-preset", "medium"]
    return [
        # Preserve the normal quality/size profile while preventing FFmpeg from
        # decoding, filtering, and encoding many phone clips in parallel.
        "-preset", "medium", "-threads", "1",
        "-x264-params", "threads=1:lookahead_threads=1:sync-lookahead=0",
    ]
