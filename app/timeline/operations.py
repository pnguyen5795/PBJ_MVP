from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from .contracts import find_clip, find_track, samples_from_frames


SUPPORTED_OPERATION_TYPES = {
    "clip.insert", "clip.delete", "clip.move", "clip.reorder", "clip.trim", "clip.split",
    "clip.speed.set", "clip.link", "clip.unlink", "track.add", "track.remove",
    "track.reorder", "track.mute", "video.transform.set", "transition.set",
    "transition.remove", "audio.volume.set", "audio.mute.set", "audio.fade.set",
    "canvas.set",
}

ALLOWED_CANVASES = {(1080, 1920), (1080, 1080), (1920, 1080)}
ALLOWED_TRANSITIONS = {"crossfade"}


def _require_keys(payload: Dict[str, Any], *keys: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ValueError("Timeline operation is missing: %s" % ", ".join(missing))


def _validate_transform(transform: Dict[str, Any]) -> None:
    if not isinstance(transform, dict) or transform.get("mode") not in {"fit", "fill"}:
        raise ValueError("Video transform mode must be fit or fill")
    for key in ("x", "y"):
        value = transform.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= float(value) <= 1:
            raise ValueError("Video transform %s must be between 0 and 1" % key)
    scale = transform.get("scale")
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not 0.1 <= float(scale) <= 4:
        raise ValueError("Video transform scale must be between 0.1 and 4")
    crop = transform.get("crop")
    if crop is not None:
        if not isinstance(crop, dict):
            raise ValueError("Video crop must be an object")
        values = {key: crop.get(key) for key in ("x", "y", "width", "height")}
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in values.values()):
            raise ValueError("Video crop coordinates must be numbers")
        x, y, width, height = (float(values[key]) for key in ("x", "y", "width", "height"))
        if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > 1.000001 or y + height > 1.000001:
            raise ValueError("Video crop must remain inside the source frame")
        preset = crop.get("preset", "freeform")
        if preset not in {"freeform", "9:16", "16:9", "1:1", "3:4", "4:3"}:
            raise ValueError("Video crop preset is unsupported")


def validate_operation(timeline: Dict[str, Any], operation: Dict[str, Any]) -> None:
    """Validate the typed command boundary before mutating timeline state."""
    kind = operation.get("type")
    payload = operation.get("payload")
    if kind not in SUPPORTED_OPERATION_TYPES or not isinstance(payload, dict):
        raise ValueError("Unsupported or malformed timeline operation: %s" % kind)
    if not isinstance(operation.get("operation_id"), str) or not operation["operation_id"].strip():
        raise ValueError("Every timeline operation requires an operation_id")
    if kind == "clip.insert":
        _require_keys(payload, "track_id", "clip")
        if not isinstance(payload["clip"], dict):
            raise ValueError("Inserted clip must be an object")
    elif kind in {"clip.delete", "clip.trim", "clip.speed.set", "clip.link", "clip.unlink"}:
        _require_keys(payload, "clip_id")
    elif kind == "clip.move":
        _require_keys(payload, "clip_id", "timeline_start_frame")
    elif kind == "clip.reorder":
        _require_keys(payload, "clip_id", "target_index")
        if not isinstance(payload["target_index"], int):
            raise ValueError("Clip target index must be an integer")
    elif kind == "clip.split":
        _require_keys(payload, "clip_id", "at_frame", "new_clip_id")
    elif kind in {"track.remove", "track.reorder", "track.mute"}:
        _require_keys(payload, "track_id")
        if kind == "track.reorder" and not isinstance(payload.get("order"), int):
            raise ValueError("Track order must be an integer")
        if kind == "track.mute" and not isinstance(payload.get("muted"), bool):
            raise ValueError("Track mute must be true or false")
    elif kind == "track.add":
        _require_keys(payload, "track")
    elif kind == "transition.set":
        _require_keys(payload, "transition")
        transition = payload["transition"]
        if not isinstance(transition, dict) or transition.get("type") not in ALLOWED_TRANSITIONS:
            raise ValueError("Only crossfade transitions are supported")
        _require_keys(transition, "transition_id", "from_clip_id", "to_clip_id", "duration_frames")
        if not isinstance(transition["duration_frames"], int) or not 1 <= transition["duration_frames"] <= 60:
            raise ValueError("Crossfade duration must be between 1 and 60 frames")
    elif kind == "transition.remove":
        _require_keys(payload, "transition_id")
    elif kind == "video.transform.set":
        _require_keys(payload, "transform")
        _validate_transform(payload["transform"])
    elif kind == "audio.volume.set":
        _require_keys(payload, "volume")
        if not isinstance(payload["volume"], (int, float)) or isinstance(payload["volume"], bool) or not 0 <= float(payload["volume"]) <= 2:
            raise ValueError("Audio volume must be between 0 and 2")
    elif kind == "audio.mute.set":
        _require_keys(payload, "muted")
        if not isinstance(payload["muted"], bool):
            raise ValueError("Audio mute must be true or false")
    elif kind == "audio.fade.set":
        _require_keys(payload, "fades")
        fades = payload["fades"]
        if not isinstance(fades, dict) or any(not isinstance(fades.get(key), int) or fades[key] < 0 for key in ("in_frames", "out_frames")):
            raise ValueError("Audio fades must use non-negative integer frames")
    elif kind == "canvas.set":
        _require_keys(payload, "canvas")
        canvas = payload["canvas"]
        if not isinstance(canvas, dict) or (canvas.get("width"), canvas.get("height")) not in ALLOWED_CANVASES:
            raise ValueError("Canvas must be 9:16, 1:1, or 16:9 at the supported resolution")


