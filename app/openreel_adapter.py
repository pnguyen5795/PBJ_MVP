from __future__ import annotations

from typing import Any, Dict
from hashlib import sha256
from datetime import datetime
import json
import math
import secrets

from .timeline.contracts import timeline_duration_frames
from .storage import JsonStore, new_id, utc_now


OPENREEL_ADAPTER_SCHEMA = "pbj-openreel-project-v1"
OPENREEL_SNAPSHOT_SCHEMA = "pbj-openreel-snapshot-v1"
OPENREEL_EXPORT_SCHEMA = "pbj-openreel-export-v1"
OPENREEL_RENDER_RECEIPT_SCHEMA = "pbj-openreel-render-receipt-v1"


def _seconds_from_frames(frames: int, fps: int) -> float:
    return int(frames) / int(fps)


def _seconds_from_us(microseconds: int) -> float:
    return int(microseconds) / 1_000_000


def _frame_rate(value: Any, fallback: int) -> float:
    if value in (None, ""):
        return float(fallback)
    if isinstance(value, str) and "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            denominator_value = float(denominator)
            return float(numerator) / denominator_value if denominator_value else float(fallback)
        except ValueError:
            return float(fallback)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _media_item(project_id: str, asset: Dict[str, Any], canvas: Dict[str, Any], fps: int) -> Dict[str, Any]:
    metadata = asset.get("media_metadata") or {}
    return {
        "id": asset["asset_id"],
        "name": asset.get("original_name") or asset["asset_id"],
        "type": asset.get("kind", "video"),
        "fileHandle": None,
        "blob": None,
        "metadata": {
            "duration": _seconds_from_us(asset.get("duration_us", 0)),
            "width": int(asset.get("width") or canvas["width"]),
            "height": int(asset.get("height") or canvas["height"]),
            "frameRate": _frame_rate(metadata.get("frame_rate") or metadata.get("fps"), fps),
            "codec": str(metadata.get("video_codec") or metadata.get("codec") or "proxy"),
            "sampleRate": int(metadata.get("sample_rate") or 48_000),
            "channels": int(metadata.get("channels") or (2 if asset.get("has_audio") else 0)),
            "fileSize": int(metadata.get("size") or metadata.get("file_size") or 0),
            "hasVideo": asset.get("kind", "video") == "video",
            "hasAudio": bool(asset.get("has_audio", asset.get("kind") == "audio")),
        },
        "thumbnailUrl": None,
        "waveformData": None,
        "originalUrl": f"/api/projects/{project_id}/assets/{asset['asset_id']}/preview",
        "pbj": {
            "assetId": asset["asset_id"],
            "sha256": asset.get("sha256"),
            "permissionScope": asset.get("permission_scope"),
            "analyzed": bool(asset.get("analyzed")),
        },
    }


def _transform(clip: Dict[str, Any], canvas: Dict[str, Any]) -> Dict[str, Any]:
    source = clip.get("transform") or {}
    x = float(source.get("x", 0.5))
    y = float(source.get("y", 0.5))
    scale = float(source.get("scale", 1.0))
    result = {
        "position": {
            "x": (x - 0.5) * int(canvas["width"]),
            "y": (y - 0.5) * int(canvas["height"]),
        },
        "scale": {"x": scale, "y": scale},
        "rotation": 0,
        "anchor": {"x": 0.5, "y": 0.5},
        "opacity": 1,
        "fitMode": "contain" if source.get("mode") == "fit" else "cover",
    }
    crop = source.get("crop")
    if crop:
        result["crop"] = {
            "x": float(crop["x"]),
            "y": float(crop["y"]),
            "width": float(crop["width"]),
            "height": float(crop["height"]),
        }
    return result


