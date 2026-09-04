from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .contracts import (
    ALLOWED_CANVASES, ALLOWED_TRANSITIONS, AUDIO_SAMPLE_RATE,
    SUPPORTED_CLIP_KINDS, SUPPORTED_TRACK_KINDS, TIMELINE_FPS, canonical_hash,
    samples_from_frames,
)


class TimelineValidationError(ValueError):
    def __init__(self, message: str, errors: Iterable[Dict[str, Any]] | None = None):
        super().__init__(message)
        self.errors = list(errors or [])


def validate_timeline(timeline: Dict[str, Any], *, for_export: bool = False) -> None:
    errors: List[Dict[str, Any]] = []
    if timeline.get("schema_version") != "1.0":
        errors.append({"code": "schema_version", "message": "Timeline schema version is unsupported"})
    if timeline.get("fps") != TIMELINE_FPS:
        errors.append({"code": "fps", "message": "Timeline must use 30 fps"})
    if timeline.get("audio_sample_rate") != AUDIO_SAMPLE_RATE:
        errors.append({"code": "sample_rate", "message": "Timeline must use 48 kHz audio"})
    canvas = timeline.get("canvas") or {}
    if (canvas.get("width"), canvas.get("height")) not in ALLOWED_CANVASES:
        errors.append({"code": "canvas", "message": "Timeline canvas is unsupported"})

    asset_map = {item.get("asset_id"): item for item in timeline.get("assets", [])}
    if len(asset_map) != len(timeline.get("assets", [])) or None in asset_map:
        errors.append({"code": "asset_ids", "message": "Asset IDs must be present and unique"})
    track_ids = set()
    clip_ids = set()
    linked = {}
    main_track = None
    for track in timeline.get("tracks", []):
        track_id = track.get("track_id")
        if not track_id or track_id in track_ids:
            errors.append({"code": "track_id", "message": "Track IDs must be present and unique"})
            continue
        track_ids.add(track_id)
        if track.get("kind") not in SUPPORTED_TRACK_KINDS:
            errors.append({"code": "track_kind", "track_id": track_id, "message": "Unsupported track kind"})
        if track.get("role") == "main" and track.get("kind") == "video":
            main_track = track
        intervals = []
        for clip in track.get("clips", []):
            clip_id = clip.get("clip_id")
            if not clip_id or clip_id in clip_ids:
                errors.append({"code": "clip_id", "track_id": track_id, "message": "Clip IDs must be present and unique"})
                continue
            clip_ids.add(clip_id)
            if clip.get("kind") not in SUPPORTED_CLIP_KINDS or clip.get("kind") != track.get("kind"):
                errors.append({"code": "clip_kind", "clip_id": clip_id, "message": "Clip kind must match its track"})
            asset = asset_map.get(clip.get("asset_id"))
            if not asset:
                errors.append({"code": "asset_missing", "clip_id": clip_id, "message": "Clip references an unknown asset"})
                continue
            source_in = clip.get("source_in_us")
            source_out = clip.get("source_out_us")
            start = clip.get("timeline_start_frame")
            duration = clip.get("duration_frames")
            if not all(isinstance(value, int) for value in (source_in, source_out, start, duration)):
                errors.append({"code": "integer_timing", "clip_id": clip_id, "message": "Timeline timing must use integers"})
                continue
            if source_in < 0 or source_out <= source_in or source_out > int(asset.get("duration_us") or 0):
                errors.append({"code": "source_range", "clip_id": clip_id, "message": "Clip source range is outside its asset"})
            if start < 0 or duration <= 0:
                errors.append({"code": "timeline_range", "clip_id": clip_id, "message": "Clip timeline range is invalid"})
            rate = float(clip.get("playback_rate", 1.0))
            expected = int(round((source_out - source_in) / 1_000_000 * TIMELINE_FPS / rate)) if rate > 0 else -1
            if rate <= 0 or abs(expected - duration) > 1:
                errors.append({"code": "duration_rate", "clip_id": clip_id, "message": "Source range, duration, and speed do not agree"})
            intervals.append((start, start + duration, clip_id))
            group = clip.get("linked_group_id")
            if group:
                linked.setdefault(group, []).append((track.get("kind"), clip))
            if clip.get("kind") == "audio":
                start_sample = clip.get("timeline_start_sample")
                duration_samples = clip.get("duration_samples")
                if start_sample != samples_from_frames(start) or duration_samples != samples_from_frames(duration):
                    errors.append({"code": "audio_samples", "clip_id": clip_id, "message": "Audio sample placement does not match frame placement"})
                volume = clip.get("volume", 1.0)
                fades = clip.get("fades") or {"in_frames": 0, "out_frames": 0}
                if not isinstance(volume, (int, float)) or isinstance(volume, bool) or not 0 <= float(volume) <= 2:
                    errors.append({"code": "audio_volume", "clip_id": clip_id, "message": "Audio volume must be between 0 and 2"})
                if any(not isinstance(fades.get(key), int) or fades[key] < 0 for key in ("in_frames", "out_frames")):
                    errors.append({"code": "audio_fade", "clip_id": clip_id, "message": "Audio fades must use non-negative frames"})
                elif fades["in_frames"] + fades["out_frames"] > duration:
                    errors.append({"code": "audio_fade", "clip_id": clip_id, "message": "Audio fades exceed the clip duration"})
            elif clip.get("kind") == "video":
                transform = clip.get("transform") or {}
                if transform.get("mode") not in {"fit", "fill"}:
                    errors.append({"code": "transform", "clip_id": clip_id, "message": "Video transform mode must be fit or fill"})
                for key in ("x", "y"):
                    value = transform.get(key)
                    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= float(value) <= 1:
                        errors.append({"code": "transform", "clip_id": clip_id, "message": "Video transform position is invalid"})
                scale = transform.get("scale")
                if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not 0.1 <= float(scale) <= 4:
                    errors.append({"code": "transform", "clip_id": clip_id, "message": "Video transform scale is invalid"})
                crop = transform.get("crop")
                if crop is not None:
                    if not isinstance(crop, dict):
                        errors.append({"code": "transform", "clip_id": clip_id, "message": "Video crop is invalid"})
                    else:
                        values = [crop.get(key) for key in ("x", "y", "width", "height")]
                        if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in values):
                            errors.append({"code": "transform", "clip_id": clip_id, "message": "Video crop coordinates are invalid"})
                        else:
                            x, y, width, height = (float(value) for value in values)
                            if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > 1.000001 or y + height > 1.000001:
                                errors.append({"code": "transform", "clip_id": clip_id, "message": "Video crop exceeds the source frame"})
                        if crop.get("preset", "freeform") not in {"freeform", "9:16", "16:9", "1:1", "3:4", "4:3"}:
                            errors.append({"code": "transform", "clip_id": clip_id, "message": "Video crop preset is unsupported"})
        intervals.sort()
        transition_pairs = {
            (item.get("from_clip_id"), item.get("to_clip_id")): int(item.get("duration_frames") or 0)
            for item in timeline.get("transitions", [])
        }
        for previous, current in zip(intervals, intervals[1:]):
            allowed_overlap = transition_pairs.get((previous[2], current[2]), 0)
            if current[0] < previous[1] - allowed_overlap:
                errors.append({"code": "overlap", "track_id": track_id, "clips": [previous[2], current[2]], "message": "Clips on one track overlap"})

    video_overlays = [track for track in timeline.get("tracks", []) if track.get("kind") == "video" and track.get("role") != "main"]
    audio_tracks = [track for track in timeline.get("tracks", []) if track.get("kind") == "audio"]
    if len(video_overlays) > 1:
        errors.append({"code": "track_limit", "message": "Timeline v1 supports one overlay video track"})
    if len(audio_tracks) > 4:
        errors.append({"code": "track_limit", "message": "Timeline v1 supports up to four audio tracks"})

    for transition in timeline.get("transitions", []):
        duration = transition.get("duration_frames")
        if transition.get("type") not in ALLOWED_TRANSITIONS:
            errors.append({"code": "transition_type", "message": "Unsupported transition type"})
        if not isinstance(duration, int) or duration <= 0:
            errors.append({"code": "transition_duration", "message": "Transition duration must be positive frames"})
        if transition.get("from_clip_id") not in clip_ids or transition.get("to_clip_id") not in clip_ids:
            errors.append({"code": "transition_clip", "message": "Transition references an unknown clip"})
        else:
            clips = {clip.get("clip_id"): clip for track in timeline.get("tracks", []) for clip in track.get("clips", [])}
            left, right = clips[transition.get("from_clip_id")], clips[transition.get("to_clip_id")]
            if isinstance(duration, int) and duration > min(int(left.get("duration_frames", 0)), int(right.get("duration_frames", 0))):
                errors.append({"code": "transition_handle", "message": "Transition is longer than an adjacent clip"})
            main_clips = sorted((main_track or {}).get("clips", []), key=lambda item: item.get("timeline_start_frame", 0))
            pair_index = next((index for index, clip in enumerate(main_clips[:-1])
                               if clip.get("clip_id") == transition.get("from_clip_id")
                               and main_clips[index + 1].get("clip_id") == transition.get("to_clip_id")), None)
            if pair_index is None:
                errors.append({"code": "transition_adjacency", "message": "Transition must join adjacent main-track clips"})
            elif isinstance(duration, int):
                expected_start = main_clips[pair_index]["timeline_start_frame"] + main_clips[pair_index]["duration_frames"] - duration
                if main_clips[pair_index + 1]["timeline_start_frame"] != expected_start:
                    errors.append({"code": "transition_overlap", "message": "Crossfade placement must match its duration"})

    for group_id, members in linked.items():
        video = next((clip for kind, clip in members if kind == "video"), None)
        audio = next((clip for kind, clip in members if kind == "audio"), None)
        if video and audio and (
            video.get("timeline_start_frame") != audio.get("timeline_start_frame")
            or video.get("duration_frames") != audio.get("duration_frames")
            or video.get("source_in_us") != audio.get("source_in_us")
            or video.get("source_out_us") != audio.get("source_out_us")
        ):
            errors.append({"code": "linked_sync", "linked_group_id": group_id, "message": "Linked video and audio are out of sync"})

    if for_export:
        if not main_track or not main_track.get("clips"):
            errors.append({"code": "main_track", "message": "Export requires a populated main video track"})
        elif main_track:
            ordered = sorted(main_track["clips"], key=lambda item: item["timeline_start_frame"])
            cursor = 0
            previous_id = None
            transition_pairs = {(item.get("from_clip_id"), item.get("to_clip_id")): int(item.get("duration_frames") or 0) for item in timeline.get("transitions", [])}
            for clip in ordered:
                expected = cursor - transition_pairs.get((previous_id, clip["clip_id"]), 0)
                if clip["timeline_start_frame"] != expected:
                    errors.append({"code": "main_gap", "clip_id": clip["clip_id"], "message": "Main video track contains a gap"})
                    break
                cursor = clip["timeline_start_frame"] + clip["duration_frames"]
                previous_id = clip["clip_id"]
            program_end = cursor
            for track in timeline.get("tracks", []):
                if track.get("kind") != "audio":
                    continue
                for clip in track.get("clips", []):
                    if clip["timeline_start_frame"] + clip["duration_frames"] > program_end:
                        errors.append({"code": "audio_beyond_program", "clip_id": clip["clip_id"], "message": "Audio extends beyond the main video"})

    stored_hash = timeline.get("timeline_hash")
    if stored_hash and stored_hash != canonical_hash(timeline):
        errors.append({"code": "timeline_hash", "message": "Timeline hash does not match its content"})
    if errors:
        raise TimelineValidationError(errors[0]["message"], errors)
