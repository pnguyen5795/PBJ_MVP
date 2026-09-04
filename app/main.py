from pathlib import Path
from typing import List
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
from threading import Lock
from urllib.parse import unquote

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import save_api_keys, settings
from .contracts import ANALYSIS_SCHEMA, EDIT_PLAN_SCHEMA, STYLE_PROFILE_SCHEMA
from .demo_lifecycle import DemoActivityTracker, DemoLifecycleManager
from .editorial_intelligence import interpret_brief, match_recipe
from .ffmpeg_runtime import (
    active_media_process_count, shutdown_media_process_runtime,
    start_media_process_runtime,
)
from .media import ffmpeg_status, inspect_video
from .providers import PROVIDERS, provider_for_name, readiness_for_provider
from .security import (
    LoginRateLimiter, apply_security_headers, client_fingerprint,
    exact_secret_match, same_origin,
)
from .storage import ID_PATTERN, JsonStore, VIDEO_EXTENSIONS, new_id, safe_name, utc_now
from .workflows import (
    ACTIVE_STYLE_JOB_STATES, ProjectAnalysisWorkflow, StyleWorkflow,
    TimelinePreparationWorkflow, failure_fields,
)
from .timeline.migration import migrate_legacy_project, timeline_from_edit_plan
from .timeline.storage import TimelineStore
from .timeline.export import TimelineExportService
from .timeline.lifecycle import ACTIVE_JOB_STATES, begin_timeline_job, fail_timeline_job
from .timeline.learning import approve_timeline_export


app = FastAPI(title="PB&J Recipe Engine", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
templates = Jinja2Templates(directory=str(settings.templates_dir))
store = JsonStore(settings.data_dir)
UI_CSS_NAMES = ("app.css", "workflow.css", "mobile-v2.css", "troy-foundation.css", "troy-screens.css")
UI_CSS_CONTENT = "\n".join((settings.static_dir / name).read_text() for name in UI_CSS_NAMES)
UI_CSS_ETAG = '"%s"' % hashlib.sha256(UI_CSS_CONTENT.encode("utf-8")).hexdigest()
upload_manifest_lock = Lock()
upload_reserved_bytes = {}
diagnostic_log_lock = Lock()
approval_lock = Lock()
render_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pbj-render")
inspection_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pbj-inspect")
UPLOAD_WRITE_BUFFER_BYTES = 1024 * 1024
ACCESS_FORM_MAX_BYTES = 1024
PROJECT_NAME_MAX_CHARS = 120
PROJECT_DESCRIPTION_MAX_CHARS = 1600
# Starlette base64-encodes the JSON session before signing it. Keeping the
# complete prospective session under 2 KiB leaves ample room below browsers'
# common 4096-byte per-cookie limit, including the signature and attributes.
PROJECT_SESSION_JSON_MAX_BYTES = 2048
diagnostic_rate_windows = {}
client_diagnostic_logger = logging.getLogger("pbj.client_diagnostic")
server_error_logger = logging.getLogger("pbj.server_error")
login_rate_limiter = LoginRateLimiter()


def _finalize_upload_promotion(session_id: str, project_id: str) -> None:
    """Commit a promotion pointer before removing its retry-safe staging data."""
    store.update_upload_session(
        session_id, files=[], inspection_metadata={}, name="", style_id="",
        provider="", prompt="", intent_interpretation=None, recipe_match=None,
        target_duration_seconds=0, total_duration_seconds=0, draft_id=None,
        status="promoted", project_id=project_id,
    )
    shutil.rmtree(store.upload_session_dir(session_id) / "raw", ignore_errors=True)


for _style in store.list_styles():
    try:
        store.backfill_learning_signals(_style["style_id"])
    except (OSError, ValueError, KeyError):
        # A damaged historical record must not prevent the local app starting.
        continue
try:
    store.backfill_permission_scopes()
except (OSError, ValueError, KeyError):
    # Permission metadata is a safe migration; damaged historical records stay
    # untouched and can be inspected without preventing the app from starting.
    pass


def recover_interrupted_jobs() -> None:
    """Make in-process jobs retryable after a server restart.

    BackgroundTasks live only inside the current process. If the process stops,
    a queued/working marker must not make the UI claim that a job is still
    running. Completed analysis, footage, and prior cuts remain untouched.
    """
    project_states = {
        "analysis_queued": "analysis_failed",
        "analyzing_footage": "analysis_failed",
        "rough_cut_queued": "rough_cut_failed",
        "planning_rough_cut": "rough_cut_failed",
        "rendering_rough_cut": "rough_cut_failed",
        "timeline_queued": "timeline_failed",
        "planning_timeline": "timeline_failed",
        "approval_running": "timeline_ready",
        "export_queued": "export_failed",
        "exporting": "export_failed",
        "project_deleting": "timeline_ready",
    }
    for project in store.list_projects():
        status = project.get("status")
        if status not in project_states:
            continue
        interrupted = "This edit was interrupted when PBJ restarted. Your footage, timeline, and completed analysis are safe; try this step again."
        if status == "project_deleting":
            interrupted = "Project deletion was interrupted when PBJ restarted. The project was kept; you can try deleting it again."
            fallback = project.get("deletion_return_status")
            if fallback not in {
                "footage_uploaded", "footage_analyzed", "rough_cut_ready",
                "analysis_failed", "rough_cut_failed", "timeline_failed",
                "export_failed", "timeline_ready", "approved",
            }:
                fallback = "timeline_ready"
        else:
            fallback = project.get("job_return_status")
            if fallback not in {"approved", "timeline_ready", "export_failed"}:
                fallback = project_states[status]
        completed_approval = (
            status == "approval_running"
            and (project.get("final_approval") or {}).get("approved") is True
            and (project.get("final_approval") or {}).get("export_id")
            == (project.get("latest_export") or {}).get("export_id")
        )
        if completed_approval:
            fallback = "approved"
        recovery_error = None if completed_approval else interrupted
        recovery_details = None if completed_approval else {
            "type": "InterruptedDeletion" if status == "project_deleting" else "InterruptedJob",
            "code": "project_deletion_interrupted" if status == "project_deleting" else "project_job_interrupted",
            "message": interrupted,
            "recorded_at": utc_now(),
        }
        if status in {"export_queued", "exporting"} and project.get("active_export_id"):
            export_path = (store.project_dir(project["project_id"]) / "exports" /
                           project["active_export_id"] / "export.json")
            if export_path.exists():
                export = store.read_json(export_path)
                export.update(status="failed", failed_at=utc_now(), error=interrupted)
                store.write_json(export_path, export)
        store.update_project(
            project["project_id"], status=fallback, active_revision=None,
            active_task=None, active_export_id=None, last_error=recovery_error,
            job_return_status=None,
            deletion_return_status=None,
            last_error_details=recovery_details,
        )
    style_states = {
        "analysis_queued": "analysis_failed",
        "analyzing_references": "analysis_failed",
        "revision_queued": "revision_failed",
        "revising_style": "revision_failed",
    }
    for style in store.list_styles():
        status = style.get("status")
        if status == "style_deleting":
            store.restore_style_deletion(
                style["style_id"],
                "Recipe archiving was interrupted when PBJ restarted. The recipe was kept; you can try again.",
            )
            continue
        if status not in style_states:
            continue
        store.update_style(
            style["style_id"], status=style_states[status],
            last_error="This recipe task was interrupted when PBJ restarted. Saved reference analysis is safe; try again.",
            last_error_details={
                "type": "InterruptedJob", "code": "recipe_task_interrupted",
                "message": "The in-process recipe task ended with the previous PBJ server process.",
                "recorded_at": utc_now(),
            },
        )
    # Media inspection also runs in-process.  If the server stops during that
    # short phase, reopen the already-saved batch instead of leaving the user
    # with an upload session that can never resume.
    for upload_session in store.list_records(store.upload_sessions_dir, "manifest.json"):
        raw_dir = store.upload_session_dir(upload_session["session_id"]) / "raw"
        for partial in raw_dir.glob("incoming-*") if raw_dir.exists() else ():
            partial.unlink(missing_ok=True)
        if upload_session.get("status") == "promoting":
            project_id = upload_session.get("project_id")
            try:
                project = store.project(project_id)
            except (FileNotFoundError, OSError, ValueError, TypeError):
                try:
                    orphan = store.project_dir(project_id)
                except (FileNotFoundError, TypeError):
                    orphan = None
                if orphan is not None:
                    shutil.rmtree(orphan, ignore_errors=True)
                store.update_upload_session(
                    upload_session["session_id"], status="ready_for_brief", project_id=None,
                )
            else:
                if not project.get("promotion_initialized"):
                    store.delete_project(project_id)
                    store.update_upload_session(
                        upload_session["session_id"], status="ready_for_brief", project_id=None,
                    )
                else:
                    _finalize_upload_promotion(upload_session["session_id"], project_id)
            continue
        if upload_session.get("status") == "promoted":
            if (
                upload_session.get("files")
                or upload_session.get("inspection_metadata")
                or upload_session.get("name")
                or upload_session.get("style_id")
                or upload_session.get("provider")
                or upload_session.get("prompt")
                or upload_session.get("intent_interpretation")
                or upload_session.get("recipe_match")
                or upload_session.get("target_duration_seconds")
                or upload_session.get("draft_id")
                or raw_dir.exists()
            ):
                _finalize_upload_promotion(
                    upload_session["session_id"], upload_session.get("project_id"),
                )
            continue
        if upload_session.get("status") != "inspecting":
            continue
        store.update_upload_session(
            upload_session["session_id"], status="uploading",
            inspection_interrupted_at=utc_now(),
        )


recover_interrupted_jobs()


def has_active_demo_work() -> bool:
    """Conservatively keep PBJ awake while any durable or OS-level work is active."""
    if active_media_process_count():
        return True
    if any(item.get("status") in ACTIVE_JOB_STATES for item in store.list_projects()):
        return True
    if any(item.get("status") in ACTIVE_STYLE_JOB_STATES for item in store.list_styles()):
        return True
    return any(
        item.get("status") in {"inspecting", "promoting"}
        for item in store.list_records(store.upload_sessions_dir, "manifest.json")
    )


demo_activity = DemoActivityTracker()
demo_lifecycle = DemoLifecycleManager(
    enabled=settings.demo_lifecycle_enabled,
    controller_url=settings.demo_controller_url,
    control_token=settings.demo_control_token,
    idle_seconds=settings.demo_idle_seconds,
    tracker=demo_activity,
    has_active_work=has_active_demo_work,
)


async def start_application_runtime() -> None:
    start_media_process_runtime()
    demo_lifecycle.start()


async def shutdown_application_runtime() -> None:
    await demo_lifecycle.stop()
    shutdown_media_process_runtime()


app.router.add_event_handler("startup", start_application_runtime)
app.router.add_event_handler("shutdown", shutdown_application_runtime)


PUBLIC_PATHS = {"/access", "/manifest.webmanifest", "/ui.css", "/health"}
INTERNAL_AUTH_PATHS = {"/internal/demo/can-suspend"}


def device_id(request: Request) -> str:
    if settings.shared_workspace:
        # A deliberately single-user hosted demo: every authorized browser
        # shares one permission boundary without introducing user accounts.
        request.session["device_id"] = settings.shared_workspace_id
        return settings.shared_workspace_id
    value = request.session.get("device_id")
    if not value:
        value = "device-" + os.urandom(12).hex()
        request.session["device_id"] = value
    return value


def is_owner(request: Request) -> bool:
    return bool(request.session.get("owner"))


def require_owner(request: Request) -> None:
    if not is_owner(request):
        raise HTTPException(403, "Owner access is required for this action.")


CLIENT_DIAGNOSTIC_EVENTS = {
    "page_loaded", "files_selected", "session_started", "upload_started",
    "upload_progress", "upload_retry", "upload_completed", "batch_check_started",
    "batch_completed", "upload_failed", "visibility_hidden", "visibility_visible",
    "network_offline", "network_online", "client_error",
}
CLIENT_DIAGNOSTIC_STAGES = {
    "upload_resume", "footage_picker", "file_upload", "session_created",
    "media_inspection", "batch", "footage_page", "unknown",
}
CLIENT_DIAGNOSTIC_CONNECTIONS = {
    "slow-2g", "2g", "3g", "4g", "wifi", "ethernet", "cellular", "unknown",
}
CLIENT_DIAGNOSTIC_ERRORS = {
    "xhr_network", "connection_interrupted", "batch_interrupted",
    "window_error", "unhandled_rejection",
}


def bounded_diagnostic_int(value, minimum: int = 0, maximum: int = 2_147_483_648):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(minimum, min(maximum, int(value)))


def diagnostic_choice(value, allowed, fallback=None):
    token = str(value or "").strip().casefold()
    return token if token in allowed else fallback


@app.post("/diagnostics/client", status_code=204)
async def record_client_diagnostic(request: Request):
    try:
        payload = await request.json()
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid diagnostic event")
    if not isinstance(payload, dict) or payload.get("event") not in CLIENT_DIAGNOSTIC_EVENTS:
        raise HTTPException(400, "Invalid diagnostic event")
    session_id = str(payload.get("upload_session_id") or "")
    if session_id and (not ID_PATTERN.fullmatch(session_id) or not session_id.startswith("upload-")):
        session_id = ""
    if session_id:
        try:
            upload_session = store.upload_session(session_id)
        except (FileNotFoundError, OSError, ValueError):
            session_id = ""
        else:
            if upload_session.get("device_id") != device_id(request):
                session_id = ""
    error_code = str(payload.get("error_code") or "").strip().casefold()
    if error_code not in CLIENT_DIAGNOSTIC_ERRORS and not re.fullmatch(r"http_[1-5][0-9]{2}", error_code):
        error_code = None
    event = {
        "schema_version": "1.0",
        "event_id": new_id("event"),
        "recorded_at": utc_now(),
        "event": payload["event"],
        "upload_session_id": session_id or None,
        "stage": diagnostic_choice(payload.get("stage"), CLIENT_DIAGNOSTIC_STAGES, "unknown"),
        "file_index": bounded_diagnostic_int(payload.get("file_index"), 1, 1000),
        "total_files": bounded_diagnostic_int(payload.get("total_files"), 1, 1000),
        "file_size_bytes": bounded_diagnostic_int(payload.get("file_size_bytes")),
        "loaded_bytes": bounded_diagnostic_int(payload.get("loaded_bytes")),
        "percent": bounded_diagnostic_int(payload.get("percent"), 0, 100),
        "attempt": bounded_diagnostic_int(payload.get("attempt"), 0, 10),
        "online": payload.get("online") if isinstance(payload.get("online"), bool) else None,
        "visibility": diagnostic_choice(payload.get("visibility"), {"visible", "hidden", "prerender"}),
        "connection_type": diagnostic_choice(payload.get("connection_type"), CLIENT_DIAGNOSTIC_CONNECTIONS),
        "error_code": error_code,
        "viewport_width": bounded_diagnostic_int(payload.get("viewport_width"), 1, 10000),
        "viewport_height": bounded_diagnostic_int(payload.get("viewport_height"), 1, 10000),
    }
    with diagnostic_log_lock:
        rate_key = device_id(request)
        now = time.monotonic()
        window_started, event_count = diagnostic_rate_windows.get(rate_key, (now, 0))
        if now - window_started >= 60:
            window_started, event_count = now, 0
        if event_count >= 240:
            raise HTTPException(429, "Diagnostic event rate exceeded")
        diagnostic_rate_windows[rate_key] = (window_started, event_count + 1)
        store.append_client_diagnostic(event)
    # The same allowlisted record goes to stdout so Render retains useful evidence
    # even when its ephemeral filesystem is cleared by a crash or restart.
    client_diagnostic_logger.warning("PBJ_CLIENT_DIAGNOSTIC %s", json.dumps(event, separators=(",", ":")))
    return Response(status_code=204)


@app.get("/diagnostics/download")
async def download_client_diagnostics(request: Request):
    require_owner(request)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(store.diagnostics_dir.glob("client-events*.jsonl")):
            archive.write(path, "pbj-diagnostics/" + path.name)
        archive.writestr("pbj-diagnostics/README.txt", "Privacy-safe PBJ client operational events. Filenames, media, prompts, secrets, and raw exception messages are excluded.\n")
    return Response(
        content=buffer.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="pbj-client-diagnostics.zip"'},
    )


def visible_projects(request: Request):
    current = device_id(request)
    return [item for item in store.list_projects()
            if item.get("device_id") == current or (not item.get("device_id") and is_owner(request))]


def upload_temp_dir(prefix: str) -> Path:
    """Create request-scoped upload staging in PBJ's configured data area."""
    parent = settings.data_dir / "tmp"
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=parent))


