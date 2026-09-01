"""Deterministic provenance records for plans, revisions, and renders.

The model proposes editorial plans. Application code owns canonicalization,
diffing, lineage, and receipts; none of these records grant shell access or
expand the renderer's allowlisted operations.
"""

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import hashlib
import json
import subprocess

from .storage import sha256, utc_now


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _range(segment: Dict[str, Any]) -> Tuple[float, float]:
    return float(segment.get("source_start", 0)), float(segment.get("source_end", 0))


def _overlap(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    if a.get("source_file_id") != b.get("source_file_id"):
        return 0.0
    a0, a1 = _range(a)
    b0, b1 = _range(b)
    return max(0.0, min(a1, b1) - max(a0, b0))


def _segment_id(segment: Dict[str, Any]) -> str:
    stable = {
        "source_file_id": segment.get("source_file_id"),
        "source_start": segment.get("source_start"),
        "source_end": segment.get("source_end"),
        "timeline_start": segment.get("timeline_start"),
        "timeline_end": segment.get("timeline_end"),
    }
    return "segment-" + canonical_sha256(stable)[:12]


def source_time_decisions(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize the final plan into auditable source-time decisions."""
    selection = plan.get("selection") or {}
    selected = selection.get("selected_candidates") or []
    influences = plan.get("decision_metadata") or {}
    records = []
    for index, segment in enumerate(plan.get("video_segments") or []):
        matches = [item for item in selected if item.get("candidate_id") in (segment.get("candidate_id"), segment.get("source_candidate_id"))]
        records.append({
            "decision_id": _segment_id(segment),
            "decision": "keep",
            "order": index,
            "source_file_id": segment.get("source_file_id"),
            "source_start": segment.get("source_start"),
            "source_end": segment.get("source_end"),
            "timeline_start": segment.get("timeline_start"),
            "timeline_end": segment.get("timeline_end"),
            "reason": "; ".join(segment.get("style_reasons") or []),
            "candidate_ids": [item.get("candidate_id") for item in matches],
            "recipe_rule_ids": segment.get("recipe_rule_ids") or [],
            "requirement_ids": segment.get("requirement_ids") or [],
            "influenced_by_signal_ids": influences.get("learning_signal_ids") or [],
            "influenced_by_example_ids": influences.get("approved_example_ids") or [],
        })
    return records


def diff_plans(previous: Optional[Dict[str, Any]], current: Dict[str, Any]) -> Dict[str, Any]:
    """Describe source-level changes without asking a model to interpret them."""
    current_segments = current.get("video_segments") or []
    if not previous:
        return {
            "schema_version": "1.0", "base_plan_hash": None,
            "plan_hash": canonical_sha256(current), "change_count": len(current_segments),
            "changes": [{"type": "added", "current": source_time_decisions({"video_segments": [item]})[0]} for item in current_segments],
        }
    previous_segments = previous.get("video_segments") or []
    unmatched_previous = set(range(len(previous_segments)))
    changes = []
    for current_index, segment in enumerate(current_segments):
        candidates = [(index, _overlap(previous_segments[index], segment)) for index in unmatched_previous]
        match_index, amount = max(candidates, key=lambda item: item[1], default=(None, 0.0))
        current_record = source_time_decisions({"video_segments": [segment]})[0]
        current_record["order"] = current_index
        if match_index is None or amount <= 0:
            changes.append({"type": "added", "current": current_record})
            continue
        unmatched_previous.remove(match_index)
        old = previous_segments[match_index]
        old_record = source_time_decisions({"video_segments": [old]})[0]
        old_record["order"] = match_index
        attributes = []
        if _range(old) != _range(segment): attributes.append("source_range")
        if match_index != current_index: attributes.append("order")
        for key in ("crop_mode", "focal_x", "focal_y", "zoom_start", "zoom_end", "speed", "transition", "transition_duration"):
            if old.get(key) != segment.get(key): attributes.append(key)
        if attributes:
            changes.append({"type": "modified", "attributes": attributes, "previous": old_record, "current": current_record})
        else:
            changes.append({"type": "retained", "previous": old_record, "current": current_record})
    for index in sorted(unmatched_previous):
        changes.append({"type": "removed", "previous": source_time_decisions({"video_segments": [previous_segments[index]]})[0]})
    return {
        "schema_version": "1.0",
        "base_plan_hash": canonical_sha256(previous),
        "plan_hash": canonical_sha256(current),
        "change_count": len([item for item in changes if item["type"] != "retained"]),
        "summary": {kind: len([item for item in changes if item["type"] == kind]) for kind in ("added", "removed", "modified", "retained")},
        "changes": changes,
    }


def _ffmpeg_version() -> Optional[str]:
    try:
        result = subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True, text=True, timeout=10)
        return result.stdout.splitlines()[0] if result.stdout else None
    except (OSError, subprocess.SubprocessError):
        return None


def render_receipt(project: Dict[str, Any], plan: Dict[str, Any], output_path: Path,
                   render_result: Dict[str, Any], command: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    sources = {item.get("file_id"): item for item in project.get("raw_files") or []}
    used_ids = sorted({item.get("source_file_id") for layer in ("video_segments", "audio_segments") for item in plan.get(layer) or [] if item.get("source_file_id")})
    return {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "project_id": project.get("project_id"),
        "recipe_id": project.get("style_id"),
        "recipe_version": project.get("recipe_version"),
        "plan_hash": canonical_sha256(plan),
        "compiled_command_hash": canonical_sha256(list(command)) if command is not None else None,
        "source_inputs": [{"file_id": file_id, "sha256": sources.get(file_id, {}).get("sha256"), "stored_path": sources.get(file_id, {}).get("stored_path")} for file_id in used_ids],
        "renderer": {"name": "pbj-ffmpeg", "contract_version": "1.0", "ffmpeg_version": _ffmpeg_version()},
        "media_policy": {"supplied_media_only": True, "original_recorded_audio_only": True, "generated_media": False},
        "verification": render_result.get("verification"),
        "output": {"sha256": sha256(output_path), "size_bytes": output_path.stat().st_size},
    }