def _clip(clip: Dict[str, Any], track_id: str, fps: int, canvas: Dict[str, Any]) -> Dict[str, Any]:
    fades = clip.get("fades") or {}
    return {
        "id": clip["clip_id"],
        "mediaId": clip["asset_id"],
        "trackId": track_id,
        "startTime": _seconds_from_frames(clip.get("timeline_start_frame", 0), fps),
        "duration": _seconds_from_frames(clip.get("duration_frames", 0), fps),
        "inPoint": _seconds_from_us(clip.get("source_in_us", 0)),
        "outPoint": _seconds_from_us(clip.get("source_out_us", 0)),
        "effects": [],
        "audioEffects": [],
        "transform": _transform(clip, canvas),
        "volume": 0 if clip.get("muted") else float(clip.get("volume", 1.0)),
        "fade": {
            "fadeIn": _seconds_from_frames(fades.get("in_frames", 0), fps),
            "fadeOut": _seconds_from_frames(fades.get("out_frames", 0), fps),
        },
        "keyframes": [],
        "speed": float(clip.get("playback_rate", 1.0)),
        "metadata": {
            "pbj": {
                "clipId": clip["clip_id"],
                "linkedGroupId": clip.get("linked_group_id"),
                "sourceInUs": int(clip.get("source_in_us", 0)),
                "sourceOutUs": int(clip.get("source_out_us", 0)),
                "timelineStartFrame": int(clip.get("timeline_start_frame", 0)),
                "durationFrames": int(clip.get("duration_frames", 0)),
                "transform": clip.get("transform") or {},
            }
        },
    }


def project_openreel(project: Dict[str, Any], timeline: Dict[str, Any]) -> Dict[str, Any]:
    fps = int(timeline["fps"])
    canvas = timeline["canvas"]
    tracks = []
    for track in sorted(timeline.get("tracks", []), key=lambda item: (item.get("kind") != "video", item.get("order", 0))):
        role = track.get("role")
        # OpenReel plays the source video's own audio with the video clip. PBJ's
        # canonical original-audio row exists for linked command/export logic;
        # projecting it as a second OpenReel track would duplicate playback.
        if track.get("kind") == "audio" and role == "original":
            continue
        tracks.append({
            "id": track["track_id"],
            "type": track["kind"],
            "role": "dialogue" if role == "original" else "music" if role == "uploaded" else "general",
            "name": str(role or track["kind"]).replace("_", " ").title(),
            "clips": [_clip(clip, track["track_id"], fps, canvas) for clip in track.get("clips", [])],
            "transitions": [],
            "locked": False,
            "hidden": False,
            "muted": bool(track.get("muted")),
            "solo": False,
            "groupId": None,
            "pbj": {"role": role, "order": int(track.get("order", 0))},
        })

    project_id = timeline["project_id"]
    return {
        "schemaVersion": OPENREEL_ADAPTER_SCHEMA,
        "authority": {
            "system": "pbj",
            "projectId": project_id,
            "revision": int(timeline["revision"]),
            "timelineHash": timeline["timeline_hash"],
            "snapshotUrl": f"/api/projects/{project_id}/openreel/snapshots",
            "latestSnapshotUrl": f"/api/projects/{project_id}/openreel/snapshots/latest",
            "exportIntentUrl": f"/api/projects/{project_id}/openreel/exports",
            "exportCompletionUrlTemplate": f"/api/projects/{project_id}/openreel/exports/{{export_id}}/complete",
        },
        "project": {
            "id": project_id,
            "name": project.get("name") or "PBJ Project",
            "createdAt": 0,
            "modifiedAt": 0,
            "settings": {
                "width": int(canvas["width"]),
                "height": int(canvas["height"]),
                "frameRate": fps,
                "sampleRate": int(timeline["audio_sample_rate"]),
                "channels": 2,
            },
            "mediaLibrary": {
                "items": [_media_item(project_id, asset, canvas, fps) for asset in timeline.get("assets", [])]
            },
            "timeline": {
                "tracks": tracks,
                "subtitles": [],
                "duration": _seconds_from_frames(timeline_duration_frames(timeline), fps),
                "markers": [],
                "backgroundFillMode": "color",
                "layoutBackgroundColor": canvas.get("background", "#000000"),
            },
            "capabilities": ["pbj-authoritative-project-v1"],
            "minimumReaderVersion": "0.1.2",
        },
    }