def _linked_clips(timeline: Dict[str, Any], group_id: str | None):
    if not group_id:
        return []
    return [clip for track in timeline.get("tracks", []) for clip in track.get("clips", [])
            if clip.get("linked_group_id") == group_id]


def _shift_clip(clip: Dict[str, Any], frames: int) -> None:
    clip["timeline_start_frame"] = int(clip["timeline_start_frame"]) + int(frames)
    if clip.get("kind") == "audio":
        clip["timeline_start_sample"] = samples_from_frames(clip["timeline_start_frame"])


def _clip_locations(timeline: Dict[str, Any], clips):
    wanted = {id(clip) for clip in clips}
    return [{"track_id": track["track_id"], "index": index, "clip": deepcopy(clip)}
            for track in timeline.get("tracks", []) for index, clip in enumerate(track.get("clips", []))
            if id(clip) in wanted]


def _restore_clip_locations(timeline: Dict[str, Any], locations) -> None:
    clip_ids = {item["clip"]["clip_id"] for item in locations}
    for track in timeline.get("tracks", []):
        track["clips"] = [clip for clip in track.get("clips", []) if clip.get("clip_id") not in clip_ids]
    for item in sorted(locations, key=lambda value: (value["track_id"], value["index"])):
        track = find_track(timeline, item["track_id"])
        track["clips"].insert(min(item["index"], len(track["clips"])), deepcopy(item["clip"]))


def _crossfade_affected(timeline: Dict[str, Any], from_id: str, to_id: str):
    from_track, from_index, _ = find_clip(timeline, from_id)
    to_track, to_index, to_clip = find_clip(timeline, to_id)
    if from_track is not to_track or from_track.get("kind") != "video" or from_track.get("role") != "main" or to_index != from_index + 1:
        raise ValueError("A crossfade must join adjacent clips on the main video track")
    ordered = from_track["clips"]
    affected = ordered[to_index:]
    linked_ids = {clip.get("linked_group_id") for clip in affected if clip.get("linked_group_id")}
    linked = [clip for group_id in linked_ids for clip in _linked_clips(timeline, group_id) if clip not in affected]
    return to_clip, affected + linked


