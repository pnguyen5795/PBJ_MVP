from __future__ import annotations

from typing import Any, Dict
from datetime import datetime

from ..storage import JsonStore, new_id, utc_now
from ..learning_agent import LearningAssessmentService
from .diff import timeline_diff
from .storage import TimelineStore


def _clips(timeline: Dict[str, Any]):
    return [clip for track in timeline.get("tracks", []) for clip in track.get("clips", [])]


def _main(timeline: Dict[str, Any]):
    track = next((item for item in timeline.get("tracks", []) if item.get("kind") == "video" and item.get("role") == "main"), {"clips": []})
    return sorted(track.get("clips", []), key=lambda item: item.get("timeline_start_frame", 0))


def _source_intervals(timeline: Dict[str, Any]):
    intervals: Dict[str, list[tuple[int, int]]] = {}
    for clip in _main(timeline):
        intervals.setdefault(clip["asset_id"], []).append((int(clip["source_in_us"]), int(clip["source_out_us"])))
    merged = {}
    for asset_id, values in intervals.items():
        result = []
        for start, end in sorted(values):
            if result and start <= result[-1][1]:
                result[-1] = (result[-1][0], max(result[-1][1], end))
            else:
                result.append((start, end))
        merged[asset_id] = result
    return merged


def _source_overlap_us(first: Dict[str, Any], second: Dict[str, Any]) -> tuple[int, int]:
    left, right = _source_intervals(first), _source_intervals(second)
    selected = sum(end - start for values in left.values() for start, end in values)
    overlap = 0
    for asset_id, values in left.items():
        for start, end in values:
            for other_start, other_end in right.get(asset_id, []):
                overlap += max(0, min(end, other_end) - max(start, other_start))
    return selected, overlap


def _same_source_moment(first: Dict[str, Any] | None, second: Dict[str, Any] | None) -> bool:
    return bool(first and second and first.get("asset_id") == second.get("asset_id")
                and min(int(first["source_out_us"]), int(second["source_out_us"]))
                > max(int(first["source_in_us"]), int(second["source_in_us"])))


def timeline_outcome_metrics(initial: Dict[str, Any], approved: Dict[str, Any], events,
                             proposals, elapsed_seconds: float | None,
                             active_transaction_ids=None) -> Dict[str, Any]:
    diff = timeline_diff(initial, approved)
    initial_ids = {item["clip_id"] for item in _clips(initial)}
    approved_ids = {item["clip_id"] for item in _clips(approved)}
    retained = initial_ids & approved_ids
    initial_main, approved_main = _main(initial), _main(approved)
    applied = [item for item in proposals if item.get("status") == "applied"]
    rejected = [item for item in proposals if item.get("status") == "rejected"]
    active_ids = set(active_transaction_ids or [])
    surviving = [item for item in applied if (item.get("transaction") or {}).get("transaction_id") in active_ids]
    selected_source_us, retained_source_us = _source_overlap_us(initial, approved)
    manual_transactions = [item for item in events if item.get("type") == "timeline.transaction" and (item.get("transaction") or {}).get("origin") == "manual"]
    return {
        "schema_version": "1.0",
        "initial_timeline_hash": initial.get("timeline_hash"), "approved_timeline_hash": approved.get("timeline_hash"),
        "initial_clip_count": len(initial_ids), "approved_clip_count": len(approved_ids),
        "retained_clip_count": len(retained),
        "first_cut_retention": round(len(retained) / max(1, len(initial_ids)), 4),
        "source_time_selected_us": selected_source_us,
        "source_time_retained_us": retained_source_us,
        "source_time_retention": round(retained_source_us / max(1, selected_source_us), 4),
        "opening_retained": _same_source_moment(initial_main[0] if initial_main else None, approved_main[0] if approved_main else None),
        "ending_retained": _same_source_moment(initial_main[-1] if initial_main else None, approved_main[-1] if approved_main else None),
        "manual_transaction_count": len(manual_transactions),
        "manual_operation_count": sum(len((item.get("transaction") or {}).get("operations") or []) for item in manual_transactions),
        "ai_proposal_count": len(proposals), "ai_proposal_applied_count": len(applied),
        "ai_proposal_surviving_count": len(surviving),
        "ai_proposal_reverted_count": len(applied) - len(surviving),
        "ai_proposal_rejected_count": len(rejected),
        "ai_proposal_rejection_rate": round(len(rejected) / max(1, len(proposals)), 4),
        "time_to_approval_seconds": round(elapsed_seconds, 3) if elapsed_seconds is not None else None,
        "change_summary": diff["summary"], "timeline_diff": diff,
    }