def project_openreel_for_resume(
    store: JsonStore,
    project: Dict[str, Any],
    timeline: Dict[str, Any],
) -> Dict[str, Any]:
    projection = project_openreel(project, timeline)
    projection["authority"]["loadedFrom"] = "first_timeline"
    try:
        snapshot = latest_openreel_snapshot(store, timeline["project_id"])
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return projection

    if (
        snapshot.get("schema_version") != OPENREEL_SNAPSHOT_SCHEMA
        or snapshot.get("project_id") != timeline["project_id"]
        or snapshot.get("source_timeline_hash") != timeline.get("timeline_hash")
        or int(snapshot.get("source_timeline_revision", -1)) != int(timeline.get("revision", -2))
    ):
        return projection
    openreel_project = snapshot.get("openreel_project")
    allowed_assets = {item["asset_id"] for item in timeline.get("assets", [])}
    media_items = ((openreel_project or {}).get("mediaLibrary") or {}).get("items") or []
    snapshot_assets = {item.get("id") for item in media_items if isinstance(item, dict)}
    if (
        not isinstance(openreel_project, dict)
        or openreel_project.get("id") != timeline["project_id"]
        or None in snapshot_assets
        or not snapshot_assets.issubset(allowed_assets)
    ):
        return projection

    projection["project"] = openreel_project
    projection["authority"]["loadedFrom"] = "latest_snapshot"
    projection["authority"]["snapshotId"] = snapshot.get("snapshot_id")
    return projection


