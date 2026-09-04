from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any, Dict, Iterable
import json


TIMELINE_SCHEMA_VERSION = "1.0"
TIMELINE_FPS = 30
AUDIO_SAMPLE_RATE = 48_000
SUPPORTED_TRACK_KINDS = {"video", "audio"}
SUPPORTED_CLIP_KINDS = {"video", "audio"}
ALLOWED_CANVASES = {(1080, 1920), (1080, 1080), (1920, 1080)}
ALLOWED_TRANSITIONS = {"crossfade"}


def frames_from_seconds(value: float) -> int:
    return max(0, int(round(float(value) * TIMELINE_FPS)))


def us_from_seconds(value: float) -> int:
    return max(0, int(round(float(value) * 1_000_000)))


def samples_from_frames(frames: int) -> int:
    return int(round(int(frames) * AUDIO_SAMPLE_RATE / TIMELINE_FPS))


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(timeline: Dict[str, Any]) -> str:
    payload = deepcopy(timeline)
    payload.pop("timeline_hash", None)
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def refresh_hash(timeline: Dict[str, Any]) -> Dict[str, Any]:
    timeline["timeline_hash"] = canonical_hash(timeline)
    return timeline


def asset_from_raw(raw: Dict[str, Any], *, analyzed: bool = True,
                   permission_scope: str = "project_private") -> Dict[str, Any]:
    metadata = raw.get("metadata") or {}
    return {
        "asset_id": raw["file_id"],
        "kind": "video",
        "original_name": raw.get("original_name") or raw["file_id"],
        "stored_path": raw["stored_path"],
        "sha256": raw.get("sha256"),
        "duration_us": us_from_seconds(metadata.get("duration_seconds") or 0),
        "has_audio": bool(metadata.get("has_audio", True)),
        "width": metadata.get("width"),
        "height": metadata.get("height"),
        "rotation": int(metadata.get("rotation") or 0),
        "analyzed": bool(analyzed),
        "analysis_status": raw.get("analysis_status", "complete" if analyzed else "not_requested"),
        "permission_scope": permission_scope,
        "media_metadata": deepcopy(metadata),
    }


def empty_timeline(project_id: str, assets: Iterable[Dict[str, Any]], *,
                   canvas: Dict[str, Any] | None = None) -> Dict[str, Any]:
    timeline = {
        "schema_version": TIMELINE_SCHEMA_VERSION,
        "project_id": project_id,
        "revision": 0,
        "fps": TIMELINE_FPS,
        "audio_sample_rate": AUDIO_SAMPLE_RATE,
        "canvas": canvas or {"width": 1080, "height": 1920, "background": "#000000"},
        "assets": list(deepcopy(list(assets))),
        "tracks": [
            {"track_id": "video-main", "kind": "video", "role": "main", "order": 0, "muted": False, "clips": []},
            {"track_id": "video-overlay", "kind": "video", "role": "overlay", "order": 1, "muted": False, "clips": []},
            {"track_id": "audio-original", "kind": "audio", "role": "original", "order": 0, "muted": False, "clips": []},
        ],
        "transitions": [],
        "metadata": {"origin": "empty", "initial_timeline_hash": None},
    }
    return refresh_hash(timeline)


def main_video_duration_frames(timeline: Dict[str, Any]) -> int:
    """Return the authoritative program duration from the primary video track."""
    main = next((track for track in timeline.get("tracks", [])
                 if track.get("kind") == "video" and track.get("role") == "main"), None)
    if not main:
        return 0
    return max((int(clip.get("timeline_start_frame", 0)) + int(clip.get("duration_frames", 0))
                for clip in main.get("clips", [])), default=0)