async def cache_bounded_access_form_body(request: Request) -> Response | None:
    """Read a login form incrementally and replay it to the route parser."""
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        if not re.fullmatch(r"[0-9]+", declared_length):
            return Response("Invalid Content-Length.", status_code=400)
        significant_length = declared_length.lstrip("0") or "0"
        limit_text = str(ACCESS_FORM_MAX_BYTES)
        if (
            len(significant_length) > len(limit_text)
            or (
                len(significant_length) == len(limit_text)
                and significant_length > limit_text
            )
        ):
            return Response("Request body is too large.", status_code=413)

    body = bytearray()
    async for chunk in request.stream():
        if len(chunk) > ACCESS_FORM_MAX_BYTES - len(body):
            return Response("Request body is too large.", status_code=413)
        body.extend(chunk)
    # BaseHTTPMiddleware replays a cached body to the downstream Request. This
    # keeps FastAPI's normal form parsing intact without ever reading an
    # unbounded access-code submission into memory.
    request._body = bytes(body)
    return None


@app.middleware("http")
async def private_beta_access(request: Request, call_next):
    path = request.url.path
    if path in INTERNAL_AUTH_PATHS:
        # These routes authenticate their fixed server-to-server bearer token;
        # browser Origin metadata is neither present nor sufficient.
        return await call_next(request)
    if not same_origin(request, hosted=settings.hosted_mode):
        return Response("Cross-site request blocked.", status_code=403)
    if request.method == "POST" and path in {"/access", "/owner-access"}:
        rejection = await cache_bounded_access_form_body(request)
        if rejection is not None:
            return rejection
    if path.startswith("/static/") or path in PUBLIC_PATHS:
        return await call_next(request)
    if not settings.access_code:
        device_id(request)
    elif not request.session.get("authorized"):
        if path != "/access":
            return RedirectResponse("/access", status_code=303)
    # Device ownership is enforced for every project page, action, and output.
    match = re.match(r"^/(?:api/)?projects/(project-[0-9]{8}-[a-f0-9]{6})(?:/|$)", path)
    if match:
        try:
            project = store.project(match.group(1))
        except (FileNotFoundError, OSError, ValueError):
            return Response(status_code=404)
        if project.get("device_id") != device_id(request) and not (not project.get("device_id") and is_owner(request)):
            return Response(status_code=404)
    style_match = re.match(r"^/styles/(style-[0-9]{8}-[a-f0-9]{6})(?:/|$)", path)
    if style_match:
        try:
            style = store.style(style_match.group(1))
        except (FileNotFoundError, OSError, ValueError):
            return Response(status_code=404)
        if style.get("project_private") and style.get("device_id") != device_id(request):
            return Response(status_code=404)
    demo_activity.request_started()
    try:
        return await call_next(request)
    finally:
        demo_activity.request_finished()


app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=settings.session_days * 24 * 60 * 60,
    same_site="lax",
    https_only=settings.https_only,
)


@app.middleware("http")
async def security_response_headers(request: Request, call_next):
    response = await call_next(request)
    return apply_security_headers(
        response, path=request.url.path, hosted=settings.hosted_mode,
    )


@app.exception_handler(Exception)
async def unhandled_server_error(request: Request, exc: Exception):
    """Return a privacy-safe 500 with the same browser defenses as other responses."""
    server_error_logger.error(
        "PBJ_SERVER_ERROR error_type=%s", type(exc).__name__,
    )
    response = Response("Internal Server Error", status_code=500)
    return apply_security_headers(
        response, path=request.url.path, hosted=settings.hosted_mode,
    )