def save_openreel_snapshot(
    store: JsonStore,
    project_id: str,
    timeline: Dict[str, Any],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    if payload.get("schema_version") != OPENREEL_SNAPSHOT_SCHEMA:
        raise ValueError("OpenReel snapshot schema is not supported")
    if payload.get("source_timeline_hash") != timeline.get("timeline_hash"):
        raise ValueError("OpenReel snapshot does not match the source PBJ timeline")
    if int(payload.get("source_timeline_revision", -1)) != int(timeline.get("revision", -2)):
        raise ValueError("OpenReel snapshot source revision is stale")
    openreel_project = payload.get("project")
    if not isinstance(openreel_project, dict) or openreel_project.get("id") != project_id:
        raise ValueError("OpenReel snapshot project identity is invalid")

    allowed_assets = {item["asset_id"] for item in timeline.get("assets", [])}
    media_items = ((openreel_project.get("mediaLibrary") or {}).get("items") or [])
    snapshot_assets = {item.get("id") for item in media_items if isinstance(item, dict)}
    if None in snapshot_assets or not snapshot_assets.issubset(allowed_assets):
        raise ValueError("OpenReel snapshot contains media outside the PBJ project")

    snapshot_id = f"snapshot-{secrets.token_hex(8)}"
    relative_path = f"projects/{project_id}/openreel/snapshots/{snapshot_id}.json"
    record = {
        "schema_version": OPENREEL_SNAPSHOT_SCHEMA,
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "created_at": utc_now(),
        "source_timeline_revision": int(timeline["revision"]),
        "source_timeline_hash": timeline["timeline_hash"],
        "media_asset_ids": sorted(snapshot_assets),
        "openreel_project": openreel_project,
        "status": "working",
    }
    store.write_json(store.data_dir / relative_path, record)
    store.write_json(store.data_dir / f"projects/{project_id}/openreel/latest.json", record)
    project = store.project(project_id)
    store.update_project(
        project_id,
        latest_openreel_snapshot_id=snapshot_id,
        latest_openreel_snapshot_path=relative_path,
        openreel_snapshot_count=int(project.get("openreel_snapshot_count", 0)) + 1,
        has_unexported_changes=True,
    )
    return {key: record[key] for key in (
        "schema_version", "snapshot_id", "project_id", "created_at",
        "source_timeline_revision", "source_timeline_hash", "status",
    )}


def latest_openreel_snapshot(store: JsonStore, project_id: str) -> Dict[str, Any]:
    path = store.project_dir(project_id) / "openreel" / "latest.json"
    if not path.exists():
        raise FileNotFoundError(project_id)
    return store.read_json(path)


def create_openreel_export_intent(
    store: JsonStore,
    project_id: str,
    timeline: Dict[str, Any],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    if not payload.get("approval_confirmation"):
        raise ValueError("Confirm that a successful export may become approved learning evidence")
    snapshot = latest_openreel_snapshot(store, project_id)
    requested_snapshot_id = payload.get("snapshot_id")
    if requested_snapshot_id and requested_snapshot_id != snapshot.get("snapshot_id"):
        raise ValueError("Review the latest saved OpenReel project before exporting")
    if (
        snapshot.get("schema_version") != OPENREEL_SNAPSHOT_SCHEMA
        or snapshot.get("project_id") != project_id
        or snapshot.get("source_timeline_hash") != timeline.get("timeline_hash")
        or int(snapshot.get("source_timeline_revision", -1)) != int(timeline.get("revision", -2))
    ):
        raise ValueError("The saved OpenReel project is stale")

    openreel_project = snapshot.get("openreel_project")
    if not isinstance(openreel_project, dict) or openreel_project.get("id") != project_id:
        raise ValueError("The saved OpenReel project identity is invalid")
    allowed_assets = {item["asset_id"] for item in timeline.get("assets", [])}
    media_items = ((openreel_project.get("mediaLibrary") or {}).get("items") or [])
    media_ids = {item.get("id") for item in media_items if isinstance(item, dict)}
    if None in media_ids or not media_ids.issubset(allowed_assets):
        raise ValueError("The saved OpenReel project contains unapproved media")

    clip_count = 0
    referenced_assets = set()
    for track in ((openreel_project.get("timeline") or {}).get("tracks") or []):
        if not isinstance(track, dict):
            raise ValueError("The saved OpenReel track structure is invalid")
        for clip in track.get("clips") or []:
            if not isinstance(clip, dict):
                raise ValueError("The saved OpenReel clip structure is invalid")
            clip_count += 1
            media_id = clip.get("mediaId")
            if media_id:
                referenced_assets.add(media_id)
                if media_id not in allowed_assets:
                    raise ValueError("An OpenReel clip references unapproved media")
            for field in ("startTime", "duration", "inPoint", "outPoint"):
                value = clip.get(field)
                if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
                    raise ValueError("An OpenReel clip contains invalid timing")
            if float(clip.get("startTime") or 0) < 0 or float(clip.get("duration") or 0) <= 0:
                raise ValueError("An OpenReel clip has an invalid timeline range")
            if float(clip.get("inPoint") or 0) < 0 or float(clip.get("outPoint") or 0) < float(clip.get("inPoint") or 0):
                raise ValueError("An OpenReel clip has an invalid source range")
    if clip_count == 0:
        raise ValueError("The saved OpenReel project has no clips to export")

    export_id = new_id("export")
    root = store.project_dir(project_id) / "openreel" / "exports" / export_id
    frozen_snapshot_path = root / "openreel_snapshot.json"
    record_path = root / "export.json"
    store.write_json(frozen_snapshot_path, snapshot)
    snapshot_sha256 = sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    record = {
        "schema_version": OPENREEL_EXPORT_SCHEMA,
        "export_id": export_id,
        "project_id": project_id,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_path": str(frozen_snapshot_path.relative_to(store.data_dir)),
        "snapshot_sha256": snapshot_sha256,
        "source_timeline_hash": timeline["timeline_hash"],
        "source_timeline_revision": int(timeline["revision"]),
        "created_at": utc_now(),
        "status": "awaiting_openreel_render",
        "approval_confirmation": True,
        "approve_on_success": False,
        "requires_post_render_approval": True,
        "media_asset_ids": sorted(referenced_assets),
        "clip_count": clip_count,
        "render_owner": "openreel",
        "approval_owner": "pbj",
    }
    store.write_json(record_path, record)
    store.update_project(
        project_id,
        latest_openreel_export_intent=record,
        has_unexported_changes=True,
    )
    return record


def complete_openreel_render(
    store: JsonStore,
    project_id: str,
    export_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    root = store.project_dir(project_id) / "openreel" / "exports" / export_id
    record_path = root / "export.json"
    if not record_path.exists():
        raise FileNotFoundError(export_id)
    record = store.read_json(record_path)
    if record.get("schema_version") != OPENREEL_EXPORT_SCHEMA or record.get("project_id") != project_id:
        raise ValueError("The OpenReel export identity is invalid")

    if record.get("status") == "render_complete_pending_approval":
        existing = store.read_json(root / "render_receipt.json")
        if payload == existing.get("client_receipt"):
            return record
        raise ValueError("This OpenReel export already has a different render receipt")
    if record.get("status") != "awaiting_openreel_render":
        raise ValueError("This OpenReel export is not awaiting a render receipt")
    if payload.get("schema_version") != OPENREEL_RENDER_RECEIPT_SCHEMA:
        raise ValueError("OpenReel render receipt schema is not supported")
    if payload.get("snapshot_id") != record.get("snapshot_id"):
        raise ValueError("OpenReel rendered a different project snapshot")

    frozen_path = store.data_dir / record["snapshot_path"]
    frozen_snapshot = store.read_json(frozen_path)
    frozen_sha256 = sha256(
        json.dumps(frozen_snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if frozen_sha256 != record.get("snapshot_sha256"):
        raise ValueError("The frozen OpenReel snapshot failed its integrity check")

    renderer = payload.get("renderer")
    if not isinstance(renderer, dict) or str(renderer.get("name", "")).casefold() != "openreel":
        raise ValueError("The render receipt must identify OpenReel as the renderer")
    if not str(renderer.get("source_revision") or "").strip():
        raise ValueError("The OpenReel source revision is required")

    output = payload.get("output")
    if not isinstance(output, dict):
        raise ValueError("The render receipt output is incomplete")
    output_sha256 = str(output.get("sha256") or "").lower()
    if len(output_sha256) != 64 or any(character not in "0123456789abcdef" for character in output_sha256):
        raise ValueError("The rendered output SHA-256 is invalid")
    size_bytes = output.get("size_bytes")
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes <= 0:
        raise ValueError("The rendered output size is invalid")
    if output.get("mime_type") != "video/mp4":
        raise ValueError("The rendered output must be an MP4 video")
    if output.get("delivered_to_user") is not True:
        raise ValueError("The render must be delivered before PBJ records completion")

    verification = payload.get("verification")
    required_checks = ("render_completed", "nonempty_output", "project_identity", "snapshot_identity")
    checks = verification.get("checks") if isinstance(verification, dict) else None
    if not isinstance(verification, dict) or verification.get("passed") is not True or not isinstance(checks, dict):
        raise ValueError("The OpenReel render verification did not pass")
    if any(checks.get(check) is not True for check in required_checks):
        raise ValueError("The OpenReel render receipt is missing a required verification check")

    completed_at = utc_now()
    receipt = {
        "schema_version": OPENREEL_RENDER_RECEIPT_SCHEMA,
        "export_id": export_id,
        "project_id": project_id,
        "snapshot_id": record["snapshot_id"],
        "received_at": completed_at,
        "client_receipt": payload,
    }
    receipt_path = root / "render_receipt.json"
    store.write_json(receipt_path, receipt)
    record.update(
        status="render_complete_pending_approval",
        render_completed_at=completed_at,
        render_receipt_path=str(receipt_path.relative_to(store.data_dir)),
        output_sha256=output_sha256,
        output_size_bytes=size_bytes,
        output_mime_type=output["mime_type"],
    )
    store.write_json(record_path, record)
    store.update_project(
        project_id,
        latest_openreel_export_intent=record,
        openreel_export_status="render_complete_pending_approval",
        has_unexported_changes=False,
    )
    return record


def _openreel_clips(project: Dict[str, Any]) -> list[Dict[str, Any]]:
    return [
        clip
        for track in ((project.get("timeline") or {}).get("tracks") or [])
        if isinstance(track, dict)
        for clip in (track.get("clips") or [])
        if isinstance(clip, dict)
    ]


def _openreel_outcome_metrics(
    initial_project: Dict[str, Any],
    approved_project: Dict[str, Any],
    elapsed_seconds: float | None,
) -> Dict[str, Any]:
    initial = _openreel_clips(initial_project)
    approved = _openreel_clips(approved_project)
    initial_by_id = {clip.get("id"): clip for clip in initial if clip.get("id")}
    approved_by_id = {clip.get("id"): clip for clip in approved if clip.get("id")}
    retained_ids = set(initial_by_id) & set(approved_by_id)

    def signature(clip: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "media_id": clip.get("mediaId"),
            "start_time": clip.get("startTime"),
            "duration": clip.get("duration"),
            "in_point": clip.get("inPoint"),
            "out_point": clip.get("outPoint"),
            "speed": clip.get("speed"),
            "volume": clip.get("volume"),
            "transform": clip.get("transform"),
        }

    changed_ids = sorted(
        clip_id for clip_id in retained_ids
        if signature(initial_by_id[clip_id]) != signature(approved_by_id[clip_id])
    )
    added_ids = sorted(set(approved_by_id) - set(initial_by_id))
    removed_ids = sorted(set(initial_by_id) - set(approved_by_id))
    initial_duration = float((initial_project.get("timeline") or {}).get("duration") or 0)
    approved_duration = float((approved_project.get("timeline") or {}).get("duration") or 0)
    return {
        "schema_version": "openreel-outcome-v1",
        "initial_clip_count": len(initial_by_id),
        "approved_clip_count": len(approved_by_id),
        "retained_clip_count": len(retained_ids),
        "first_cut_retention": round(len(retained_ids) / max(1, len(initial_by_id)), 4),
        "added_clip_ids": added_ids,
        "removed_clip_ids": removed_ids,
        "changed_clip_ids": changed_ids,
        "added_clip_count": len(added_ids),
        "removed_clip_count": len(removed_ids),
        "changed_clip_count": len(changed_ids),
        "initial_duration_seconds": initial_duration,
        "approved_duration_seconds": approved_duration,
        "duration_change_seconds": round(approved_duration - initial_duration, 6),
        "time_to_approval_seconds": round(elapsed_seconds, 3) if elapsed_seconds is not None else None,
        "comparison_boundary": "whole_openreel_project",
    }


def approve_openreel_export(
    store: JsonStore,
    project_id: str,
    export_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    from .learning_agent import LearningAssessmentService
    from .timeline.storage import TimelineStore

    if payload.get("approval_confirmation") is not True:
        raise ValueError("Confirm the finished OpenReel video before approving it")
    root = store.project_dir(project_id) / "openreel" / "exports" / export_id
    record_path = root / "export.json"
    if not record_path.exists():
        raise FileNotFoundError(export_id)
    record = store.read_json(record_path)
    if record.get("project_id") != project_id or record.get("schema_version") != OPENREEL_EXPORT_SCHEMA:
        raise ValueError("The OpenReel export identity is invalid")
    if record.get("status") == "approved":
        if payload.get("output_sha256") != record.get("output_sha256"):
            raise ValueError("This OpenReel export was approved for a different rendered output")
        return record["approval"]
    if record.get("status") != "render_complete_pending_approval":
        raise ValueError("Only a verified completed OpenReel render can be approved")
    if payload.get("output_sha256") != record.get("output_sha256"):
        raise ValueError("Confirm the exact rendered output before approving it")

    frozen_snapshot = store.read_json(store.data_dir / record["snapshot_path"])
    approved_project = frozen_snapshot.get("openreel_project")
    if not isinstance(approved_project, dict) or approved_project.get("id") != project_id:
        raise ValueError("The frozen OpenReel project identity is invalid")
    render_receipt = store.read_json(store.data_dir / record["render_receipt_path"])
    if render_receipt.get("export_id") != export_id or render_receipt.get("snapshot_id") != record.get("snapshot_id"):
        raise ValueError("The OpenReel render receipt identity is invalid")

    project = store.project(project_id)
    timelines = TimelineStore(store)
    initial_path = project.get("initial_timeline_path") or str(
        (timelines.root(project_id) / "snapshots" / "initial-ai.json").relative_to(store.data_dir)
    )
    initial_timeline = store.read_json(store.resolve_data_path(initial_path))
    initial_project = project_openreel(project, initial_timeline)["project"]
    approved_at = utc_now()
    elapsed = None
    try:
        elapsed = (
            datetime.fromisoformat(approved_at) - datetime.fromisoformat(project["created_at"])
        ).total_seconds()
    except (KeyError, TypeError, ValueError):
        pass
    metrics = _openreel_outcome_metrics(initial_project, approved_project, elapsed)
    comparison = {
        "schema_version": "pbj-openreel-approval-comparison-v1",
        "project_id": project_id,
        "export_id": export_id,
        "snapshot_id": record["snapshot_id"],
        "initial_project": initial_project,
        "approved_project": approved_project,
        "outcome_metrics": metrics,
    }
    comparison_path = root / "approval_comparison.json"
    store.write_json(comparison_path, comparison)

    existing = next((item for item in store.list_approved_examples() if item.get("project_id") == project_id), None)
    example_id = existing.get("example_id") if existing else new_id("example")
    example = {
        "schema_version": "5.0",
        "example_id": example_id,
        "approved_at": approved_at,
        "project_id": project_id,
        "project_name": project.get("name"),
        "device_id": project.get("device_id"),
        "permission_scope": "device_private",
        "export_id": export_id,
        "snapshot_id": record["snapshot_id"],
        "project_prompt": project.get("prompt"),
        "target_duration_seconds": project.get("target_duration_seconds"),
        "style_id": project.get("style_id"),
        "recipe_version": project.get("recipe_version"),
        "recipe": store.recipe_for_project(project),
        "initial_openreel_project": initial_project,
        "approved_openreel_project": approved_project,
        "comparison_path": str(comparison_path.relative_to(store.data_dir)),
        "render_receipt": render_receipt,
        "outcome_metrics": metrics,
    }
    store.write_json(store.approved_examples_dir / f"{example_id}.json", example)
    signal = store.upsert_learning_signal(project["style_id"], {
        "source_key": f"openreel-approval:{project_id}",
        "type": "approved_openreel_export",
        "scope": "style_candidate",
        "project_id": project_id,
        "device_id": project.get("device_id"),
        "example_id": example_id,
        "export_id": export_id,
        "snapshot_id": record["snapshot_id"],
        "output_sha256": record["output_sha256"],
        "outcome_metrics": metrics,
        "status": "candidate",
        "instruction": "Latest successfully approved OpenReel outcome for this project; count this project once when evaluating shared recipe changes.",
    })
    learning_assessment = LearningAssessmentService(store).assess_approval(project, record, metrics, [])
    store.upsert_learning_signal(project["style_id"], {
        "source_key": f"openreel-learning-assessment:{project_id}:{export_id}",
        "type": "learning_agent_assessment",
        "scope": "project_only",
        "project_id": project_id,
        "device_id": project.get("device_id"),
        "export_id": export_id,
        "status": "context",
        "assessment_status": learning_assessment.get("status"),
        "assessment_path": learning_assessment.get("path"),
        "instruction": "Advisory classification only; never count as independent support or automatically promote a recipe.",
    })
    evaluation = {
        "schema_version": "openreel-approval-v1",
        "evaluation_id": new_id("evaluation"),
        "recorded_at": approved_at,
        "recipe_id": project["style_id"],
        "recipe_version": project.get("recipe_version"),
        "project_id": project_id,
        "device_id": project.get("device_id"),
        "approved_example_id": example_id,
        "export_id": export_id,
        "snapshot_id": record["snapshot_id"],
        "outcome_metrics": metrics,
        "learning_status": "candidate_signal_saved",
        "learning_signal_id": signal["signal_id"],
        "learning_agent_status": learning_assessment.get("status"),
        "learning_agent_assessment_path": learning_assessment.get("path"),
        "applied_to_recipe": False,
    }
    evaluation_path = store.style_dir(project["style_id"]) / "evaluations" / f"{evaluation['evaluation_id']}.json"
    store.write_json(evaluation_path, evaluation)
    approval = {
        "approved": True,
        "approved_at": approved_at,
        "export_id": export_id,
        "snapshot_id": record["snapshot_id"],
        "example_id": example_id,
        "output_sha256": record["output_sha256"],
        "comparison_path": str(comparison_path.relative_to(store.data_dir)),
        "evaluation_id": evaluation["evaluation_id"],
    }
    record.update(status="approved", approved_at=approved_at, approval=approval)
    store.write_json(record_path, record)
    store.update_project(
        project_id,
        status="approved",
        final_approval=approval,
        latest_openreel_export_intent=record,
        openreel_export_status="approved",
        has_unexported_changes=False,
    )
    return approval
