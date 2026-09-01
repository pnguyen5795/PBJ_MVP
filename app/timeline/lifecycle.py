from __future__ import annotations

from typing import Any, Dict

from ..storage import JsonStore, utc_now


ACTIVE_JOB_STATES = {
    "analysis_queued", "analyzing_footage", "planning_timeline", "preparing_proxies",
    "proposal_running", "export_queued", "exporting",
}


def begin_timeline_job(store: JsonStore, project_id: str, status: str, task: str) -> Dict[str, Any]:
    project = store.project(project_id)
    if project.get("status") in ACTIVE_JOB_STATES:
        raise ValueError("Wait for the current project task to finish")
    return store.update_project(
        project_id, status=status, active_task=task, active_started_at=utc_now(), last_error=None,
        job_return_status=project.get("status") if project.get("status") in {"approved", "timeline_ready", "export_failed"} else "timeline_ready",
    )


def finish_timeline_job(store: JsonStore, project_id: str) -> Dict[str, Any]:
    project = store.project(project_id)
    return store.update_project(project_id, status=project.get("job_return_status") or "timeline_ready", active_task=None, last_error=None, job_return_status=None)


def fail_timeline_job(store: JsonStore, project_id: str, error: Exception | str) -> Dict[str, Any]:
    project = store.project(project_id)
    return store.update_project(
        project_id, status=project.get("job_return_status") or "timeline_ready", active_task=None, last_error=str(error), job_return_status=None,
    )


def mark_working_timeline_changed(store: JsonStore, project_id: str, timeline: Dict[str, Any],
                                  reason: str) -> Dict[str, Any]:
    """Make approval truth follow the exact working timeline lineage.

    Prior exports and approvals remain immutable history. The current working
    timeline is only considered approved when its hash still matches the most
    recent successful approval.
    """
    project = store.project(project_id)
    approval = project.get("final_approval") or {}
    approved_hash = approval.get("timeline_hash")
    has_unexported_changes = bool(approved_hash and approved_hash != timeline.get("timeline_hash"))
    status = "approved" if approved_hash and not has_unexported_changes else "timeline_ready"
    return store.update_project(
        project_id,
        status=status,
        timeline_hash=timeline.get("timeline_hash"),
        timeline_revision=timeline.get("revision"),
        has_unexported_changes=has_unexported_changes,
        working_timeline_change_reason=reason,
        active_task=None,
    )