@app.get("/manifest.webmanifest", include_in_schema=False)
async def web_manifest():
    return FileResponse(settings.static_dir / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/ui.css", include_in_schema=False)
async def ui_styles(request: Request):
    """Serve the versioned UI bundle without rereading five files per request."""
    headers = {"Cache-Control": "public, max-age=3600", "ETag": UI_CSS_ETAG}
    if request.headers.get("if-none-match") == UI_CSS_ETAG:
        return Response(status_code=304, headers=headers)
    return Response(content=UI_CSS_CONTENT, media_type="text/css", headers=headers)


def target_seconds_from_prompt(prompt: str, default: int = 60) -> int:
    """Honor an explicit duration in the user's creative brief; otherwise use the product default."""
    text = (prompt or "").lower()
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(seconds?|secs?|s)\b", text)
    if match:
        seconds = round(float(match.group(1)))
    else:
        match = re.search(r"\b(\d+(?:\.\d+)?)\s*(minutes?|mins?|m)\b", text)
        seconds = round(float(match.group(1)) * 60) if match else default
    return max(15, min(180, int(seconds)))


def readiness():
    providers = {name: cls().readiness().__dict__ for name, cls in PROVIDERS.items()}
    return {
        "ffmpeg": ffmpeg_status(),
        "features": {},
        "providers": providers,
        "openai": {
            "configured": bool(os.getenv("OPENAI_API_KEY")),
            "message": "Ready" if os.getenv("OPENAI_API_KEY") else "Add OPENAI_API_KEY to .env",
            "agents": {
                "editing": {"model": settings.editing_agent_model, "reasoning_effort": settings.agent_reasoning_effort},
                "repair": {"model": settings.repair_agent_model, "reasoning_effort": settings.agent_reasoning_effort},
                "learning": {"model": settings.learning_agent_model, "reasoning_effort": settings.agent_reasoning_effort},
            },
        },
    }


def analyzer_provider() -> str:
    """Return the sole analyzer used by the production workflow."""
    return "pegasus"


def login_client_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return client_fingerprint(host, settings.session_secret)


def access_rate_limited(request: Request, retry_after: int):
    return templates.TemplateResponse(
        request, "access.html", {"error": False, "rate_limited": True},
        status_code=429, headers={"Retry-After": str(retry_after)},
    )


@app.get("/access", response_class=HTMLResponse)
async def access_page(request: Request, error: bool = False, rate_limited: bool = False):
    if request.session.get("authorized"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "access.html", {"error": error, "rate_limited": rate_limited},
    )


@app.post("/access")
async def unlock_beta(request: Request, code: str = Form(...)):
    client_key = login_client_key(request)
    retry_after = login_rate_limiter.retry_after(client_key, "access")
    if retry_after:
        return access_rate_limited(request, retry_after)
    access_match = exact_secret_match(code, settings.access_code)
    owner_match = exact_secret_match(code, settings.owner_code)
    if access_match or owner_match:
        saved_device = request.session.get("device_id") if not settings.shared_workspace else None
        request.session.clear()
        if saved_device:
            request.session["device_id"] = saved_device
        request.session["authorized"] = True
        request.session["owner"] = owner_match
        device_id(request)
        login_rate_limiter.record_success(client_key, "access")
        return RedirectResponse("/", status_code=303)
    retry_after = login_rate_limiter.record_failure(client_key, "access")
    if retry_after:
        return access_rate_limited(request, retry_after)
    return RedirectResponse("/access?error=true", status_code=303)


@app.post("/owner-access")
async def unlock_owner(request: Request, code: str = Form(...)):
    client_key = login_client_key(request)
    retry_after = login_rate_limiter.retry_after(client_key, "owner")
    if retry_after:
        return templates.TemplateResponse(
            request, "more.html", {"owner_state": "rate_limited"},
            status_code=429, headers={"Retry-After": str(retry_after)},
        )
    if exact_secret_match(code, settings.owner_code):
        request.session["owner"] = True
        login_rate_limiter.record_success(client_key, "owner")
        return RedirectResponse("/more?owner=unlocked", status_code=303)
    retry_after = login_rate_limiter.record_failure(client_key, "owner")
    if retry_after:
        return templates.TemplateResponse(
            request, "more.html", {"owner_state": "rate_limited"},
            status_code=429, headers={"Retry-After": str(retry_after)},
        )
    return RedirectResponse("/more?owner=invalid", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    saved_device = request.session.get("device_id") if not settings.shared_workspace else None
    request.session.clear()
    if saved_device:
        request.session["device_id"] = saved_device
    return RedirectResponse("/access" if settings.access_code else "/", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request, approved: bool = False, message: str = "", remote_cleanup: str = "",
):
    return templates.TemplateResponse(request, "welcome.html", {
        "style_deleted": message == "style-deleted",
        "remote_cleanup_warning": (
            message == "style-deleted" and remote_cleanup == "unavailable"
        ),
    })


@app.get("/projects", response_class=HTMLResponse)
async def projects_dashboard(
    request: Request, message: str = "", remote_cleanup: str = "",
):
    return templates.TemplateResponse(request, "dashboard.html", {
        "projects": visible_projects(request),
        "project_deleted": message == "deleted",
        "remote_cleanup_warning": (
            message == "deleted" and remote_cleanup == "unavailable"
        ),
    })


@app.get("/more", response_class=HTMLResponse)
async def more_page(request: Request, owner: str = ""):
    return templates.TemplateResponse(request, "more.html", {"owner_state": owner})


@app.get("/styles", response_class=HTMLResponse)
async def styles_library(request: Request):
    styles = [item for item in store.list_styles() if not item.get("system_default") and not item.get("project_private")]
    return templates.TemplateResponse(request, "styles_library.html", {"styles": styles})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False):
    require_owner(request)
    return templates.TemplateResponse(request, "settings.html", {
        "readiness": readiness(), "saved": saved, "hosted_mode": settings.hosted_mode,
    })


@app.post("/settings")
async def update_settings(request: Request, openai_key: str = Form(""), twelve_labs_key: str = Form("")):
    require_owner(request)
    if settings.hosted_mode:
        raise HTTPException(403, "Hosted connections are managed securely in Render.")
    save_api_keys({"OPENAI_API_KEY": openai_key, "TWELVE_LABS_API_KEY": twelve_labs_key})
    return RedirectResponse("/settings?saved=true", status_code=303)


@app.get("/assets", response_class=HTMLResponse)
async def remote_assets_page(request: Request, message: str = ""):
    require_owner(request)
    assets = store.remote_assets()
    cleanup_tombstones = [{
        "recorded_at": item.get("recorded_at"),
        "local_context": item.get("local_context"),
        "status": item.get("status"),
    } for item in store.remote_cleanup_tombstones()]
    return templates.TemplateResponse(request, "assets.html", {
        "assets": assets,
        "cleanup_tombstones": cleanup_tombstones,
        "message": message,
        "total_asset_records": len(assets) + len(cleanup_tombstones),
        "retained_asset_count": (
            sum(1 for asset in assets if asset.get("retained"))
            + len(cleanup_tombstones)
        ),
    })


async def cleanup_remote_asset(owner_type: str, owner_id: str, provider: str, asset_id: str) -> bool:
    """Delete through a current provider, or truthfully mark retired cleanup unavailable."""
    provider_type = provider_for_name(provider)
    if provider_type is None:
        store.mark_remote_asset_cleanup_unavailable(owner_type, owner_id, provider, asset_id)
        return False
    await provider_type().delete_asset(asset_id)
    store.mark_remote_asset_deleted(owner_type, owner_id, provider, asset_id)
    return True


@app.post("/assets/delete")
async def delete_remote_asset(request: Request, owner_type: str = Form(...), owner_id: str = Form(...),
                              provider: str = Form(...), asset_id: str = Form(...)):
    require_owner(request)
    if owner_type not in ("style", "project"):
        raise HTTPException(400, "Invalid remote asset")
    match = next((item for item in store.remote_assets() if item.get("owner_type") == owner_type and item.get("owner_id") == owner_id and item.get("provider") == provider and item.get("id") == asset_id), None)
    if not match:
        raise HTTPException(404, "Remote asset not found")
    if match.get("status") == "deleted":
        return RedirectResponse("/assets?message=already-deleted", status_code=303)
    try:
        deleted = await cleanup_remote_asset(owner_type, owner_id, provider, asset_id)
    except Exception:
        raise HTTPException(502, "The provider could not delete this asset. Try again later.")
    if not deleted:
        raise HTTPException(
            409,
            "PBJ no longer supports that provider, so remote deletion could not be verified. Local files were not changed.",
        )
    return RedirectResponse("/assets?message=deleted", status_code=303)


@app.get("/styles/new", response_class=HTMLResponse)
async def new_style(request: Request, next: str = ""):
    return templates.TemplateResponse(request, "style_new.html", {"next_action": next})


@app.post("/styles")
async def create_style(
    request: Request, label: str = Form(""), references: List[UploadFile] = File(...),
    next_action: str = Form(""), contribution_consent: bool = Form(False),
):
    if not contribution_consent:
        raise HTTPException(400, "Confirm that these videos may be used as a shared Recipe Lab contribution.")
    if not 1 <= len(references) <= 5:
        raise HTTPException(400, "Upload between 1 and 5 reference videos.")
    temp_dir = upload_temp_dir("pbj-recipe-references-")
    paths = []
    batch_bytes = 0
    try:
        for index, upload in enumerate(references, start=1):
            suffix = Path(upload.filename or "").suffix.lower()
            if suffix not in VIDEO_EXTENSIONS:
                raise HTTPException(400, "Unsupported video file: %s" % upload.filename)
            target = temp_dir / ("%03d-%s" % (index, safe_name(upload.filename or "reference.mp4")))
            with target.open("wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    batch_bytes += len(chunk)
                    if batch_bytes > settings.max_upload_batch_bytes:
                        raise HTTPException(413, "Reference videos must fit within the 2 GB batch limit.")
                    output.write(chunk)
            paths.append(target)
        metadata = {str(path): await asyncio.to_thread(inspect_video, path) for path in paths}
        total = sum(item.get("duration_seconds") or 0 for item in metadata.values())
        if total > 30 * 60:
            raise HTTPException(400, "Reference videos must total 30 minutes or less.")
        profile = store.create_style(label, paths, metadata)
        profile = store.update_style(
            profile["style_id"],
            next_action="project" if next_action == "project" else "",
            created_by_device_id=device_id(request),
            recipe_ownership="platform" if is_owner(request) else "contributor_candidate",
            recipe_visibility="internal" if is_owner(request) else "shared_candidate",
            contribution_consent={
                "confirmed": True,
                "confirmed_at": utc_now(),
                "device_id": device_id(request),
                "scope": "shared_recipe_evidence",
            },
        )
        store.save_learning_signal(profile["style_id"], {
            "source_key": "reference-upload:%s" % profile["style_id"],
            "type": "reference_upload", "scope": "style_evidence",
            "reference_file_ids": [item["file_id"] for item in profile.get("reference_files", [])],
            "file_count": len(profile.get("reference_files", [])), "status": "context",
            "instruction": "Reference upload recorded; it becomes recipe evidence only after successful timestamped analysis and synthesis.",
        })
        return RedirectResponse("/styles/%s" % profile["style_id"], status_code=303)
    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)


@app.get("/styles/{style_id}", response_class=HTMLResponse)
async def style_detail(request: Request, style_id: str):
    try:
        profile = store.style(style_id)
    except FileNotFoundError:
        raise HTTPException(404, "Style not found")
    status = profile.get("status")
    if status in ("analysis_queued", "analyzing_references", "revision_queued", "revising_style"):
        destination = "progress"
    elif profile.get("style_analysis"):
        destination = "review"
    else:
        destination = "analysis"
    return RedirectResponse("/styles/%s/%s" % (style_id, destination), status_code=303)


def style_context(request: Request, style_id: str, *, include_learning: bool = False):
    try:
        profile = store.style(style_id)
    except FileNotFoundError:
        raise HTTPException(404, "Style not found")
    context = {"request": request, "style": profile}
    if include_learning:
        context["learning_state"] = store.learning_state(style_id)
    return context


@app.get("/styles/{style_id}/analysis", response_class=HTMLResponse)
async def style_analysis_page(request: Request, style_id: str):
    return templates.TemplateResponse(request, "style_analysis.html", style_context(request, style_id))


@app.get("/styles/{style_id}/progress", response_class=HTMLResponse)
async def style_progress_page(request: Request, style_id: str):
    context = style_context(request, style_id)
    profile = context["style"]
    if profile.get("status") not in ("analysis_queued", "analyzing_references", "revision_queued", "revising_style"):
        return RedirectResponse("/styles/%s" % style_id, status_code=303)
    return templates.TemplateResponse(request, "style_progress.html", context)


@app.get("/styles/{style_id}/review", response_class=HTMLResponse)
async def style_review_page(request: Request, style_id: str):
    context = style_context(request, style_id, include_learning=True)
    if not context["style"].get("style_analysis"):
        return RedirectResponse("/styles/%s/analysis" % style_id, status_code=303)
    return templates.TemplateResponse(request, "style_review.html", context)


@app.post("/styles/{style_id}/delete")
async def delete_style(request: Request, style_id: str):
    require_owner(request)
    try:
        profile = store.begin_style_deletion(
            style_id, reject_statuses=ACTIVE_STYLE_JOB_STATES,
        )
    except FileNotFoundError:
        raise HTTPException(404, "Style not found")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    cleanup_unavailable = []
    try:
        for asset in [item for item in store.remote_assets() if item.get("owner_type") == "style" and item.get("owner_id") == style_id and item.get("status") != "deleted"]:
            deleted = await cleanup_remote_asset(
                "style", style_id, asset.get("provider"), asset.get("id"),
            )
            if not deleted:
                cleanup_unavailable.append(asset)
        for asset in cleanup_unavailable:
            store.record_remote_cleanup_tombstone(
                "style", style_id, asset.get("provider"), asset.get("id"),
                local_context="style_archive",
            )
        store.delete_style(profile["style_id"])
    except BaseException as exc:
        try:
            store.restore_style_deletion(
                style_id,
                "The recipe was kept because its remote analysis cleanup did not finish. Try again later.",
            )
        except Exception:
            pass
        if not isinstance(exc, Exception):
            raise
        raise HTTPException(
            502,
            "The style was kept because its remote analysis copy could not be deleted. Try again later.",
        )
    suffix = "&remote_cleanup=unavailable" if cleanup_unavailable else ""
    return RedirectResponse("/?message=style-deleted" + suffix, status_code=303)


async def _run_style_analysis(style_id: str, provider: str) -> None:
    try:
        await StyleWorkflow(store).analyze(style_id, [provider], refresh=False)
    except Exception:
        # StyleWorkflow records a bounded, user-safe failure on the style. The
        # background task must not reference unrelated project/editor state.
        return


@app.post("/styles/{style_id}/analyze")
async def analyze_style(style_id: str, background_tasks: BackgroundTasks):
    try:
        profile = store.style(style_id)
    except FileNotFoundError:
        raise HTTPException(404, "Style not found")
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(400, "Connect OpenAI before building an editing recipe")
    provider = analyzer_provider()
    if not PROVIDERS[provider]().readiness().configured:
        raise HTTPException(400, "Add the %s API key to .env" % provider.title())
    try:
        store.transition_style(
            style_id, reject_statuses=ACTIVE_STYLE_JOB_STATES,
            status="analysis_queued", last_error=None, active_started_at=utc_now(),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    background_tasks.add_task(_run_style_analysis, style_id, provider)
    return RedirectResponse("/styles/%s/progress" % style_id, status_code=303)


@app.post("/styles/{style_id}/approve")
async def approve_style(request: Request, style_id: str):
    try:
        profile = store.style(style_id)
    except FileNotFoundError:
        raise HTTPException(404, "Recipe not found")
    if not profile.get("project_private"):
        require_owner(request)
    try:
        StyleWorkflow(store).approve(style_id)
    except FileNotFoundError:
        raise HTTPException(404, "Style not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    profile = store.style(style_id)
    if not profile.get("project_private"):
        profile = store.update_style(style_id, recipe_ownership="platform", recipe_visibility="internal")
    if profile.get("next_action") == "project":
        return RedirectResponse("/projects/new/footage?style_id=%s" % style_id, status_code=303)
    return RedirectResponse("/styles/%s/review" % style_id, status_code=303)


async def _run_style_revision(style_id: str, feedback: str) -> None:
    try:
        await StyleWorkflow(store).revise(style_id, feedback)
    except Exception:
        return


@app.post("/styles/{style_id}/revise")
async def revise_style(request: Request, style_id: str, background_tasks: BackgroundTasks, feedback: str = Form(...)):
    try:
        profile = store.style(style_id)
    except FileNotFoundError:
        raise HTTPException(404, "Style not found")
    if not profile.get("project_private"):
        require_owner(request)
    if not profile.get("style_analysis"):
        raise HTTPException(400, "Analyze this style before revising it")
    if not feedback.strip():
        raise HTTPException(400, "Describe what should change")
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(400, "Add OPENAI_API_KEY before revising the style")
    try:
        store.transition_style(
            style_id, reject_statuses=ACTIVE_STYLE_JOB_STATES,
            status="revision_queued", last_error=None, active_started_at=utc_now(),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    background_tasks.add_task(_run_style_revision, style_id, feedback.strip())
    return RedirectResponse("/styles/%s/progress" % style_id, status_code=303)


def ensured_project_draft(request: Request, *, create: bool = False) -> dict:
    """Return a browser-owned draft with a stable identity for upload binding."""
    value = request.session.get("project_draft")
    draft = dict(value) if isinstance(value, dict) else {}
    if not draft and not create:
        return {}
    if not draft.get("draft_id"):
        draft["draft_id"] = new_id("draft")
        request.session["project_draft"] = draft
    return draft


@app.get("/projects/new", response_class=HTMLResponse)
async def new_project(request: Request):
    draft = ensured_project_draft(request, create=True)
    return templates.TemplateResponse(request, "project_describe.html", {"draft": draft})


@app.post("/projects/new/fresh")
async def start_fresh_project(request: Request):
    """Begin a distinct draft through a same-origin-protected mutation."""
    request.session.pop("project_draft", None)
    request.session.pop("active_upload_session_id", None)
    return RedirectResponse("/projects/new", status_code=303)


@app.post("/projects/new/describe")
async def save_project_description(request: Request, name: str = Form(""), description: str = Form(...)):
    if len(name) > PROJECT_NAME_MAX_CHARS:
        raise HTTPException(400, "The project name is too long.")
    if len(description) > PROJECT_DESCRIPTION_MAX_CHARS:
        raise HTTPException(400, "The description is too long for this private demo.")
    clean_name = name.strip()
    clean_description = description.strip()
    if not clean_description:
        raise HTTPException(400, "Describe the video you want to create.")
    draft = ensured_project_draft(request, create=True)
    project_draft = {
        "draft_id": draft["draft_id"],
        "name": clean_name,
        "description": clean_description,
        "style_id": "",
    }
    prospective_session = dict(request.session)
    prospective_session["project_draft"] = project_draft
    serialized_session = json.dumps(prospective_session, ensure_ascii=True).encode("utf-8")
    if len(serialized_session) > PROJECT_SESSION_JSON_MAX_BYTES:
        raise HTTPException(
            400, "The description is too long for this private demo. Shorten it and try again.",
        )
    request.session["project_draft"] = project_draft
    return RedirectResponse("/projects/new/references", status_code=303)


@app.get("/projects/new/references", response_class=HTMLResponse)
async def project_references_page(request: Request):
    draft = request.session.get("project_draft")
    if not draft or not draft.get("description"):
        return RedirectResponse("/projects/new", status_code=303)
    return templates.TemplateResponse(request, "project_references.html", {"draft": draft})


async def _run_project_reference_analysis(style_id: str, provider: str) -> None:
    try:
        await StyleWorkflow(store).analyze(style_id, [provider], refresh=False)
        StyleWorkflow(store).approve(style_id)
    except Exception:
        return


@app.post("/projects/new/references")
async def save_project_references(
    request: Request, background_tasks: BackgroundTasks,
    references: List[UploadFile] | None = File(None), skip: bool = Form(False),
):
    draft = request.session.get("project_draft")
    if not draft or not draft.get("description"):
        return RedirectResponse("/projects/new", status_code=303)
    references = references or []
    if skip:
        draft["style_id"] = ""
        request.session["project_draft"] = draft
        return RedirectResponse("/projects/new/footage", status_code=303)
    references = [item for item in references if item.filename]
    if not references:
        return templates.TemplateResponse(
            request,
            "project_references.html",
            {
                "draft": draft,
                "error": "The video was not attached. Choose it again and wait until its filename appears before tapping Use Example.",
            },
            status_code=400,
        )
    if not 1 <= len(references) <= 5:
        raise HTTPException(400, "Choose up to five finished reference videos.")
    temp_dir = upload_temp_dir("pbj-project-references-")
    paths = []
    batch_bytes = 0
    try:
        for index, upload in enumerate(references, start=1):
            suffix = Path(upload.filename or "").suffix.lower()
            if suffix not in VIDEO_EXTENSIONS:
                raise HTTPException(400, "Unsupported reference video: %s" % upload.filename)
            target = temp_dir / ("%03d-%s" % (index, safe_name(upload.filename or "reference.mp4")))
            with target.open("wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    batch_bytes += len(chunk)
                    if batch_bytes > settings.max_upload_batch_bytes:
                        raise HTTPException(413, "Reference videos must fit within the 2 GB batch limit.")
                    output.write(chunk)
            paths.append(target)
        metadata = {str(path): await asyncio.to_thread(inspect_video, path) for path in paths}
        total = sum(item.get("duration_seconds") or 0 for item in metadata.values())
        if total > 30 * 60:
            raise HTTPException(400, "Reference videos must total 30 minutes or less.")
        profile = store.create_style("Private project references", paths, metadata)
        store.update_style(profile["style_id"], project_private=True, device_id=device_id(request))
        store.save_learning_signal(profile["style_id"], {
            "source_key": "reference-upload:%s" % profile["style_id"],
            "type": "reference_upload", "scope": "project_only",
            "reference_file_ids": [item["file_id"] for item in profile.get("reference_files", [])],
            "file_count": len(profile.get("reference_files", [])), "status": "context",
            "instruction": "Private project references uploaded; they become project recipe evidence only after successful analysis and synthesis.",
        })
        draft["style_id"] = profile["style_id"]
        request.session["project_draft"] = draft
        provider_status = readiness()["providers"]
        provider = analyzer_provider()
        if not provider_status.get(provider, {}).get("configured"):
            raise HTTPException(400, "Video understanding is not configured. Open More, then Connections.")
        store.transition_style(
            profile["style_id"], reject_statuses=ACTIVE_STYLE_JOB_STATES,
            status="analysis_queued", last_error=None, active_started_at=utc_now(),
        )
        background_tasks.add_task(_run_project_reference_analysis, profile["style_id"], provider)
        return RedirectResponse("/projects/new/references-progress", status_code=303)
    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)


@app.get("/projects/new/references-progress", response_class=HTMLResponse)
async def project_references_progress(request: Request):
    draft = request.session.get("project_draft") or {}
    style_id = draft.get("style_id")
    if not style_id:
        return RedirectResponse("/projects/new/references", status_code=303)
    try:
        style = store.style(style_id)
    except FileNotFoundError:
        return RedirectResponse("/projects/new/references", status_code=303)
    if style.get("approval", {}).get("approved"):
        return RedirectResponse("/projects/new/footage", status_code=303)
    return templates.TemplateResponse(request, "project_references_progress.html", {"style": style})


@app.post("/projects/new/references-retry")
async def retry_project_reference_analysis(request: Request, background_tasks: BackgroundTasks):
    draft = request.session.get("project_draft") or {}
    style_id = draft.get("style_id")
    if not style_id:
        return RedirectResponse("/projects/new/references", status_code=303)
    try:
        style = store.style(style_id)
    except FileNotFoundError:
        return RedirectResponse("/projects/new/references", status_code=303)
    provider = analyzer_provider()
    if not PROVIDERS[provider]().readiness().configured or not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(400, "Connect video understanding and OpenAI before trying again")
    try:
        store.transition_style(
            style_id, reject_statuses=ACTIVE_STYLE_JOB_STATES,
            status="analysis_queued", last_error=None, last_error_details=None,
            active_started_at=utc_now(),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    background_tasks.add_task(_run_project_reference_analysis, style_id, provider)
    return RedirectResponse("/projects/new/references-progress", status_code=303)


@app.get("/projects/new/saved-style", response_class=HTMLResponse)
async def choose_saved_style(request: Request):
    # Recipe selection is internal infrastructure. Keep old bookmarks from
    # reopening the retired recipe-first project flow.
    return RedirectResponse("/projects/new", status_code=303)


def engine_decides_style() -> dict:
    existing = next((item for item in store.list_styles() if item.get("system_default")), None)
    if existing:
        return existing
    profile = store.create_style("Editing engine decides", [], {})
    recipe = {
        "summary": "Use the project brief and available footage to make coherent editorial decisions.",
        "creative_principles": ["Prioritize clarity, strong moments, coherent story, and technically reliable edits."],
        "structure_summary": "Build the clearest story supported by the supplied footage.",
        "compatibility": ["General fallback when no reference evidence is supplied."],
        "avoid": ["Do not invent unavailable media or unsupported facts."],
        "rules": [], "unsupported_observations": [], "uncertainties": [],
    }
    draft = store.save_recipe_draft(profile["style_id"], recipe, "1.0.0")
    store.update_style(
        profile["style_id"], system_default=True, recipe=draft,
        recipe_version="1.0.0", recipe_status="testing", style_analysis=draft,
    )
    return store.approve_recipe_version(profile["style_id"])


def upload_session_matches_draft(upload_session: dict, draft: dict, style_id: str = "") -> bool:
    """Only resume staging that was created for this exact project draft."""
    session_draft_id = upload_session.get("draft_id")
    if session_draft_id and session_draft_id != draft.get("draft_id"):
        return False
    if (upload_session.get("name") or "") != (draft.get("name") or "").strip():
        return False
    if (upload_session.get("prompt") or "") != (draft.get("description") or "").strip():
        return False
    return not style_id or upload_session.get("style_id") == style_id


@app.get("/projects/new/engine-decides")
async def choose_engine_decides():
    return RedirectResponse("/projects/new", status_code=303)


@app.get("/projects/new/footage", response_class=HTMLResponse)
async def project_footage_page(request: Request, style_id: str = "", session_id: str = ""):
    draft = ensured_project_draft(request)
    if not draft or not draft.get("description"):
        return RedirectResponse("/projects/new", status_code=303)
    requested_style_id = style_id
    style_id = style_id or draft.get("style_id", "")
    style = None
    if style_id:
        try:
            style = store.style(style_id)
        except FileNotFoundError:
            raise HTTPException(404, "Reference direction not found")
        if style.get("project_private") and style.get("device_id") != device_id(request):
            raise HTTPException(404, "Reference direction not found")
        if not style.get("approval", {}).get("approved"):
            return RedirectResponse("/projects/new/references-progress", status_code=303)
        if requested_style_id and draft.get("style_id") != requested_style_id:
            # Preserve the saved-link compatibility route that carries an
            # explicitly approved recipe into the prompt-first footage step.
            draft["style_id"] = requested_style_id
            request.session["project_draft"] = draft
    uploaded_session = None
    active_session_id = request.session.get("active_upload_session_id", "")
    session_id = session_id or active_session_id
    if session_id:
        try:
            uploaded_session = store.upload_session(session_id)
        except (FileNotFoundError, OSError, ValueError):
            request.session.pop("active_upload_session_id", None)
            uploaded_session = None
        if uploaded_session and uploaded_session.get("device_id") != device_id(request):
            raise HTTPException(404, "Upload session not found")
        if uploaded_session and (
            uploaded_session.get("status") in {"promoting", "promoted"}
            or not upload_session_matches_draft(uploaded_session, draft, style_id)
        ):
            # A completed project or a newly described project must never pick
            # up staging from an older draft merely because its cookie remains.
            if active_session_id == session_id:
                request.session.pop("active_upload_session_id", None)
            uploaded_session = None
        elif uploaded_session and not uploaded_session.get("draft_id"):
            # One-time compatibility binding for a pre-audit session whose exact
            # stored fields match the browser's current draft.
            uploaded_session = store.update_upload_session(
                session_id, draft_id=draft["draft_id"],
            )
    return templates.TemplateResponse(request, "project_footage.html", {
        "style": style, "draft": draft, "uploaded_session": uploaded_session,
    })


@app.post("/projects/upload-session")
async def start_upload_session(request: Request, name: str = Form(""), style_id: str = Form(""),
                               prompt: str = Form(""), target_seconds: int = Form(60)):
    draft = ensured_project_draft(request)
    if (
        not draft.get("description")
        or name.strip() != (draft.get("name") or "").strip()
        or prompt.strip() != draft["description"].strip()
        or style_id != (draft.get("style_id") or "")
    ):
        raise HTTPException(409, "This project draft changed. Return to the first step and try again.")
    provider = analyzer_provider()
    engine_decides_style()
    target_seconds = target_seconds_from_prompt(prompt, target_seconds)
    intent = interpret_brief(prompt, target_seconds)
    candidates = [
        item for item in store.list_styles()
        if not item.get("project_private")
        or (
            item.get("style_id") == style_id
            and item.get("device_id") == device_id(request)
        )
    ]
    try:
        recipe_match = match_recipe(intent, candidates, style_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    selected_style_id = recipe_match["selected_recipe_id"]
    session = store.create_upload_session(
        name, selected_style_id, provider, prompt, target_seconds, intent, recipe_match, device_id(request),
        draft_id=draft["draft_id"],
    )
    request.session["active_upload_session_id"] = session["session_id"]
    return {"session_id": session["session_id"], "uploaded_files": 0}


@app.post("/projects/upload-session/{session_id}/file")
async def upload_session_file(request: Request, session_id: str):
    try:
        session = store.upload_session(session_id)
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "Upload session not found. Start the upload again.")
    if session.get("device_id") != device_id(request):
        raise HTTPException(404, "Upload session not found. Start the upload again.")
    if session.get("status") != "uploading":
        raise HTTPException(409, "This upload batch is already being checked.")
    encoded_filename = request.headers.get("x-pbj-filename", "")
    try:
        original_name = unquote(encoded_filename, errors="strict")
    except UnicodeDecodeError:
        raise HTTPException(400, "The video filename is invalid.")
    if not original_name or len(original_name) > 1024:
        raise HTTPException(400, "A video filename is required.")
    suffix = Path(original_name).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise HTTPException(400, "Unsupported video file type.")
    safe_filename = safe_name(original_name)
    upload_id = request.headers.get("x-pbj-upload-id", "").strip()
    if upload_id and not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", upload_id):
        raise HTTPException(400, "The upload identifier is invalid.")
    content_length = request.headers.get("content-length")
    declared_bytes = None
    if content_length:
        try:
            declared_bytes = int(content_length)
        except ValueError:
            raise HTTPException(400, "The upload size is invalid.")
        if declared_bytes < 0:
            raise HTTPException(400, "The upload size is invalid.")
    # Reserve capacity before reading the body. Two desktop uploads may arrive
    # together; without a reservation, each can independently believe the full
    # remaining 2 GB is available and temporarily exhaust ephemeral storage.
    with upload_manifest_lock:
        session = store.upload_session(session_id)
        if session.get("device_id") != device_id(request):
            raise HTTPException(404, "Upload session not found. Start the upload again.")
        if session.get("status") != "uploading":
            raise HTTPException(409, "This upload batch is already being checked.")
        if upload_id:
            previously_saved = next(
                (item for item in session.get("files", []) if item.get("upload_id") == upload_id),
                None,
            )
            if previously_saved:
                if (
                    previously_saved.get("original_name") != original_name
                    or (declared_bytes is not None and previously_saved.get("size_bytes") != declared_bytes)
                ):
                    raise HTTPException(409, "This upload identifier was already used for another video.")
                return {
                    "file_id": previously_saved["file_id"],
                    "filename": previously_saved["original_name"],
                    "size_bytes": previously_saved["size_bytes"],
                    "uploaded_files": len(session["files"]),
                }
        existing_bytes = sum(item.get("size_bytes", 0) for item in session.get("files", []))
        already_reserved = upload_reserved_bytes.get(session_id, 0)
        available_bytes = settings.max_upload_batch_bytes - existing_bytes - already_reserved
        reservation_bytes = available_bytes if declared_bytes is None else declared_bytes
        if reservation_bytes < 0 or reservation_bytes > available_bytes:
            raise HTTPException(413, "This batch is larger than 2 GB. Upload fewer videos at a time.")
        upload_reserved_bytes[session_id] = already_reserved + reservation_bytes
    target = None
    final_target = None
    manifest_committed = False
    try:
        raw_dir = store.upload_session_dir(session_id) / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        target = raw_dir / ("incoming-%s-%s" % (os.urandom(6).hex(), safe_filename))
        written = 0
        digest = hashlib.sha256()
        pending = bytearray()
        with target.open("wb") as output:
            async for chunk in request.stream():
                if not chunk:
                    continue
                written += len(chunk)
                if written > reservation_bytes:
                    raise HTTPException(413, "This upload is larger than the 2 GB batch limit.")
                digest.update(chunk)
                # ASGI servers may yield many small network chunks. Batch them
                # before crossing into the file-writing thread so a large upload
                # does not schedule tens of thousands of tiny executor jobs.
                view = memoryview(chunk)
                while view:
                    if not pending and len(view) >= UPLOAD_WRITE_BUFFER_BYTES:
                        await asyncio.to_thread(
                            output.write, view[:UPLOAD_WRITE_BUFFER_BYTES],
                        )
                        view = view[UPLOAD_WRITE_BUFFER_BYTES:]
                        continue
                    take = min(UPLOAD_WRITE_BUFFER_BYTES - len(pending), len(view))
                    pending.extend(view[:take])
                    view = view[take:]
                    if len(pending) == UPLOAD_WRITE_BUFFER_BYTES:
                        await asyncio.to_thread(output.write, bytes(pending))
                        pending.clear()
            if pending:
                await asyncio.to_thread(output.write, bytes(pending))
        if written == 0:
            raise HTTPException(400, "The uploaded video is empty.")
        # Finalize the short manifest update as one critical section. Desktop may
        # upload two files concurrently; without this lock, both completions could
        # claim the same next slot and overwrite one another.
        with upload_manifest_lock:
            session = store.upload_session(session_id)
            if session.get("status") != "uploading":
                raise HTTPException(409, "This upload batch is already being checked.")
            checksum = digest.hexdigest()
            duplicate = next(
                (item for item in session.get("files", [])
                 if item.get("original_name") == original_name
                 and item.get("size_bytes") == target.stat().st_size
                 and item.get("sha256") == checksum),
                None,
            )
            current_bytes = sum(item.get("size_bytes", 0) for item in session.get("files", []))
            if not duplicate and current_bytes + target.stat().st_size > settings.max_upload_batch_bytes:
                raise HTTPException(413, "This batch is larger than 2 GB. Upload fewer videos at a time.")
            if duplicate:
                target.unlink(missing_ok=True)
                record = dict(duplicate)
                if upload_id and record.get("upload_id") != upload_id:
                    record["upload_id"] = upload_id
                    files = [record if item.get("file_id") == record["file_id"] else item
                             for item in session.get("files", [])]
                    session = store.update_upload_session(session_id, files=files)
                    manifest_committed = True
            else:
                occupied_indices = [
                    int(match.group(1))
                    for item in session.get("files", [])
                    if (match := re.fullmatch(r"raw-(\d+)", item.get("file_id", "")))
                ]
                occupied_indices.extend(
                    int(match.group(1))
                    for path in raw_dir.iterdir()
                    if (match := re.match(r"(\d+)-", path.name))
                )
                index = max(occupied_indices, default=0) + 1
                final_target = raw_dir / ("%03d-%s" % (index, safe_filename))
                target.replace(final_target)
                record = {
                    "file_id": "raw-%03d" % index,
                    "original_name": original_name,
                    "stored_path": str(final_target.relative_to(store.data_dir)),
                    "size_bytes": final_target.stat().st_size,
                    "sha256": checksum,
                }
                if upload_id:
                    record["upload_id"] = upload_id
                session = store.update_upload_session(session_id, files=session.get("files", []) + [record])
                manifest_committed = True
        return {"file_id": record["file_id"], "filename": record["original_name"], "size_bytes": record["size_bytes"], "uploaded_files": len(session["files"])}
    except BaseException:
        if target is not None:
            target.unlink(missing_ok=True)
        if final_target is not None and not manifest_committed:
            final_target.unlink(missing_ok=True)
        raise
    finally:
        with upload_manifest_lock:
            remaining_reservation = upload_reserved_bytes.get(session_id, 0) - reservation_bytes
            if remaining_reservation > 0:
                upload_reserved_bytes[session_id] = remaining_reservation
            else:
                upload_reserved_bytes.pop(session_id, None)


@app.post("/projects/upload-session/{session_id}/complete")
async def complete_upload_session(request: Request, session_id: str):
    with upload_manifest_lock:
        try:
            session = store.upload_session(session_id)
        except (FileNotFoundError, OSError, ValueError):
            raise HTTPException(404, "Upload session not found. Start the upload again.")
        if session.get("device_id") != device_id(request):
            raise HTTPException(404, "Upload session not found. Start the upload again.")
        if session.get("status") == "ready_for_brief":
            return {"session_id": session_id}
        if session.get("status") != "uploading":
            raise HTTPException(409, "This upload batch is already being checked.")
        if upload_reserved_bytes.get(session_id, 0) > 0:
            raise HTTPException(409, "Wait for the current video upload to finish.")
        if sum(item.get("size_bytes", 0) for item in session.get("files", [])) > settings.max_upload_batch_bytes:
            raise HTTPException(413, "This batch is larger than 2 GB. Upload fewer videos at a time.")
        if not session.get("files"):
            raise HTTPException(400, "Choose at least one video before continuing.")
        session = store.update_upload_session(session_id, status="inspecting")
    paths = [store.resolve_data_path(item["stored_path"]) for item in session["files"]]
    inspection_limit = asyncio.Semaphore(2)

    async def inspect_one(path):
        async with inspection_limit:
            details = await asyncio.get_running_loop().run_in_executor(
                inspection_executor, inspect_video, path,
            )
            return path, details

    try:
        inspected = await asyncio.gather(*(inspect_one(path) for path in paths))
        metadata = {str(path): details for path, details in inspected}
        failed_paths = [path for path, details in inspected if details.get("inspection_error")]
        if failed_paths:
            failed_path_names = {str(path) for path in failed_paths}
            remaining_files = [
                item for item in session["files"]
                if str(store.resolve_data_path(item["stored_path"])) not in failed_path_names
            ]
            # Commit the retryable manifest first. A failed filesystem cleanup
            # can leave only an unreferenced staging file, never a poisoned batch.
            store.update_upload_session(
                session_id, files=remaining_files, inspection_metadata={},
                total_duration_seconds=0, status="uploading",
            )
            staging_root = (store.upload_session_dir(session_id) / "raw").resolve()
            for path in failed_paths:
                try:
                    if staging_root in path.resolve().parents:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
            failed_count = len(failed_paths)
            remaining_count = len(remaining_files)
            if remaining_count:
                message = (
                    "PBJ removed %d video%s it could not read. Your other %d video%s "
                    "remain%s saved; choose %s and try again."
                    % (
                        failed_count, "" if failed_count == 1 else "s",
                        remaining_count, "" if remaining_count == 1 else "s",
                        "s" if remaining_count == 1 else "",
                        "a replacement" if failed_count == 1 else "replacements",
                    )
                )
            else:
                message = "PBJ removed the video%s it could not read. Choose %s and try again." % (
                    "" if failed_count == 1 else "s",
                    "a replacement" if failed_count == 1 else "replacements",
                )
            raise HTTPException(400, message)
        total = sum(item.get("duration_seconds") or 0 for item in metadata.values())
        if total > 60 * 60:
            raise HTTPException(400, "Raw footage must total 60 minutes or less for this workspace.")
        store.update_upload_session(
            session_id, inspection_metadata=metadata, total_duration_seconds=round(total, 3), status="ready_for_brief",
        )
        return {"session_id": session_id}
    except BaseException:
        store.update_upload_session(session_id, status="uploading")
        raise


@app.get("/projects/new/brief", response_class=HTMLResponse)
async def new_project_brief_page(request: Request, session_id: str):
    try:
        session = store.upload_session(session_id)
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "Upload session not found")
    if session.get("device_id") != device_id(request):
        raise HTTPException(404, "Upload session not found")
    if session.get("status") in {"promoting", "promoted"} and session.get("project_id"):
        try:
            project = store.project(session["project_id"])
        except (FileNotFoundError, OSError, ValueError):
            if session.get("status") == "promoting":
                raise HTTPException(409, "This project is already being created.")
        else:
            if session.get("status") == "promoting" and not project.get("promotion_initialized"):
                raise HTTPException(409, "This project is already being created.")
            _finalize_upload_promotion(session_id, session["project_id"])
            return RedirectResponse("/projects/%s" % session["project_id"], status_code=303)
    if session.get("status") != "ready_for_brief":
        raise HTTPException(404, "Upload session not found")
    draft = request.session.get("project_draft") or {}
    return templates.TemplateResponse(request, "project_new_brief.html", {"upload_session": session, "draft": draft})


@app.post("/projects/new/brief")
async def finish_new_project(
    request: Request, background_tasks: BackgroundTasks,
    session_id: str = Form(...), specifics: str = Form(""),
):
    try:
        session = store.upload_session(session_id)
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "Upload session not found")
    if session.get("device_id") != device_id(request):
        raise HTTPException(404, "Upload session not found")
    if session.get("status") in {"promoting", "promoted"} and session.get("project_id"):
        project_id = session["project_id"]
        try:
            project = store.project(project_id)
        except (FileNotFoundError, OSError, ValueError):
            if session.get("status") == "promoting":
                raise HTTPException(409, "This project is already being created.")
        else:
            if session.get("status") == "promoting" and not project.get("promotion_initialized"):
                raise HTTPException(409, "This project is already being created.")
            _finalize_upload_promotion(session_id, project_id)
            request.session.pop("project_draft", None)
            request.session.pop("active_upload_session_id", None)
            return RedirectResponse("/projects/%s/production-progress" % project_id, status_code=303)
    if session.get("status") != "ready_for_brief":
        raise HTTPException(409, "This project is already being created.")
    if not readiness_for_provider(session.get("provider")).configured:
        raise HTTPException(400, "Video understanding is not configured. Open More, then Connections.")
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(400, "The editing engine is not configured. Open More, then Connections.")
    initial = (session.get("prompt") or "").strip()
    additional = specifics.strip()
    combined = initial + (("\n\nProject-specific requirements:\n" + additional) if additional else "")
    target_seconds = target_seconds_from_prompt(combined)
    intent = interpret_brief(combined, target_seconds)
    style_id = session.get("style_id", "")
    candidates = [
        item for item in store.list_styles()
        if not item.get("project_private")
        or (
            item.get("style_id") == style_id
            and item.get("device_id") == device_id(request)
        )
    ]
    try:
        recipe_match = match_recipe(intent, candidates, style_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    selected_style_id = recipe_match["selected_recipe_id"]
    with upload_manifest_lock:
        session = store.upload_session(session_id)
        if session.get("device_id") != device_id(request):
            raise HTTPException(404, "Upload session not found")
        if session.get("status") == "promoted" and session.get("project_id"):
            return RedirectResponse(
                "/projects/%s/production-progress" % session["project_id"], status_code=303,
            )
        if session.get("status") != "ready_for_brief":
            raise HTTPException(409, "This project is already being created.")
        project_id = new_id("project")
        session = store.update_upload_session(
            session_id, status="promoting", project_id=project_id,
        )
    paths = [store.resolve_data_path(item["stored_path"]) for item in session["files"]]
    metadata = session.get("inspection_metadata", {})
    source_checksums = {
        str(path): item.get("sha256", "") for path, item in zip(paths, session["files"])
    }
    source_original_names = {
        str(path): item.get("original_name") or path.name
        for path, item in zip(paths, session["files"])
    }
    try:
        project = await asyncio.to_thread(
            store.create_project,
            session["name"], selected_style_id, session["provider"], combined, target_seconds,
            paths, metadata,
            intent=intent, recipe_match=recipe_match, device_id=session.get("device_id"),
            source_checksums=source_checksums, reuse_staged_files=True,
            project_id_override=project_id, source_original_names=source_original_names,
        )
    except Exception:
        with upload_manifest_lock:
            current = store.upload_session(session_id)
            if current.get("status") == "promoting" and current.get("project_id") == project_id:
                store.update_upload_session(
                    session_id, status="ready_for_brief", project_id=None,
                )
        raise
    try:
        store.update_project(project["project_id"], initial_prompt=initial, additional_prompt=additional)
        store.update_project(
            project["project_id"], status="analysis_queued", last_error=None, active_revision=1,
            active_task="Understanding your footage", active_started_at=utc_now(),
            promotion_initialized=True,
        )
    except Exception:
        store.delete_project(project["project_id"])
        with upload_manifest_lock:
            store.update_upload_session(
                session_id, status="ready_for_brief", project_id=None,
            )
        raise
    # Commit the durable pointer before attaching in-process work to the HTTP
    # response. If that commit fails, the initialized project remains a safe,
    # retryable source of truth and is never falsely shown as still running.
    try:
        with upload_manifest_lock:
            _finalize_upload_promotion(session_id, project_id)
    except Exception as exc:
        store.update_project(
            project_id, status="analysis_failed", active_revision=None,
            active_task=None, **failure_fields(exc),
        )
        raise
    try:
        store.save_learning_signal(selected_style_id, {
            "source_key": "raw:%s" % project["project_id"],
            "type": "raw_footage_upload", "scope": "project_only",
            "project_id": project["project_id"], "file_count": len(paths),
            "device_id": project.get("device_id"),
            "total_duration_seconds": session.get("total_duration_seconds", 0), "status": "context",
            "instruction": "Project footage inventory; use only for compatibility and outcome analysis, not as a shared style rule.",
        })
        background_tasks.add_task(_run_complete_production, project["project_id"])
    except Exception as exc:
        store.update_project(
            project_id, status="analysis_failed", active_revision=None,
            active_task=None, **failure_fields(exc),
        )
        raise
    request.session.pop("project_draft", None)
    request.session.pop("active_upload_session_id", None)
    return RedirectResponse("/projects/%s/production-progress" % project["project_id"], status_code=303)


@app.post("/projects")
async def create_project(
    request: Request, name: str = Form(""), style_id: str = Form(""),
    prompt: str = Form(""), target_seconds: int = Form(60),
    footage: List[UploadFile] = File(...),
):
    provider = analyzer_provider()
    target_seconds = target_seconds_from_prompt(prompt, target_seconds)
    if not 15 <= target_seconds <= 180:
        raise HTTPException(400, "Target duration must be between 15 and 180 seconds.")
    engine_decides_style()
    intent = interpret_brief(prompt, target_seconds)
    candidates = [
        item for item in store.list_styles()
        if not item.get("project_private")
        or (
            item.get("style_id") == style_id
            and item.get("device_id") == device_id(request)
        )
    ]
    try:
        recipe_match = match_recipe(intent, candidates, style_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    style_id = recipe_match["selected_recipe_id"]
    temp_dir = upload_temp_dir("pbj-project-footage-")
    paths = []
    source_checksums = {}
    batch_bytes = 0
    try:
        for index, upload in enumerate(footage, start=1):
            suffix = Path(upload.filename or "").suffix.lower()
            if suffix not in VIDEO_EXTENSIONS:
                raise HTTPException(400, "Unsupported video file: %s" % upload.filename)
            target = temp_dir / ("%03d-%s" % (index, safe_name(upload.filename or "raw.mp4")))
            with target.open("wb") as output:
                digest = hashlib.sha256()
                while chunk := await upload.read(1024 * 1024):
                    batch_bytes += len(chunk)
                    if batch_bytes > settings.max_upload_batch_bytes:
                        raise HTTPException(413, "This batch is larger than 2 GB. Upload fewer videos at a time.")
                    digest.update(chunk)
                    await asyncio.to_thread(output.write, chunk)
            paths.append(target)
            source_checksums[str(target)] = digest.hexdigest()
        metadata = {str(path): await asyncio.to_thread(inspect_video, path) for path in paths}
        total = sum(item.get("duration_seconds") or 0 for item in metadata.values())
        if total > 60 * 60:
            raise HTTPException(400, "Raw footage must total 60 minutes or less for this workspace.")
        project = await asyncio.to_thread(
            store.create_project, name, style_id, provider, prompt, target_seconds,
            paths, metadata, intent, recipe_match, device_id(request), source_checksums, True,
        )
        store.save_learning_signal(style_id, {
            "source_key": "raw:%s" % project["project_id"],
            "type": "raw_footage_upload", "scope": "project_only",
            "project_id": project["project_id"], "file_count": len(paths),
            "device_id": project.get("device_id"),
            "total_duration_seconds": round(total, 3), "status": "context",
            "instruction": "Project footage inventory; use only for compatibility and outcome analysis, not as a shared style rule.",
        })
        return RedirectResponse("/projects/%s/brief" % project["project_id"], status_code=303)
    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str):
    try:
        project = store.project(project_id)
        style = store.style(project["style_id"])
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    status = project.get("status")
    if status in ("export_queued", "exporting") and project.get("active_export_id"):
        return RedirectResponse("/projects/%s/exports/%s/progress" % (project_id, project["active_export_id"]), status_code=303)
    if status in ("analysis_failed", "rough_cut_failed", "timeline_failed", "export_failed"):
        destination = "production-progress"
    elif status in ("timeline_ready", "approved"):
        destination = "ready"
    elif status in ("timeline_queued", "planning_timeline"):
        destination = "production-progress"
    elif status in ("analysis_queued", "analyzing_footage"):
        destination = "production-progress"
    elif status in ("rough_cut_queued", "planning_rough_cut", "rendering_rough_cut"):
        destination = "production-progress"
    elif status == "approval_running":
        destination = "ready"
    elif project.get("latest_run"):
        destination = "review"
    elif status == "footage_uploaded":
        destination = "brief"
    elif project.get("content_map"):
        # Historical projects may have stopped in the retired analyzer-first
        # wizard. Bring them into the same creative-brief step as every new
        # project instead of reopening that old flow.
        destination = "brief"
    else:
        destination = "brief"
    return RedirectResponse("/projects/%s/%s" % (project_id, destination), status_code=303)


@app.post("/projects/{project_id}/delete")
async def delete_project(request: Request, project_id: str):
    try:
        project = store.project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    if project.get("device_id") != device_id(request) and not (not project.get("device_id") and is_owner(request)):
        raise HTTPException(404, "Project not found")
    try:
        project = store.transition_project(
            project_id,
            reject_statuses=ACTIVE_JOB_STATES,
            status="project_deleting",
            deletion_return_status=project.get("status") or "timeline_ready",
            active_task="Deleting this project",
            active_started_at=utc_now(),
            last_error=None,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    cleanup_unavailable = []
    try:
        for asset in [item for item in store.remote_assets() if item.get("owner_type") == "project" and item.get("owner_id") == project_id and item.get("status") != "deleted"]:
            deleted = await cleanup_remote_asset(
                "project", project_id, asset.get("provider"), asset.get("id"),
            )
            if not deleted:
                cleanup_unavailable.append(asset)
        for asset in cleanup_unavailable:
            store.record_remote_cleanup_tombstone(
                "project", project_id, asset.get("provider"), asset.get("id"),
                local_context="project_deletion",
            )
        store.delete_project(project_id)
    except BaseException as exc:
        try:
            return_status = project.get("deletion_return_status") or "timeline_ready"
            store.transition_project(
                project_id, require_statuses={"project_deleting"},
                status=return_status,
                deletion_return_status=None,
                active_task=None,
                active_started_at=None,
                last_error=(
                    "The project was kept because remote analysis cleanup did not finish. "
                    "Try deleting it again later."
                ),
                last_error_details={
                    "type": "DeletionCleanupError",
                    "code": "project_deletion_cleanup_failed",
                    "message": "Remote cleanup did not finish, so local project files were kept.",
                    "recorded_at": utc_now(),
                },
            )
        except Exception:
            pass
        if not isinstance(exc, Exception):
            raise
        raise HTTPException(
            502,
            "The project was kept because its remote analysis copy could not be deleted. Try again later.",
        )
    suffix = "&remote_cleanup=unavailable" if cleanup_unavailable else ""
    return RedirectResponse("/projects?message=deleted" + suffix, status_code=303)


def project_context(request: Request, project_id: str):
    try:
        project = store.project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    return {"request": request, "project": project}


@app.get("/projects/{project_id}/brief", response_class=HTMLResponse)
async def project_brief_page(request: Request, project_id: str):
    return templates.TemplateResponse(request, "project_brief.html", project_context(request, project_id))


async def _run_complete_production(project_id: str) -> None:
    try:
        await ProjectAnalysisWorkflow(store).analyze(project_id, refresh=False)
        await TimelinePreparationWorkflow(store).create(project_id)
        timeline = TimelineStore(store).load(project_id)
        export = TimelineExportService(store).create(
            project_id, timeline["timeline_hash"],
            approve_on_success=False, approval_confirmation=False,
        )
        await asyncio.get_running_loop().run_in_executor(
            render_executor, TimelineExportService(store).run, project_id, export["export_id"],
        )
    except Exception as exc:
        current = store.project(project_id)
        if current.get("status") not in {"analysis_failed", "timeline_failed", "export_failed"}:
            store.update_project(
                project_id, status="export_failed", active_export_id=None, active_task=None,
                **failure_fields(exc),
            )


async def _run_revision(project_id: str, feedback: str) -> None:
    try:
        await TimelinePreparationWorkflow(store).create(project_id, feedback=feedback)
        timeline = TimelineStore(store).load(project_id)
        export = TimelineExportService(store).create(
            project_id, timeline["timeline_hash"],
            approve_on_success=False, approval_confirmation=False,
            revision_prompt=feedback,
        )
        await asyncio.get_running_loop().run_in_executor(
            render_executor, TimelineExportService(store).run, project_id, export["export_id"],
        )
    except Exception as exc:
        current = store.project(project_id)
        if current.get("status") not in {"analysis_failed", "timeline_failed", "export_failed"}:
            store.update_project(
                project_id, status="export_failed", active_export_id=None, active_task=None,
                **failure_fields(exc),
            )


@app.post("/projects/{project_id}/brief")
async def save_project_brief(
    project_id: str, background_tasks: BackgroundTasks,
    prompt: str = Form(""), target_seconds: int = Form(60),
):
    try:
        project = store.project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    target_seconds = target_seconds_from_prompt(prompt)
    if not readiness_for_provider(project.get("provider")).configured:
        raise HTTPException(400, "Video understanding is not configured. Open Settings to connect it.")
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(400, "The editing engine is not configured. Open Settings to connect it.")
    try:
        store.transition_project(
            project_id, reject_statuses=ACTIVE_JOB_STATES,
            prompt=prompt.strip() or "Create the strongest coherent rough cut from the supplied footage.",
            target_duration_seconds=target_seconds, status="analysis_queued", last_error=None,
            active_revision=len(project.get("runs", [])) + 1, active_task="Understanding your footage",
            active_started_at=utc_now(),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    background_tasks.add_task(_run_complete_production, project_id)
    return RedirectResponse("/projects/%s/production-progress" % project_id, status_code=303)


@app.get("/projects/{project_id}/production-progress", response_class=HTMLResponse)
async def production_progress_page(request: Request, project_id: str):
    context = project_context(request, project_id)
    status = context["project"].get("status")
    if status not in ("analysis_queued", "analyzing_footage", "footage_analyzed", "rough_cut_queued", "planning_rough_cut", "rendering_rough_cut", "analysis_failed", "rough_cut_failed", "timeline_queued", "planning_timeline", "timeline_failed", "export_queued", "exporting", "export_failed"):
        return RedirectResponse("/projects/%s" % project_id, status_code=303)
    return templates.TemplateResponse(request, "production_progress.html", context)


def export_matches_current_timeline(project_id: str, export: dict) -> bool:
    """Require approval to follow the exact current working-timeline lineage."""
    if export.get("status") != "complete" or not export.get("timeline_path"):
        return False
    try:
        current = TimelineStore(store).load(project_id)
        snapshot = store.read_json(store.resolve_data_path(export["timeline_path"]))
    except (FileNotFoundError, OSError, ValueError, KeyError, json.JSONDecodeError):
        return False
    current_hash = current.get("timeline_hash")
    declared_hash = export.get("timeline_hash")
    return bool(
        current_hash
        and snapshot.get("timeline_hash") == current_hash
        and (not declared_hash or declared_hash == current_hash)
    )


@app.get("/projects/{project_id}/ready", response_class=HTMLResponse)
async def project_ready_page(request: Request, project_id: str):
    project = store.project(project_id)
    if not TimelineStore(store).exists(project_id):
        if project.get("latest_run"):
            migrate_legacy_project(store, project_id)
        else:
            return RedirectResponse("/projects/%s/production-progress" % project_id, status_code=303)
    cuts = TimelineExportService(store).records(project_id, completed_only=True)
    export = project.get("latest_export") or {}
    return templates.TemplateResponse(request, "project_ready.html", {
        "project": project, "export": export, "cuts": cuts,
        "cut_number": len(cuts),
        "can_approve": export_matches_current_timeline(project_id, export)
        and project.get("status") == "timeline_ready",
    })


@app.get("/projects/{project_id}/cuts", response_class=HTMLResponse)
async def project_cuts_page(request: Request, project_id: str):
    store.project(project_id)
    cuts = TimelineExportService(store).records(project_id, completed_only=True)
    if not cuts:
        return RedirectResponse("/projects/%s/ready" % project_id, status_code=303)
    return RedirectResponse(
        "/projects/%s/cuts/%s" % (project_id, cuts[-1]["export_id"]), status_code=303,
    )


@app.get("/projects/{project_id}/cuts/{export_id}", response_class=HTMLResponse)
async def project_cut_page(request: Request, project_id: str, export_id: str):
    project = store.project(project_id)
    cuts = TimelineExportService(store).records(project_id, completed_only=True)
    selected = next((cut for cut in cuts if cut.get("export_id") == export_id), None)
    if not selected:
        raise HTTPException(404, "Rough cut not found")
    cut_number = cuts.index(selected) + 1
    latest = bool(cuts and cuts[-1].get("export_id") == export_id)
    feedback_history = project.get("revision_feedback") or []
    if cut_number == 1:
        prompt_label = "Original creative brief"
        prompt = project.get("prompt") or "Create the strongest coherent rough cut from the supplied footage."
    else:
        prompt_label = "Revision prompt for Cut %d" % cut_number
        fallback = feedback_history[cut_number - 2].get("feedback") if len(feedback_history) >= cut_number - 1 else ""
        prompt = selected.get("revision_prompt") or fallback or "Revision details were not recorded for this historical cut."
    return templates.TemplateResponse(request, "project_cut.html", {
        "project": project, "export": selected, "cut_number": cut_number,
        "is_latest": latest, "prompt_label": prompt_label, "prompt": prompt,
        "previous_cut": cuts[cut_number - 2] if cut_number > 1 else None,
        "next_cut": cuts[cut_number] if cut_number < len(cuts) else None,
    })


async def _run_timeline_export(project_id: str, export_id: str) -> None:
    try:
        await asyncio.get_running_loop().run_in_executor(
            render_executor, TimelineExportService(store).run, project_id, export_id,
        )
    except Exception:
        return


@app.get("/projects/{project_id}/exports/{export_id}/progress", response_class=HTMLResponse)
async def timeline_export_progress(request: Request, project_id: str, export_id: str):
    try:
        export = TimelineExportService(store).record(project_id, export_id)
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "Export not found")
    if export.get("status") == "complete":
        return RedirectResponse("/projects/%s/exports/%s/complete" % (project_id, export_id), status_code=303)
    return templates.TemplateResponse(request, "timeline_export_progress.html", {
        "project": store.project(project_id), "export": export,
    })


@app.get("/projects/{project_id}/exports/{export_id}/complete", response_class=HTMLResponse)
async def timeline_export_complete(request: Request, project_id: str, export_id: str):
    try:
        export = TimelineExportService(store).record(project_id, export_id)
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "Export not found")
    if export.get("status") not in ("complete", "failed"):
        return RedirectResponse("/projects/%s/exports/%s/progress" % (project_id, export_id), status_code=303)
    return templates.TemplateResponse(request, "timeline_export_complete.html", {
        "project": store.project(project_id), "export": export,
    })


@app.get("/projects/{project_id}/exports/{export_id}/download")
async def download_timeline_export(project_id: str, export_id: str):
    try:
        export = TimelineExportService(store).record(project_id, export_id)
        path = store.resolve_data_path(export["output_path"])
    except (FileNotFoundError, OSError, ValueError, KeyError):
        raise HTTPException(404, "Export not found")
    if export.get("status") != "complete" or not path.exists():
        raise HTTPException(404, "Completed video is not available")
    return FileResponse(path, media_type="video/mp4", filename="%s-%s.mp4" % (project_id, export_id))


@app.get("/projects/{project_id}/analysis-data/download")
async def download_project_analysis_data(project_id: str):
    """Download project-owned provider evidence without exposing source media."""
    try:
        project = store.project(project_id)
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "Project not found")

    files = []
    project_analysis_root = store.project_dir(project_id) / "analyses"
    if project_analysis_root.exists():
        for path in sorted(project_analysis_root.glob("*/*.json")):
            files.append((path, "footage/%s/%s" % (path.parent.name, path.name)))

    content_map_path = store.project_dir(project_id) / "content_map.json"
    if content_map_path.exists():
        files.append((content_map_path, "content-map.json"))

    try:
        style = store.style(project["style_id"])
    except (FileNotFoundError, OSError, ValueError, KeyError):
        style = {}
    if style.get("project_private") and style.get("device_id") == project.get("device_id"):
        reference_root = store.style_dir(project["style_id"]) / "analyses"
        if reference_root.exists():
            for path in sorted(reference_root.glob("*/*.json")):
                files.append((path, "references/%s/%s" % (path.parent.name, path.name)))

    if not files:
        raise HTTPException(404, "No saved analysis data is available for this project")

    package = io.BytesIO()
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, archive_name in files:
            archive.write(path, archive_name)
        archive.writestr("package-manifest.json", json.dumps({
            "project_id": project_id,
            "created_at": utc_now(),
            "contents": [archive_name for _, archive_name in files],
        }, indent=2))
    filename = "%s-analysis-data.zip" % safe_name(project.get("name") or project_id)
    return Response(
        content=package.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="%s"' % filename},
    )


@app.get("/projects/{project_id}/analysis-results", response_class=HTMLResponse)
async def project_analysis_results_page(request: Request, project_id: str):
    try:
        project = store.project(project_id)
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "Project not found")
    names = {item.get("file_id"): item.get("original_name") for item in project.get("raw_files", [])}
    analyses = store.project_analyses(project_id, project.get("provider"))
    results = []
    for record in analyses:
        analysis = record.get("analysis") or {}
        results.append({
            "file_id": record.get("file_id"),
            "name": names.get(record.get("file_id")) or record.get("file_id") or "Uploaded video",
            "analysis": analysis,
            "duration_seconds": record.get("duration_seconds"),
            "model": record.get("model"),
            "completed_at": record.get("completed_at"),
            "cache_hit": bool((record.get("cache") or {}).get("hit")),
        })
    results.sort(key=lambda item: item["file_id"] or "")
    return templates.TemplateResponse(request, "project_analysis_results.html", {
        "project": project, "results": results,
        "segment_count": sum(len((item["analysis"].get("segments") or [])) for item in results),
    })


@app.get("/projects/{project_id}/analysis", response_class=HTMLResponse)
async def project_analysis_page(request: Request, project_id: str):
    return RedirectResponse("/projects/%s" % project_id, status_code=303)


@app.get("/projects/{project_id}/analysis-progress", response_class=HTMLResponse)
async def project_analysis_progress_page(request: Request, project_id: str):
    return RedirectResponse("/projects/%s/production-progress" % project_id, status_code=303)


@app.get("/projects/{project_id}/analysis-review", response_class=HTMLResponse)
async def project_analysis_review_page(request: Request, project_id: str):
    return RedirectResponse("/projects/%s/analysis-results" % project_id, status_code=303)


@app.get("/projects/{project_id}/rough-cut", response_class=HTMLResponse)
async def project_rough_cut_page(request: Request, project_id: str):
    return RedirectResponse("/projects/%s" % project_id, status_code=303)


@app.get("/projects/{project_id}/rough-cut-progress", response_class=HTMLResponse)
async def project_rough_cut_progress_page(request: Request, project_id: str):
    return RedirectResponse("/projects/%s/production-progress" % project_id, status_code=303)


@app.get("/projects/{project_id}/review", response_class=HTMLResponse)
async def project_review_page(request: Request, project_id: str):
    return RedirectResponse("/projects/%s/ready" % project_id, status_code=303)


@app.get("/projects/{project_id}/revision", response_class=HTMLResponse)
async def project_revision_page(request: Request, project_id: str):
    return RedirectResponse("/projects/%s/ready" % project_id, status_code=303)


@app.get("/projects/{project_id}/approval", response_class=HTMLResponse)
async def project_approval_page(request: Request, project_id: str):
    return RedirectResponse("/projects/%s/ready" % project_id, status_code=303)


def _approve_latest_project_export(project_id: str):
    """Make an explicit approval idempotent within the one-process demo."""
    with approval_lock:
        project = store.project(project_id)
        if project.get("status") in ACTIVE_JOB_STATES:
            raise ValueError("Wait for the current project task to finish before approving a cut")
        export = project.get("latest_export") or {}
        if export.get("status") != "complete":
            raise ValueError("A completed rough cut is required before approval")
        if not export_matches_current_timeline(project_id, export):
            raise ValueError("This cut is not the current saved edit. Review or finish the latest edit before approving.")
        try:
            receipt = store.read_json(store.resolve_data_path(export["render_receipt_path"]))
        except (FileNotFoundError, OSError, ValueError, KeyError, json.JSONDecodeError):
            raise ValueError("This cut is missing its completed verification receipt")
        if (receipt.get("verification") or {}).get("passed") is not True:
            raise ValueError("This cut did not pass required export verification")
        existing = project.get("final_approval") or {}
        if existing.get("approved") and existing.get("export_id") == export.get("export_id"):
            return existing
        begin_timeline_job(store, project_id, "approval_running", "Saving your approved cut")
        try:
            # Re-read after the atomic claim so a concurrent revision or legacy
            # mutation cannot approve an export that stopped being current.
            project = store.project(project_id)
            claimed_export = project.get("latest_export") or {}
            if claimed_export.get("export_id") != export.get("export_id"):
                raise ValueError("The latest cut changed; refresh before approving")
            if not export_matches_current_timeline(project_id, claimed_export):
                raise ValueError("This cut is not the current saved edit. Review or finish the latest edit before approving.")
            timeline = store.read_json(store.resolve_data_path(claimed_export["timeline_path"]))
            approval = approve_timeline_export(
                store, project_id, claimed_export, timeline, receipt,
            )
            claimed_export["approval"] = approval
            export_path = (
                store.project_dir(project_id) / "exports" /
                claimed_export["export_id"] / "export.json"
            )
            store.write_json(export_path, claimed_export)
            store.update_project(
                project_id,
                status="approved",
                latest_export=claimed_export,
                active_task=None,
                active_started_at=None,
                job_return_status=None,
            )
            return approval
        except Exception as exc:
            # The approval helper writes final_approval only after its durable
            # evidence. If that marker exists, preserve the completed approval
            # even if the final convenience pointer write was interrupted.
            current = store.project(project_id)
            saved = current.get("final_approval") or {}
            if saved.get("approved") and saved.get("export_id") == export.get("export_id"):
                store.update_project(
                    project_id,
                    status="approved",
                    active_task=None,
                    active_started_at=None,
                    job_return_status=None,
                )
                return saved
            fail_timeline_job(store, project_id, exc)
            raise


@app.post("/projects/{project_id}/approve")
async def approve_project_run(project_id: str, confirmation: str = Form("")):
    if confirmation != "approve":
        raise HTTPException(400, "Confirm that this finished cut is approved")
    try:
        await asyncio.to_thread(_approve_latest_project_export, project_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return RedirectResponse("/projects/%s/approval" % project_id, status_code=303)


@app.get("/examples", response_class=HTMLResponse)
async def approved_examples_page(request: Request):
    require_owner(request)
    return templates.TemplateResponse(request, "approved_examples.html", {"examples": store.list_approved_examples()})


@app.post("/projects/{project_id}/retry")
async def retry_failed_rough_cut(project_id: str, background_tasks: BackgroundTasks):
    try:
        project = store.project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    if project.get("status") == "analysis_failed":
        if not readiness_for_provider(project.get("provider")).configured:
            raise HTTPException(
                400,
                "This saved project uses video understanding that is no longer available. Create a new project to analyze with the current provider.",
            )
        try:
            store.transition_project(
                project_id, require_statuses={"analysis_failed"},
                status="analysis_queued", last_error=None, active_revision=1,
                active_task="Retrying footage analysis", active_started_at=utc_now(),
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        background_tasks.add_task(_run_complete_production, project_id)
        return RedirectResponse("/projects/%s/production-progress" % project_id, status_code=303)
    if project.get("status") in {"timeline_ready", "export_failed"} and TimelineStore(store).exists(project_id):
        timeline = TimelineStore(store).load(project_id)
        latest_run = project.get("latest_run") or {}
        plan_path = store.resolve_data_path(latest_run["plan_path"]) if latest_run.get("plan_path") else TimelineStore(store).root(project_id) / "initial_edit_plan.json"
        if plan_path.exists():
            plan = store.read_json(plan_path)
            rebuilt = timeline_from_edit_plan(project, plan)
            if rebuilt["timeline_hash"] != timeline["timeline_hash"]:
                timeline = TimelineStore(store).replace_with_ai_revision(
                    project_id, rebuilt, "Rebuilt saved cut with frame-safe timing",
                )
        export = TimelineExportService(store).create(
            project_id, timeline["timeline_hash"], approve_on_success=False,
            approval_confirmation=False,
        )
        background_tasks.add_task(_run_timeline_export, project_id, export["export_id"])
        return RedirectResponse("/projects/%s/production-progress" % project_id, status_code=303)
    if project.get("status") != "timeline_failed" or not project.get("content_map"):
        raise HTTPException(400, "Only failed timeline preparation can be retried here")
    try:
        store.transition_project(
            project_id, require_statuses={"timeline_failed"}, status="timeline_queued",
            last_error=None, active_task="Rebuilding the timeline from saved analysis",
            active_started_at=utc_now(),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    revision_feedback = project.get("pending_revision_feedback")
    if not isinstance(revision_feedback, str):
        revision_feedback = ""
    background_tasks.add_task(_run_revision, project_id, revision_feedback)
    return RedirectResponse("/projects/%s/production-progress" % project_id, status_code=303)


@app.post("/projects/{project_id}/revise")
async def revise_rough_cut(project_id: str, background_tasks: BackgroundTasks, feedback: str = Form(...), focus: List[str] = Form([])):
    feedback = feedback.strip()
    if not feedback:
        raise HTTPException(400, "Describe what you want changed")
    project = store.project(project_id)
    if not TimelineStore(store).exists(project_id) or not (project.get("latest_export") or {}).get("status") == "complete":
        raise HTTPException(409, "Finish the current rough cut before requesting changes")
    combined = feedback
    if focus:
        combined += "\nFocus areas: " + ", ".join(focus)
    history = project.get("revision_feedback", []) + [{"feedback": combined, "requested_at": utc_now()}]
    try:
        store.transition_project(
            project_id, reject_statuses=ACTIVE_JOB_STATES,
            status="timeline_queued", last_error=None,
            active_task="Replanning from your feedback", active_started_at=utc_now(),
            revision_feedback=history, pending_revision_feedback=combined,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    background_tasks.add_task(_run_revision, project_id, combined)
    return RedirectResponse("/projects/%s/production-progress" % project_id, status_code=303)


@app.get("/projects/{project_id}/output/{run_id}")
async def project_output(project_id: str, run_id: str):
    if not run_id.startswith("run-"):
        raise HTTPException(404, "Output not found")
    try:
        project = store.project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    run = next((item for item in project.get("runs", []) if item.get("run_id") == run_id), None)
    if not run:
        raise HTTPException(404, "Output not found")
    path = store.resolve_data_path(run["output_path"])
    if not path.exists():
        raise HTTPException(404, "Output file is missing")
    return FileResponse(path, media_type="video/mp4", filename="%s-%s.mp4" % (project_id, run_id))


@app.get("/api/readiness")
async def api_readiness():
    return readiness()


@app.post("/api/demo/activity", status_code=204, include_in_schema=False)
async def record_demo_activity():
    """Reset the idle timer only for an authorized, visible browser session."""
    demo_activity.touch()
    return Response(status_code=204)


@app.post("/internal/demo/can-suspend", include_in_schema=False)
async def confirm_demo_can_suspend(request: Request):
    authorization = request.headers.get("authorization", "")
    prefix = "Bearer "
    supplied = authorization[len(prefix):] if authorization.startswith(prefix) else ""
    if not settings.demo_lifecycle_enabled or not exact_secret_match(
        supplied, settings.demo_control_token,
    ):
        raise HTTPException(401, "Unauthorized.")
    idle_for, active_requests, _ = demo_activity.snapshot()
    allowed = (
        idle_for >= settings.demo_idle_seconds
        and active_requests == 0
        and not has_active_demo_work()
    )
    return {"allowed": allowed}


@app.get("/api/contracts")
async def api_contracts():
    return {"analysis": ANALYSIS_SCHEMA, "style_profile": STYLE_PROFILE_SCHEMA, "edit_plan": EDIT_PLAN_SCHEMA}


@app.get("/health")
async def health():
    return {"status": "ok"}