def _op(kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": kind, "payload": payload}


def apply_operation(timeline: Dict[str, Any], operation: Dict[str, Any]) -> Dict[str, Any]:
    kind = operation.get("type")
    payload = deepcopy(operation.get("payload") or {})
    validate_operation(timeline, operation)

    if kind == "clip.insert":
        track = find_track(timeline, payload["track_id"])
        clip = deepcopy(payload["clip"])
        index = min(max(0, int(payload.get("index", len(track["clips"])))), len(track["clips"]))
        track["clips"].insert(index, clip)
        return _op("clip.delete", {"clip_id": clip["clip_id"]})
    if kind == "clip.delete":
        track, index, clip = find_clip(timeline, payload["clip_id"])
        group = _linked_clips(timeline, clip.get("linked_group_id")) or [clip]
        locations = _clip_locations(timeline, group)
        old_end = int(clip["timeline_start_frame"]) + int(clip["duration_frames"])
        downstream = []
        if payload.get("ripple") and track.get("kind") == "video" and track.get("role") == "main":
            downstream = [item for item in track["clips"] if item not in group and int(item["timeline_start_frame"]) >= old_end]
            linked_ids = {item.get("linked_group_id") for item in downstream if item.get("linked_group_id")}
            downstream += [linked for group_id in linked_ids for linked in _linked_clips(timeline, group_id) if linked not in downstream]
            locations += _clip_locations(timeline, downstream)
        for item in locations:
            if item["clip"]["clip_id"] in {value["clip_id"] for value in group}:
                owner = find_track(timeline, item["track_id"])
                owner["clips"] = [value for value in owner["clips"] if value.get("clip_id") != item["clip"]["clip_id"]]
        for item in downstream:
            _shift_clip(item, -int(clip["duration_frames"]))
        return _op("clips.restore", {"locations": locations})
    if kind == "clip.move":
        track, index, clip = find_clip(timeline, payload["clip_id"])
        group = _linked_clips(timeline, clip.get("linked_group_id")) or [clip]
        before = _clip_locations(timeline, group)
        delta = int(payload["timeline_start_frame"]) - int(clip["timeline_start_frame"])
        destination = find_track(timeline, payload.get("track_id", track["track_id"]))
        if destination is not track:
            track["clips"].pop(index)
            destination["clips"].insert(min(int(payload.get("index", len(destination["clips"]))), len(destination["clips"])), clip)
        for member in group:
            _shift_clip(member, delta)
        return _op("clips.restore", {"locations": before})
    if kind == "clip.reorder":
        track, index, clip = find_clip(timeline, payload["clip_id"])
        if track.get("kind") != "video" or track.get("role") != "main":
            raise ValueError("Only main-track clips use magnetic reordering")
        linked = [member for item in track["clips"] for member in _linked_clips(timeline, item.get("linked_group_id"))]
        before = _clip_locations(timeline, track["clips"] + linked)
        before_transitions = deepcopy(timeline.get("transitions", []))
        track["clips"].pop(index)
        target = min(max(0, int(payload["target_index"])), len(track["clips"]))
        track["clips"].insert(target, clip)
        adjacent = {(track["clips"][i - 1]["clip_id"], track["clips"][i]["clip_id"])
                    for i in range(1, len(track["clips"]))}
        timeline["transitions"] = [item for item in timeline.get("transitions", [])
                                   if (item.get("from_clip_id"), item.get("to_clip_id")) in adjacent]
        transition_map = {(item["from_clip_id"], item["to_clip_id"]): item for item in timeline["transitions"]}
        cursor = 0
        previous = None
        for member in track["clips"]:
            overlap = int((transition_map.get((previous["clip_id"], member["clip_id"])) or {}).get("duration_frames", 0)) if previous else 0
            wanted = cursor - overlap
            delta = wanted - int(member["timeline_start_frame"])
            group = _linked_clips(timeline, member.get("linked_group_id")) or [member]
            for grouped in group:
                _shift_clip(grouped, delta)
            cursor = wanted + int(member["duration_frames"])
            previous = member
        return _op("clips.restore", {"locations": before, "transitions": before_transitions})
    if kind == "clip.trim":
        _, _, clip = find_clip(timeline, payload["clip_id"])
        group = _linked_clips(timeline, clip.get("linked_group_id")) or [clip]
        before = _clip_locations(timeline, group)
        old_end = int(clip["timeline_start_frame"]) + int(clip["duration_frames"])
        main = next((track for track in timeline["tracks"] if track.get("kind") == "video" and track.get("role") == "main"), None)
        downstream = []
        if payload.get("ripple") and main and clip in main.get("clips", []):
            downstream = [item for item in main["clips"] if item not in group and int(item["timeline_start_frame"]) >= old_end]
            linked_ids = {item.get("linked_group_id") for item in downstream if item.get("linked_group_id")}
            downstream += [linked for group_id in linked_ids for linked in _linked_clips(timeline, group_id) if linked not in downstream]
            before += _clip_locations(timeline, downstream)
        for member in group:
            for key in ("source_in_us", "source_out_us", "timeline_start_frame", "duration_frames"):
                if key in payload:
                    member[key] = int(payload[key])
            if member.get("kind") == "audio":
                member["timeline_start_sample"] = samples_from_frames(member["timeline_start_frame"])
                member["duration_samples"] = samples_from_frames(member["duration_frames"])
        new_end = int(clip["timeline_start_frame"]) + int(clip["duration_frames"])
        if payload.get("ripple") and new_end != old_end:
            if main and clip in main.get("clips", []):
                for item in downstream:
                    _shift_clip(item, new_end - old_end)
        return _op("clips.restore", {"locations": before})
    if kind == "clip.split":
        track, index, clip = find_clip(timeline, payload["clip_id"])
        at = int(payload["at_frame"])
        offset = at - int(clip["timeline_start_frame"])
        if offset <= 0 or offset >= int(clip["duration_frames"]):
            raise ValueError("Split must occur inside the clip")
        group = _linked_clips(timeline, clip.get("linked_group_id")) or [clip]
        originals = _clip_locations(timeline, group)
        rate = float(clip.get("playback_rate", 1.0))
        source_delta = int(round(offset / 30 * 1_000_000 * rate))
        # A split creates two independently editable sync groups. Keeping the
        # right-hand video/audio pair in the original group would make a later
        # trim, speed change, move, or delete affect both halves of the split.
        right_group_id = None
        if clip.get("linked_group_id"):
            right_group_id = str(payload.get("new_linked_group_id") or (payload["new_clip_id"] + "-sync"))
        right_ids = []
        for member in group:
            owner, member_index, _ = find_clip(timeline, member["clip_id"])
            right = deepcopy(member)
            right["clip_id"] = payload["new_clip_id"] if member is clip else payload["new_clip_id"] + "-linked-" + member["clip_id"]
            right_ids.append(right["clip_id"])
            if right_group_id:
                right["linked_group_id"] = right_group_id
            right["source_in_us"] = member["source_in_us"] + source_delta
            right["timeline_start_frame"] = at
            right["duration_frames"] = member["duration_frames"] - offset
            member["source_out_us"] = right["source_in_us"]
            member["duration_frames"] = offset
            for item in (member, right):
                if item.get("kind") == "audio":
                    item["timeline_start_sample"] = samples_from_frames(item["timeline_start_frame"])
                    item["duration_samples"] = samples_from_frames(item["duration_frames"])
            owner["clips"].insert(member_index + 1, right)
        return _op("clips.restore", {"locations": originals, "remove_ids": right_ids})
    if kind == "clip.speed.set":
        _, _, clip = find_clip(timeline, payload["clip_id"])
        group = _linked_clips(timeline, clip.get("linked_group_id")) or [clip]
        before = _clip_locations(timeline, group)
        old_end = int(clip["timeline_start_frame"]) + int(clip["duration_frames"])
        main = next((track for track in timeline["tracks"] if track.get("kind") == "video" and track.get("role") == "main"), None)
        downstream = []
        if payload.get("ripple") and main and clip in main.get("clips", []):
            downstream = [item for item in main["clips"] if item not in group and int(item["timeline_start_frame"]) >= old_end]
            linked_ids = {item.get("linked_group_id") for item in downstream if item.get("linked_group_id")}
            downstream += [linked for group_id in linked_ids for linked in _linked_clips(timeline, group_id) if linked not in downstream]
            before += _clip_locations(timeline, downstream)
        for member in group:
            member["playback_rate"] = float(payload["playback_rate"])
            member["duration_frames"] = int(payload["duration_frames"])
            if member.get("kind") == "audio":
                member["duration_samples"] = samples_from_frames(member["duration_frames"])
        if payload.get("ripple"):
            new_end = int(clip["timeline_start_frame"]) + int(clip["duration_frames"])
            for member in downstream:
                _shift_clip(member, new_end - old_end)
        return _op("clips.restore", {"locations": before})
    if kind in ("clip.link", "clip.unlink"):
        _, _, clip = find_clip(timeline, payload["clip_id"])
        before = clip.get("linked_group_id")
        clip["linked_group_id"] = payload.get("linked_group_id") if kind == "clip.link" else None
        return _op("clip.link" if before else "clip.unlink", {"clip_id": clip["clip_id"], "linked_group_id": before})
    if kind == "track.add":
        track = deepcopy(payload["track"])
        timeline["tracks"].insert(min(int(payload.get("index", len(timeline["tracks"]))), len(timeline["tracks"])), track)
        return _op("track.remove", {"track_id": track["track_id"]})
    if kind == "track.remove":
        track = find_track(timeline, payload["track_id"])
        index = timeline["tracks"].index(track)
        if track.get("clips"):
            raise ValueError("A populated track cannot be removed")
        timeline["tracks"].pop(index)
        return _op("track.add", {"track": deepcopy(track), "index": index})
    if kind == "track.reorder":
        track = find_track(timeline, payload["track_id"])
        before = int(track.get("order", 0))
        track["order"] = int(payload["order"])
        return _op("track.reorder", {"track_id": track["track_id"], "order": before})
    if kind == "track.mute":
        track = find_track(timeline, payload["track_id"])
        before = bool(track.get("muted", False))
        track["muted"] = bool(payload["muted"])
        return _op("track.mute", {"track_id": track["track_id"], "muted": before})
    if kind == "video.transform.set":
        _, _, clip = find_clip(timeline, payload["clip_id"])
        before = deepcopy(clip.get("transform") or {})
        clip["transform"] = deepcopy(payload["transform"])
        return _op("video.transform.set", {"clip_id": clip["clip_id"], "transform": before})
    if kind == "transition.set":
        transition = deepcopy(payload["transition"])
        existing = next((item for item in timeline["transitions"] if item.get("transition_id") == transition["transition_id"]), None)
        _, affected = _crossfade_affected(timeline, transition["from_clip_id"], transition["to_clip_id"])
        before = {
            "transition": deepcopy(existing),
            "transition_id": transition["transition_id"],
            "positions": {clip["clip_id"]: clip["timeline_start_frame"] for clip in affected},
        }
        old_duration = int(existing.get("duration_frames", 0)) if existing else 0
        shift = old_duration - int(transition["duration_frames"])
        for clip in affected:
            _shift_clip(clip, shift)
        if existing:
            existing.clear(); existing.update(transition)
        else:
            timeline["transitions"].append(transition)
        return _op("transition.restore", before)
    if kind == "transition.remove":
        index = next((i for i, item in enumerate(timeline["transitions"]) if item.get("transition_id") == payload["transition_id"]), None)
        if index is None:
            raise KeyError("Unknown transition")
        transition = timeline["transitions"].pop(index)
        _, affected = _crossfade_affected(timeline, transition["from_clip_id"], transition["to_clip_id"])
        before = {
            "transition": deepcopy(transition), "transition_id": transition["transition_id"],
            "positions": {clip["clip_id"]: clip["timeline_start_frame"] for clip in affected},
        }
        for clip in affected:
            _shift_clip(clip, int(transition["duration_frames"]))
        return _op("transition.restore", before)
    if kind in ("audio.volume.set", "audio.mute.set", "audio.fade.set"):
        _, _, clip = find_clip(timeline, payload["clip_id"])
        key = {"audio.volume.set": "volume", "audio.mute.set": "muted", "audio.fade.set": "fades"}[kind]
        before = deepcopy(clip.get(key, 1.0 if key == "volume" else False if key == "muted" else {"in_frames": 0, "out_frames": 0}))
        clip[key] = deepcopy(payload[key])
        return _op(kind, {"clip_id": clip["clip_id"], key: before})
    if kind == "canvas.set":
        before = deepcopy(timeline["canvas"])
        timeline["canvas"] = deepcopy(payload["canvas"])
        return _op("canvas.set", {"canvas": before})
    # Internal inverse used only by split undo.
    raise ValueError("Unsupported timeline operation: %s" % kind)


def apply_inverse(timeline: Dict[str, Any], inverse: Dict[str, Any]) -> Dict[str, Any]:
    if inverse.get("type") == "clip.split.restore":
        payload = inverse["payload"]
        track = find_track(timeline, payload["track_id"])
        track["clips"] = [item for item in track["clips"] if item.get("clip_id") != payload["right_clip_id"]]
        for index, item in enumerate(track["clips"]):
            if item.get("clip_id") == payload["left"]["clip_id"]:
                track["clips"][index] = deepcopy(payload["left"])
                break
        return {}
    if inverse.get("type") == "transition.restore":
        payload = inverse["payload"]
        timeline["transitions"] = [item for item in timeline["transitions"] if item.get("transition_id") != payload["transition_id"]]
        if payload.get("transition"):
            timeline["transitions"].append(deepcopy(payload["transition"]))
        positions = payload.get("positions") or {}
        for track in timeline.get("tracks", []):
            for clip in track.get("clips", []):
                if clip.get("clip_id") in positions:
                    clip["timeline_start_frame"] = int(positions[clip["clip_id"]])
                    if clip.get("kind") == "audio":
                        clip["timeline_start_sample"] = samples_from_frames(clip["timeline_start_frame"])
        return {}
    if inverse.get("type") == "clips.restore":
        remove_ids = set(inverse["payload"].get("remove_ids") or [])
        if remove_ids:
            for track in timeline.get("tracks", []):
                track["clips"] = [clip for clip in track.get("clips", []) if clip.get("clip_id") not in remove_ids]
        _restore_clip_locations(timeline, inverse["payload"]["locations"])
        if "transitions" in inverse["payload"]:
            timeline["transitions"] = deepcopy(inverse["payload"]["transitions"])
        return {}
    return apply_operation(timeline, inverse)
