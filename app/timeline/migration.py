from __future__ import annotations

from typing import Any, Dict

from .contracts import asset_from_raw, empty_timeline, frames_from_seconds, refresh_hash, samples_from_frames, us_from_seconds
from .storage import TimelineStore
from .validation import validate_timeline


def timeline_from_edit_plan(project: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    assets = [asset_from_raw(item, analyzed=item.get("analysis_status") != "not_requested") for item in project.get("raw_files", [])]
    timeline = empty_timeline(project["project_id"], assets, canvas={
        "width": int((plan.get("target") or {}).get("width", 1080)),
        "height": int((plan.get("target") or {}).get("height", 1920)),
        "background": "#000000",
    })
    tracks = {item["track_id"]: item for item in timeline["tracks"]}
    for index, segment in enumerate(plan.get("video_segments") or [], start=1):
        start = frames_from_seconds(segment["timeline_start"])
        end = frames_from_seconds(segment["timeline_end"])
        duration = end - start
        group = "link-%03d" % index
        clip = {
            "clip_id": "video-%03d" % index, "kind": "video", "asset_id": segment["source_file_id"],
            "source_in_us": us_from_seconds(segment["source_start"]), "source_out_us": us_from_seconds(segment["source_end"]),
            "timeline_start_frame": start, "duration_frames": duration,
            "playback_rate": float(segment.get("speed", 1)), "linked_group_id": group,
            "transform": {"mode": "fit" if segment.get("crop_mode") == "fit" else "fill", "x": float(segment.get("focal_x", .5)), "y": float(segment.get("focal_y", .5)), "scale": max(float(segment.get("zoom_start", 1)), float(segment.get("zoom_end", 1)))},
            "provenance": {"origin": "ai_initial", "style_reasons": segment.get("style_reasons", [])},
            "locked_for_ai": False,
        }
        tracks["video-main"]["clips"].append(clip)
        if index > 1 and segment.get("transition") == "crossfade" and float(segment.get("transition_duration", 0)) > 0:
            timeline["transitions"].append({"transition_id": "transition-%03d" % index, "type": "crossfade", "from_clip_id": "video-%03d" % (index - 1), "to_clip_id": clip["clip_id"], "duration_frames": frames_from_seconds(segment["transition_duration"])})
    for index, segment in enumerate(plan.get("audio_segments") or [], start=1):
        start = frames_from_seconds(segment["timeline_start"])
        end = frames_from_seconds(segment["timeline_end"])
        duration = end - start
        matching_video = next((item for item in tracks["video-main"]["clips"]
                               if item["asset_id"] == segment["source_file_id"]
                               and item["source_in_us"] == us_from_seconds(segment["source_start"])
                               and item["source_out_us"] == us_from_seconds(segment["source_end"])
                               and item["timeline_start_frame"] == start
                               and item["duration_frames"] == duration), None)
        clip = {
            "clip_id": "audio-%03d" % index, "kind": "audio", "asset_id": segment["source_file_id"],
            "source_in_us": us_from_seconds(segment["source_start"]), "source_out_us": us_from_seconds(segment["source_end"]),
            "timeline_start_frame": start, "duration_frames": duration,
            "timeline_start_sample": samples_from_frames(start), "duration_samples": samples_from_frames(duration),
            "playback_rate": float(segment.get("speed", 1)), "linked_group_id": matching_video.get("linked_group_id") if matching_video else None,
            "volume": 1.0, "muted": False, "fades": {"in_frames": 0, "out_frames": 0},
            "provenance": {"origin": "ai_initial"}, "locked_for_ai": False,
        }
        tracks["audio-original"]["clips"].append(clip)
    timeline["metadata"] = {
        "origin": "ai_initial", "legacy_plan_hash": plan.get("plan_hash"),
        "recipe_version": project.get("recipe_version"), "decision_model": plan.get("decision_model"),
        "decision_metadata": plan.get("decision_metadata", {}), "initial_timeline_hash": None,
    }
    refresh_hash(timeline)
    timeline["metadata"]["initial_timeline_hash"] = timeline["timeline_hash"]
    refresh_hash(timeline)
    validate_timeline(timeline)
    return timeline


def migrate_legacy_project(store, project_id: str) -> Dict[str, Any]:
    timelines = TimelineStore(store)
    if timelines.exists(project_id):
        return timelines.load(project_id)
    project = store.project(project_id)
    latest = project.get("latest_run") or (project.get("runs") or [{}])[-1]
    if not latest.get("plan_path"):
        raise ValueError("This project has no edit plan to migrate")
    plan = store.read_json(store.resolve_data_path(latest["plan_path"]))
    timeline = timeline_from_edit_plan(project, plan)
    timelines.initialize(project_id, timeline, origin="legacy_migration")
    return timeline