def approve_timeline_export(store: JsonStore, project_id: str, export: Dict[str, Any],
                            timeline: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
    project = store.project(project_id)
    timelines = TimelineStore(store)
    initial_path = project.get("initial_timeline_path") or str((timelines.root(project_id) / "snapshots" / "initial-ai.json").relative_to(store.data_dir))
    initial = store.read_json(store.resolve_data_path(initial_path))
    events = timelines.events(project_id)
    proposal_root = timelines.root(project_id) / "proposals"
    proposals = []
    for path in proposal_root.glob("proposal-*.json"):
        try: proposals.append(store.read_json(path))
        except (OSError, ValueError): continue
    elapsed = None
    try:
        start = next(item["recorded_at"] for item in events if item.get("type") == "timeline.initialized")
        elapsed = (datetime.fromisoformat(export["completed_at"]) - datetime.fromisoformat(start)).total_seconds()
    except (StopIteration, KeyError, TypeError, ValueError):
        pass
    history_path = timelines.root(project_id) / "history.json"
    history = store.read_json(history_path) if history_path.exists() else {"undo": []}
    active_transaction_ids = [item.get("transaction_id") for item in history.get("undo", []) if item.get("transaction_id")]
    metrics = timeline_outcome_metrics(initial, timeline, events, proposals, elapsed, active_transaction_ids)
    diff_path = timelines.root(project_id) / "snapshots" / ("export-%s-diff.json" % export["export_id"])
    snapshot_path = timelines.root(project_id) / "snapshots" / ("export-%s.json" % export["export_id"])
    store.write_json(diff_path, metrics["timeline_diff"])
    store.write_json(snapshot_path, timeline)

    existing = next((item for item in store.list_approved_examples() if item.get("project_id") == project_id), None)
    example_id = existing.get("example_id") if existing else new_id("example")
    example = {
        "schema_version": "4.0", "example_id": example_id, "approved_at": export["completed_at"],
        "project_id": project_id, "project_name": project.get("name"), "device_id": project.get("device_id"),
        "permission_scope": "device_private", "export_id": export["export_id"],
        "project_prompt": project.get("prompt"), "target_duration_seconds": project.get("target_duration_seconds"),
        "style_id": project.get("style_id"), "recipe_version": project.get("recipe_version"),
        "recipe": store.recipe_for_project(project), "content_map": project.get("content_map"),
        "initial_timeline": initial, "approved_timeline": timeline,
        "timeline_diff_path": str(diff_path.relative_to(store.data_dir)),
        "render_receipt": receipt, "outcome_metrics": metrics,
        "revision_history": [{"type": item.get("type"), "transaction_id": item.get("transaction_id"), "recorded_at": item.get("recorded_at")} for item in events],
    }
    store.write_json(store.approved_examples_dir / (example_id + ".json"), example)
    signal = store.upsert_learning_signal(project["style_id"], {
        "source_key": "timeline-approval:%s" % project_id,
        "type": "approved_timeline_export", "scope": "style_candidate", "project_id": project_id,
        "device_id": project.get("device_id"), "example_id": example_id,
        "export_id": export["export_id"], "timeline_hash": timeline["timeline_hash"],
        "outcome_metrics": metrics, "status": "candidate",
        "instruction": "Latest successful approved timeline for this project; count this project once when evaluating shared recipe changes.",
    })
    learning_assessment = LearningAssessmentService(store).assess_approval(
        project, export, metrics, proposals,
    )
    store.upsert_learning_signal(project["style_id"], {
        "source_key": "learning-agent-assessment:%s:%s" % (project_id, export["export_id"]),
        "type": "learning_agent_assessment", "scope": "project_only",
        "project_id": project_id, "device_id": project.get("device_id"),
        "export_id": export["export_id"], "status": "context",
        "assessment_status": learning_assessment.get("status"),
        "assessment_path": learning_assessment.get("path"),
        "instruction": "Advisory classification only; never count as independent support or automatically promote a recipe.",
    })
    evaluation = {
        "schema_version": "2.0", "evaluation_id": new_id("evaluation"), "recorded_at": export["completed_at"],
        "recipe_id": project["style_id"], "recipe_version": project.get("recipe_version"),
        "project_id": project_id, "device_id": project.get("device_id"), "approved_example_id": example_id,
        "export_id": export["export_id"], "outcome_metrics": metrics,
        "learning_status": "candidate_signal_saved", "learning_signal_id": signal["signal_id"],
        "learning_agent_status": learning_assessment.get("status"),
        "learning_agent_assessment_path": learning_assessment.get("path"),
        "applied_to_recipe": False,
    }
    store.write_json(store.style_dir(project["style_id"]) / "evaluations" / (evaluation["evaluation_id"] + ".json"), evaluation)
    approval = {
        "approved": True, "approved_at": export["completed_at"], "export_id": export["export_id"],
        "example_id": example_id, "timeline_hash": timeline["timeline_hash"],
        "timeline_snapshot_path": str(snapshot_path.relative_to(store.data_dir)),
        "timeline_diff_path": str(diff_path.relative_to(store.data_dir)),
        "evaluation_id": evaluation["evaluation_id"],
    }
    store.update_project(project_id, final_approval=approval, has_unexported_changes=False)
    return approval
