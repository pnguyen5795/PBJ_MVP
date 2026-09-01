from __future__ import annotations

from typing import Any, Dict

from .contracts import TIMELINE_FPS


def preview_state_at_frame(timeline: Dict[str, Any], frame: int) -> Dict[str, Any]:
    """Resolve the deterministic editorial state used by browser preview tests."""
    frame = max(0, int(frame))
    state = {"frame": frame, "seconds": frame / TIMELINE_FPS, "video": [], "audio": []}
    transitions = {(item.get("from_clip_id"), item.get("to_clip_id")): item for item in timeline.get("transitions", [])}
    for track in sorted(timeline.get("tracks", []), key=lambda item: item.get("order", 0)):
        if track.get("muted"):
            continue
        ordered = sorted(track.get("clips", []), key=lambda item: item["timeline_start_frame"])
        for index, clip in enumerate(ordered):
            start = int(clip["timeline_start_frame"])
            end = start + int(clip["duration_frames"])
            if not (start <= frame < end) or clip.get("muted"):
                continue
            source_us = int(clip["source_in_us"] + round((frame - start) / TIMELINE_FPS * 1_000_000 * float(clip.get("playback_rate", 1))))
            resolved = {
                "track_id": track["track_id"], "clip_id": clip["clip_id"], "asset_id": clip["asset_id"],
                "source_us": source_us, "playback_rate": float(clip.get("playback_rate", 1)),
            }
            if track.get("kind") == "video":
                resolved["transform"] = clip.get("transform") or {"mode": "fill", "x": .5, "y": .5, "scale": 1}
                resolved["opacity"] = 1.0
                if index:
                    transition = transitions.get((ordered[index - 1]["clip_id"], clip["clip_id"]))
                    if transition and transition.get("type") == "crossfade":
                        duration = int(transition["duration_frames"])
                        resolved["opacity"] = min(1.0, max(0.0, (frame - start) / max(1, duration)))
                state["video"].append(resolved)
            else:
                fades = clip.get("fades") or {}
                local = frame - start
                gain = float(clip.get("volume", 1))
                fade_in, fade_out = int(fades.get("in_frames", 0)), int(fades.get("out_frames", 0))
                if fade_in and local < fade_in:
                    gain *= local / fade_in
                if fade_out and end - frame <= fade_out:
                    gain *= max(0, end - frame) / fade_out
                resolved["gain"] = gain
                state["audio"].append(resolved)
    return state
