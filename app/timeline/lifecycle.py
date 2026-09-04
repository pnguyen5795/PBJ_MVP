from __future__ import annotations

from typing import Any, Dict

from ..storage import JsonStore, utc_now


ACTIVE_JOB_STATES = {
    "analysis_queued", "analyzing_footage",
    "rough_cut_queued", "planning_rough_cut", "rendering_rough_cut",
    "timeline_queued", "planning_timeline", "approval_running",
    "export_queued", "exporting",
    "project_deleting",
}


def begin_timeline_job(store: JsonStore, project_id: str, status: str, task: str) -> Dict[str, Any]:
    project = store.project(project_id)
    return store.transition_project(
        project_id, status=status, active_task=task, active_started_at=utc_now(), last_error=None,
        reject_statuses=ACTIVE_JOB_STATES,
        job_return_status=project.get("status") if project.get("status") in {"approved", "timeline_ready", "export_failed"} else "timeline_ready",
    )


def fail_timeline_job(store: JsonStore, project_id: str, error: Exception | str) -> Dict[str, Any]:
    project = store.project(project_id)
    safe_error = "PBJ could not complete this timeline task. Your saved work is safe; try again."
    return store.update_project(
        project_id,
        status=project.get("job_return_status") or "timeline_ready",
        active_task=None,
        active_started_at=None,
        last_error=safe_error,
        last_error_details={
            "type": type(error).__name__ if isinstance(error, Exception) else "TimelineTaskError",
            "code": "timeline_task_failed",
            "message": safe_error,
            "recorded_at": utc_now(),
        },
        job_return_status=None,
    )
