from __future__ import annotations

from typing import Any, Dict


def timeline_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    def clips(value):
        return {clip["clip_id"]: {**clip, "track_id": track["track_id"]}
                for track in value.get("tracks", []) for clip in track.get("clips", [])}
    left, right = clips(before), clips(after)
    added = sorted(set(right) - set(left))
    removed = sorted(set(left) - set(right))
    changed = []
    categories = {"trim": 0, "move": 0, "speed": 0, "transform": 0, "audio": 0, "other": 0}
    for clip_id in sorted(set(left) & set(right)):
        old, new = left[clip_id], right[clip_id]
        fields = sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))
        if not fields:
            continue
        changed.append({"clip_id": clip_id, "fields": fields, "before": old, "after": new})
        matched = False
        if any(key in fields for key in ("source_in_us", "source_out_us", "duration_frames")): categories["trim"] += 1; matched = True
        if any(key in fields for key in ("timeline_start_frame", "track_id")): categories["move"] += 1; matched = True
        if "playback_rate" in fields: categories["speed"] += 1; matched = True
        if "transform" in fields: categories["transform"] += 1; matched = True
        if any(key in fields for key in ("volume", "muted", "fades")): categories["audio"] += 1; matched = True
        if not matched: categories["other"] += 1
    transition_changed = before.get("transitions", []) != after.get("transitions", [])
    return {
        "schema_version": "1.0",
        "before_hash": before.get("timeline_hash"),
        "after_hash": after.get("timeline_hash"),
        "added_clip_ids": added,
        "removed_clip_ids": removed,
        "changed_clips": changed,
        "transition_changed": transition_changed,
        "canvas_changed": before.get("canvas") != after.get("canvas"),
        "summary": {"added": len(added), "removed": len(removed), "changed": len(changed), "transition_changed": int(transition_changed), **categories},
    }
