from pathlib import Path
from typing import List
from datetime import datetime
import asyncio
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

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import save_api_keys, settings
from .contracts import ANALYSIS_SCHEMA, EDIT_PLAN_SCHEMA, STYLE_PROFILE_SCHEMA
from .editorial_intelligence import interpret_brief, match_recipe
from .media import ffmpeg_status, inspect_video
from .providers import PROVIDERS
from .storage import ID_PATTERN, JsonStore, VIDEO_EXTENSIONS, new_id, safe_name, utc_now
from .storage import sha256
from .timeline.contracts import us_from_seconds
from .workflows import ProjectAnalysisWorkflow, StyleWorkflow, TimelinePreparationWorkflow, failure_fields
from .timeline.migration import migrate_legacy_project, timeline_from_edit_plan
from .timeline.storage import StaleTimelineError, TimelineStore
from .timeline.proxies import ProxyPipeline
from .timeline.proposals import TimelineProposalService
from .timeline.export import TimelineExportService
from .timeline.lifecycle import ACTIVE_JOB_STATES, begin_timeline_job, fail_timeline_job, finish_timeline_job, mark_working_timeline_changed
from .timeline.learning import approve_timeline_export


app = FastAPI(title="PB&J Recipe Engine", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
templates = Jinja2Templates(directory=str(settings.templates_dir))
store = JsonStore(settings.data_dir)
upload_manifest_lock = Lock()
diagnostic_log_lock = Lock()
diagnostic_rate_windows = {}
client_diagnostic_logger = logging.getLogger("pbj.client_diagnostic")
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
        "preparing_proxies": "timeline_failed",
        "export_queued": "export_failed",
        "exporting": "export_failed",
    }
    for project in store.list_projects():
        status = project.get("status")
        if status not in project_states:
            continue
        interrupted = "This edit was interrupted when PBJ restarted. Your footage, timeline, and completed analysis are safe; try this step again."
        fallback = project.get("job_return_status")
        if fallback not in {"approved", "timeline_ready", "export_failed"}:
            fallback = project_states[status]
        if status in {"export_queued", "exporting"} and project.get("active_export_id"):
            export_path = (store.project_dir(project["project_id"]) / "exports" /
                           project["active_export_id"] / "export.json")
            if export_path.exists():
                export = store.read_json(export_path)
                export.update(status="failed", failed_at=utc_now(), error=interrupted)
                store.write_json(export_path, export)
        store.update_project(
            project["project_id"], status=fallback, active_revision=None,
            active_task=None, active_export_id=None, editor_read_only=False, last_error=interrupted,
            job_return_status=None,
            last_error_details={
                "type": "InterruptedJob",
                "message": "The in-process background job ended with the previous PBJ server process.",
                "recorded_at": utc_now(),
            },
        )


recover_interrupted_jobs()


PUBLIC_PATHS = {"/access", "/offline", "/manifest.webmanifest", "/service-worker.js", "/ui.css", "/health"}


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


def bounded_diagnostic_int(value, minimum: int = 0, maximum: int = 2_147_483_648):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(minimum, min(maximum, int(value)))


def bounded_diagnostic_token(value, maximum: int, fallback=None):
    raw = str(value or "").strip()
    if not raw:
        return fallback
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", raw)[:maximum] or fallback


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
    event = {
        "schema_version": "1.0",
        "event_id": new_id("event"),
        "recorded_at": utc_now(),
        "event": payload["event"],
        "upload_session_id": session_id or None,
        "stage": bounded_diagnostic_token(payload.get("stage"), 48, "unknown"),
        "file_index": bounded_diagnostic_int(payload.get("file_index"), 1, 1000),
        "total_files": bounded_diagnostic_int(payload.get("total_files"), 1, 1000),
        "file_size_bytes": bounded_diagnostic_int(payload.get("file_size_bytes")),
        "loaded_bytes": bounded_diagnostic_int(payload.get("loaded_bytes")),
        "percent": bounded_diagnostic_int(payload.get("percent"), 0, 100),
        "attempt": bounded_diagnostic_int(payload.get("attempt"), 0, 10),
        "online": payload.get("online") if isinstance(payload.get("online"), bool) else None,
        "visibility": str(payload.get("visibility") or "")[:16] or None,
        "connection_type": bounded_diagnostic_token(payload.get("connection_type"), 24),
        "error_code": bounded_diagnostic_token(payload.get("error_code"), 64),
        "client_recorded_at": str(payload.get("client_recorded_at") or "")[:40] or None,
        "user_agent": str(payload.get("user_agent") or "")[:240] or None,
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


@app.middleware("http")
async def private_beta_access(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static/") or path in PUBLIC_PATHS or not settings.access_code:
        device_id(request)
        return await call_next(request)
    if not request.session.get("authorized"):
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
    return await call_next(request)


app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=settings.session_days * 24 * 60 * 60,
    same_site="lax",
    https_only=os.getenv("PBJ_HTTPS_ONLY", "false").lower() == "true",
)


@app.get("/manifest.webmanifest", include_in_schema=False)
async def web_manifest():
    return FileResponse(settings.static_dir / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/ui.css", include_in_schema=False)
async def ui_styles():
    """Serve the complete UI outside the retired service-worker static cache."""
    names = ("app.css", "workflow.css", "mobile-v2.css", "troy-foundation.css", "troy-screens.css")
    content = "\n".join((settings.static_dir / name).read_text() for name in names)
    return Response(content=content, media_type="text/css", headers={"Cache-Control": "no-store"})


@app.get("/service-worker.js", include_in_schema=False)
async def service_worker():
    return FileResponse(
        settings.static_dir / "service-worker.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


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


def preferred_provider() -> str:
    """Choose the configured analyzer used by the normal provider-neutral flow."""
    provider_status = readiness()["providers"]
    if provider_status.get("pegasus", {}).get("configured"):
        return "pegasus"
    return "gemini"


@app.get("/access", response_class=HTMLResponse)
async def access_page(request: Request, error: bool = False):
    if request.session.get("authorized"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "access.html", {"error": error})


@app.post("/access")
async def unlock_beta(request: Request, code: str = Form(...)):
    supplied = code.strip().casefold()
    if supplied == settings.access_code.strip().casefold() or (settings.owner_code and supplied == settings.owner_code.strip().casefold()):
        request.session["authorized"] = True
        request.session["owner"] = bool(settings.owner_code and supplied == settings.owner_code.strip().casefold())
        device_id(request)
        return RedirectResponse("/", status_code=303)
    return RedirectResponse("/access?error=true", status_code=303)


@app.post("/owner-access")
async def unlock_owner(request: Request, code: str = Form(...)):
    if settings.owner_code and code.strip().casefold() == settings.owner_code.strip().casefold():
        request.session["owner"] = True
        return RedirectResponse("/more?owner=unlocked", status_code=303)
    return RedirectResponse("/more?owner=invalid", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, approved: bool = False):
    hour = datetime.now().hour
    greeting = "Good morning" if hour < 12 else ("Good afternoon" if hour < 18 else "Good evening")
    return templates.TemplateResponse(request, "welcome.html", {"projects": visible_projects(request)[:3], "greeting": greeting, "approved": approved})


@app.get("/projects", response_class=HTMLResponse)
async def projects_dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {
        "styles": store.list_styles(),
        "projects": visible_projects(request),
        "readiness": readiness(),
    })


@app.get("/more", response_class=HTMLResponse)
async def more_page(request: Request, owner: str = ""):
    return templates.TemplateResponse(request, "more.html", {"owner_state": owner, "readiness": readiness()})


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
async def update_settings(request: Request, openai_key: str = Form(""), gemini_key: str = Form(""), twelve_labs_key: str = Form("")):
    require_owner(request)
    if settings.hosted_mode:
        raise HTTPException(403, "Hosted connections are managed securely in Render.")
    save_api_keys({"OPENAI_API_KEY": openai_key, "GEMINI_API_KEY": gemini_key, "TWELVE_LABS_API_KEY": twelve_labs_key})
    return RedirectResponse("/settings?saved=true", status_code=303)


@app.get("/assets", response_class=HTMLResponse)
async def remote_assets_page(request: Request, message: str = ""):
    require_owner(request)
    return templates.TemplateResponse(request, "assets.html", {"assets": store.remote_assets(), "readiness": readiness(), "message": message})


@app.post("/assets/delete")
async def delete_remote_asset(request: Request, owner_type: str = Form(...), owner_id: str = Form(...),
                              provider: str = Form(...), asset_id: str = Form(...)):
    require_owner(request)
    if owner_type not in ("style", "project") or provider not in PROVIDERS:
        raise HTTPException(400, "Invalid remote asset")
    match = next((item for item in store.remote_assets() if item.get("owner_type") == owner_type and item.get("owner_id") == owner_id and item.get("provider") == provider and item.get("id") == asset_id), None)
    if not match:
        raise HTTPException(404, "Remote asset not found")
    if match.get("status") == "deleted":
        return RedirectResponse("/assets?message=already-deleted", status_code=303)
    try:
        await PROVIDERS[provider]().delete_asset(asset_id)
        store.mark_remote_asset_deleted(owner_type, owner_id, provider, asset_id)
    except Exception as exc:
        raise HTTPException(502, "The provider could not delete this asset: %s" % exc)
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


def style_context(request: Request, style_id: str):
    try:
        profile = store.style(style_id)
    except FileNotFoundError:
        raise HTTPException(404, "Style not found")
    return {"request": request, "style": profile, "analyses": store.style_analyses(style_id),
            "learning_state": store.learning_state(style_id), "readiness": readiness()}


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
    context = style_context(request, style_id)
    if not context["style"].get("style_analysis"):
        return RedirectResponse("/styles/%s/analysis" % style_id, status_code=303)
    return templates.TemplateResponse(request, "style_review.html", context)


@app.post("/styles/{style_id}/delete")
async def delete_style(request: Request, style_id: str):
    require_owner(request)
    try:
        profile = store.style(style_id)
    except FileNotFoundError:
        raise HTTPException(404, "Style not found")
    linked = [project for project in store.list_projects() if project.get("style_id") == style_id]
    if linked:
        raise HTTPException(409, "This style is used by an existing project; delete or archive that project first.")
    for asset in [item for item in store.remote_assets() if item.get("owner_type") == "style" and item.get("owner_id") == style_id and item.get("status") != "deleted"]:
        try:
            await PROVIDERS[asset["provider"]]().delete_asset(asset["id"])
            store.mark_remote_asset_deleted("style", style_id, asset["provider"], asset["id"])
        except Exception as exc:
            raise HTTPException(502, "The style could not be deleted because its remote %s asset could not be removed: %s" % (asset["provider"].title(), exc))
    store.delete_style(profile["style_id"])
    return RedirectResponse("/?message=style-deleted", status_code=303)


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
    if profile.get("status") == "analyzing_references":
        raise HTTPException(409, "This style is already being analyzed")
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(400, "Connect OpenAI before building an editing recipe")
    provider = preferred_provider()
    if not PROVIDERS[provider]().readiness().configured:
        raise HTTPException(400, "Add the %s API key to .env" % provider.title())
    store.update_style(style_id, status="analysis_queued", last_error=None, active_started_at=utc_now())
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
    if profile.get("status") == "revising_style":
        raise HTTPException(409, "This style is already being revised")
    store.update_style(style_id, status="revision_queued", last_error=None, active_started_at=utc_now())
    background_tasks.add_task(_run_style_revision, style_id, feedback.strip())
    return RedirectResponse("/styles/%s/progress" % style_id, status_code=303)


@app.get("/projects/new", response_class=HTMLResponse)
async def new_project(request: Request):
    draft = request.session.get("project_draft", {})
    return templates.TemplateResponse(request, "project_describe.html", {"draft": draft})


@app.post("/projects/new/describe")
async def save_project_description(request: Request, name: str = Form(""), description: str = Form(...)):
    if not description.strip():
        raise HTTPException(400, "Describe the video you want to create.")
    request.session["project_draft"] = {
        "name": name.strip(),
        "description": description.strip(),
        "style_id": "",
    }
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
        provider = preferred_provider()
        if not provider_status.get(provider, {}).get("configured"):
            raise HTTPException(400, "Video understanding is not configured. Open More, then Connections.")
        store.update_style(profile["style_id"], status="analysis_queued", last_error=None, active_started_at=utc_now())
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
    if style.get("status") in {"analysis_queued", "analyzing_references"}:
        raise HTTPException(409, "Reference analysis is already running")
    provider = preferred_provider()
    if not PROVIDERS[provider]().readiness().configured or not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(400, "Connect video understanding and OpenAI before trying again")
    store.update_style(style_id, status="analysis_queued", last_error=None, last_error_details=None, active_started_at=utc_now())
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


@app.get("/projects/new/engine-decides")
async def choose_engine_decides():
    return RedirectResponse("/projects/new", status_code=303)


@app.get("/projects/new/footage", response_class=HTMLResponse)
async def project_footage_page(request: Request, style_id: str = "", session_id: str = ""):
    draft = request.session.get("project_draft")
    if not draft or not draft.get("description"):
        return RedirectResponse("/projects/new", status_code=303)
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
    uploaded_session = None
    session_id = session_id or request.session.get("active_upload_session_id", "")
    if session_id:
        try:
            uploaded_session = store.upload_session(session_id)
        except (FileNotFoundError, OSError, ValueError):
            request.session.pop("active_upload_session_id", None)
            uploaded_session = None
        if uploaded_session and uploaded_session.get("device_id") != device_id(request):
            raise HTTPException(404, "Upload session not found")
    return templates.TemplateResponse(request, "project_footage.html", {
        "style": style, "draft": draft, "uploaded_session": uploaded_session,
    })


@app.post("/projects/upload-session")
async def start_upload_session(request: Request, name: str = Form(""), style_id: str = Form(""),
                               prompt: str = Form(""), target_seconds: int = Form(60)):
    provider = preferred_provider()
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
    )
    request.session["active_upload_session_id"] = session["session_id"]
    return {"session_id": session["session_id"], "uploaded_files": 0}


@app.post("/projects/upload-session/{session_id}/file")
async def upload_session_file(request: Request, session_id: str, footage: UploadFile = File(...)):
    try:
        session = store.upload_session(session_id)
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "Upload session not found. Start the upload again.")
    if session.get("device_id") != device_id(request):
        raise HTTPException(404, "Upload session not found. Start the upload again.")
    suffix = Path(footage.filename or "").suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise HTTPException(400, "Unsupported video file: %s" % footage.filename)
    raw_dir = store.upload_session_dir(session_id) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    safe_filename = safe_name(footage.filename or "raw.mp4")
    target = raw_dir / ("incoming-%s-%s" % (os.urandom(6).hex(), safe_filename))
    try:
        written = 0
        with target.open("wb") as output:
            while chunk := await footage.read(1024 * 1024):
                written += len(chunk)
                if written + sum(item.get("size_bytes", 0) for item in session.get("files", [])) > settings.max_upload_batch_bytes:
                    raise HTTPException(413, "This upload is larger than the 2 GB batch limit.")
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    # Finalize the short manifest update as one critical section. Desktop may
    # upload two files concurrently; without this lock, both completions could
    # observe the same list length and overwrite the same sequential slot.
    with upload_manifest_lock:
        session = store.upload_session(session_id)
        original_name = footage.filename or safe_filename
        duplicate = next(
            (item for item in session.get("files", [])
             if item.get("original_name") == original_name and item.get("size_bytes") == target.stat().st_size),
            None,
        )
        current_bytes = sum(item.get("size_bytes", 0) for item in session.get("files", []))
        if not duplicate and current_bytes + target.stat().st_size > settings.max_upload_batch_bytes:
            target.unlink(missing_ok=True)
            raise HTTPException(413, "This batch is larger than 2 GB. Upload fewer videos at a time.")
        if duplicate:
            target.unlink(missing_ok=True)
            record = duplicate
        else:
            index = len(session.get("files", [])) + 1
            final_target = raw_dir / ("%03d-%s" % (index, safe_filename))
            target.replace(final_target)
            record = {
                "file_id": "raw-%03d" % index,
                "original_name": original_name,
                "stored_path": str(final_target.relative_to(store.data_dir)),
                "size_bytes": final_target.stat().st_size,
            }
            session = store.update_upload_session(session_id, files=session.get("files", []) + [record])
    return {"file_id": record["file_id"], "filename": record["original_name"], "size_bytes": record["size_bytes"], "uploaded_files": len(session["files"])}


@app.post("/projects/upload-session/{session_id}/complete")
async def complete_upload_session(request: Request, session_id: str):
    try:
        session = store.upload_session(session_id)
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "Upload session not found. Start the upload again.")
    if session.get("device_id") != device_id(request):
        raise HTTPException(404, "Upload session not found. Start the upload again.")
    if sum(item.get("size_bytes", 0) for item in session.get("files", [])) > settings.max_upload_batch_bytes:
        raise HTTPException(413, "This batch is larger than 2 GB. Upload fewer videos at a time.")
    if not session.get("files"):
        raise HTTPException(400, "Choose at least one video before continuing.")
    paths = [store.resolve_data_path(item["stored_path"]) for item in session["files"]]
    metadata = {}
    for path in paths:
        details = await asyncio.to_thread(inspect_video, path)
        if details.get("inspection_error"):
            raise HTTPException(400, "Could not inspect %s: %s" % (path.name, details["inspection_error"]))
        metadata[str(path)] = details
    total = sum(item.get("duration_seconds") or 0 for item in metadata.values())
    if total > 60 * 60:
        raise HTTPException(400, "Raw footage must total 60 minutes or less for this workspace.")
    store.update_upload_session(
        session_id, inspection_metadata=metadata, total_duration_seconds=round(total, 3), status="ready_for_brief",
    )
    return {"session_id": session_id}


@app.get("/projects/new/brief", response_class=HTMLResponse)
async def new_project_brief_page(request: Request, session_id: str):
    try:
        session = store.upload_session(session_id)
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "Upload session not found")
    if session.get("device_id") != device_id(request) or session.get("status") != "ready_for_brief":
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
    if session.get("device_id") != device_id(request) or session.get("status") != "ready_for_brief":
        raise HTTPException(404, "Upload session not found")
    if not PROVIDERS[session["provider"]]().readiness().configured:
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
    paths = [store.resolve_data_path(item["stored_path"]) for item in session["files"]]
    metadata = session.get("inspection_metadata", {})
    project = store.create_project(
        session["name"], selected_style_id, session["provider"], combined, target_seconds,
        paths, metadata, intent, recipe_match, session.get("device_id"),
    )
    store.update_project(project["project_id"], initial_prompt=initial, additional_prompt=additional)
    store.save_learning_signal(selected_style_id, {
        "source_key": "raw:%s" % project["project_id"],
        "type": "raw_footage_upload", "scope": "project_only",
        "project_id": project["project_id"], "file_count": len(paths),
        "device_id": project.get("device_id"),
        "total_duration_seconds": session.get("total_duration_seconds", 0), "status": "context",
        "instruction": "Project footage inventory; use only for compatibility and outcome analysis, not as a shared style rule.",
    })
    shutil.rmtree(str(store.upload_session_dir(session_id)), ignore_errors=True)
    request.session.pop("project_draft", None)
    request.session.pop("active_upload_session_id", None)
    store.update_project(
        project["project_id"], status="analysis_queued", last_error=None, active_revision=1,
        active_task="Understanding your footage", active_started_at=utc_now(),
    )
    background_tasks.add_task(_run_complete_production, project["project_id"])
    return RedirectResponse("/projects/%s/production-progress" % project["project_id"], status_code=303)


@app.post("/projects")
async def create_project(
    request: Request, name: str = Form(""), style_id: str = Form(""),
    prompt: str = Form(""), target_seconds: int = Form(60),
    footage: List[UploadFile] = File(...),
):
    provider = preferred_provider()
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
    batch_bytes = 0
    try:
        for index, upload in enumerate(footage, start=1):
            suffix = Path(upload.filename or "").suffix.lower()
            if suffix not in VIDEO_EXTENSIONS:
                raise HTTPException(400, "Unsupported video file: %s" % upload.filename)
            target = temp_dir / ("%03d-%s" % (index, safe_name(upload.filename or "raw.mp4")))
            with target.open("wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    batch_bytes += len(chunk)
                    if batch_bytes > settings.max_upload_batch_bytes:
                        raise HTTPException(413, "This batch is larger than 2 GB. Upload fewer videos at a time.")
                    output.write(chunk)
            paths.append(target)
        metadata = {str(path): await asyncio.to_thread(inspect_video, path) for path in paths}
        total = sum(item.get("duration_seconds") or 0 for item in metadata.values())
        if total > 60 * 60:
            raise HTTPException(400, "Raw footage must total 60 minutes or less for this workspace.")
        project = store.create_project(name, style_id, provider, prompt, target_seconds, paths, metadata, intent, recipe_match, device_id(request))
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
    if status in ("timeline_ready", "export_failed", "approved"):
        destination = "ready"
    elif status in ("timeline_queued", "planning_timeline", "preparing_proxies"):
        destination = "production-progress"
    elif status in ("analysis_queued", "analyzing_footage"):
        destination = "production-progress"
    elif status in ("rough_cut_queued", "planning_rough_cut", "rendering_rough_cut"):
        destination = "production-progress"
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
    for asset in [item for item in store.remote_assets() if item.get("owner_type") == "project" and item.get("owner_id") == project_id and item.get("status") != "deleted"]:
        try:
            await PROVIDERS[asset["provider"]]().delete_asset(asset["id"])
            store.mark_remote_asset_deleted("project", project_id, asset["provider"], asset["id"])
        except Exception as exc:
            raise HTTPException(502, "The project was kept because its remote analysis copy could not be deleted: %s" % exc)
    store.delete_project(project_id)
    return RedirectResponse("/projects?message=deleted", status_code=303)


def project_context(request: Request, project_id: str):
    try:
        project = store.project(project_id)
        style = store.style(project["style_id"])
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    latest_plan = None
    latest_run = project.get("latest_run") or {}
    if latest_run.get("plan_path"):
        try:
            latest_plan = store.read_json(store.resolve_data_path(latest_run["plan_path"]))
        except (OSError, ValueError):
            latest_plan = None
    return {"request": request, "project": project, "style": style, "readiness": readiness(), "latest_plan": latest_plan}


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
        await asyncio.to_thread(TimelineExportService(store).run, project_id, export["export_id"])
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
        await asyncio.to_thread(TimelineExportService(store).run, project_id, export["export_id"])
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
    if not PROVIDERS[project["provider"]]().readiness().configured:
        raise HTTPException(400, "Video understanding is not configured. Open Settings to connect it.")
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(400, "The editing engine is not configured. Open Settings to connect it.")
    store.update_project(
        project_id, prompt=prompt.strip() or "Create the strongest coherent rough cut from the supplied footage.",
        target_duration_seconds=target_seconds, status="analysis_queued", last_error=None,
        active_revision=len(project.get("runs", [])) + 1, active_task="Understanding your footage",
        active_started_at=utc_now(),
    )
    background_tasks.add_task(_run_complete_production, project_id)
    return RedirectResponse("/projects/%s/production-progress" % project_id, status_code=303)


@app.get("/projects/{project_id}/production-progress", response_class=HTMLResponse)
async def production_progress_page(request: Request, project_id: str):
    context = project_context(request, project_id)
    status = context["project"].get("status")
    if status not in ("analysis_queued", "analyzing_footage", "footage_analyzed", "rough_cut_queued", "planning_rough_cut", "rendering_rough_cut", "analysis_failed", "rough_cut_failed", "timeline_queued", "planning_timeline", "preparing_proxies", "timeline_failed", "export_queued", "exporting", "export_failed"):
        return RedirectResponse("/projects/%s" % project_id, status_code=303)
    return templates.TemplateResponse(request, "production_progress.html", context)


@app.get("/projects/{project_id}/ready", response_class=HTMLResponse)
async def project_ready_page(request: Request, project_id: str):
    project = store.project(project_id)
    if not TimelineStore(store).exists(project_id):
        if project.get("latest_run"):
            migrate_legacy_project(store, project_id)
        else:
            return RedirectResponse("/projects/%s/production-progress" % project_id, status_code=303)
    cuts = TimelineExportService(store).records(project_id, completed_only=True)
    return templates.TemplateResponse(request, "project_ready.html", {
        "project": project, "export": project.get("latest_export") or {}, "cuts": cuts,
        "cut_number": len(cuts),
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


@app.get("/api/projects/{project_id}/timeline")
async def get_project_timeline(project_id: str):
    timelines = TimelineStore(store)
    if not timelines.exists(project_id):
        project = store.project(project_id)
        if not project.get("latest_run"):
            raise HTTPException(409, "The first timeline is not ready")
        migrate_legacy_project(store, project_id)
    return timelines.load(project_id)


@app.post("/api/projects/{project_id}/timeline/transactions")
async def apply_timeline_transaction(request: Request, project_id: str):
    project = store.project(project_id)
    if project.get("editor_read_only"):
        raise HTTPException(409, "This timeline is locked while an export is running")
    payload = await request.json()
    required = ("base_revision", "base_timeline_hash", "transaction_id", "operations")
    if any(key not in payload for key in required):
        raise HTTPException(400, "Timeline transaction is incomplete")
    payload["origin"] = "manual" if payload.get("origin") not in ("ai_proposal", "system") else payload["origin"]
    try:
        result = TimelineStore(store).transact(project_id, payload)
        mark_working_timeline_changed(store, project_id, result["timeline"], str(payload.get("reason") or "Timeline edit"))
        if not result.get("diff", {}).get("idempotent"):
            store.save_learning_signal(project["style_id"], {
                "source_key": "timeline-transaction:%s:%s" % (project_id, payload["transaction_id"]),
                "type": "timeline_interaction", "scope": "project_only", "project_id": project_id,
                "device_id": project.get("device_id"), "origin": payload["origin"],
                "reason": str(payload.get("reason") or "Timeline edit"), "diff": result.get("diff"),
                "status": "context", "instruction": "Retain as project audit context; only the latest successful approval is positive evidence.",
            })
        return result
    except StaleTimelineError as exc:
        return JSONResponse({"detail": str(exc), "current": exc.current}, status_code=409)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc))


@app.post("/api/projects/{project_id}/timeline/undo")
async def undo_timeline(project_id: str):
    if store.project(project_id).get("editor_read_only"):
        raise HTTPException(409, "This timeline is locked while an export is running")
    result = TimelineStore(store).undo(project_id)
    mark_working_timeline_changed(store, project_id, result["timeline"], "Undo timeline edit")
    return result


@app.post("/api/projects/{project_id}/timeline/redo")
async def redo_timeline(project_id: str):
    if store.project(project_id).get("editor_read_only"):
        raise HTTPException(409, "This timeline is locked while an export is running")
    result = TimelineStore(store).redo(project_id)
    mark_working_timeline_changed(store, project_id, result["timeline"], "Redo timeline edit")
    return result


@app.post("/api/projects/{project_id}/timeline/proposals")
async def create_timeline_proposal(request: Request, project_id: str):
    payload = await request.json()
    try:
        begin_timeline_job(store, project_id, "proposal_running", "Preparing a suggested timeline change")
        proposal = await TimelineProposalService(store).create(project_id, str(payload.get("instruction") or ""))
        finish_timeline_job(store, project_id)
        return proposal
    except Exception as exc:
        fail_timeline_job(store, project_id, exc)
        if isinstance(exc, (ValueError, KeyError, json.JSONDecodeError)):
            raise HTTPException(422, str(exc))
        raise HTTPException(502, "PB&J could not prepare that suggestion. Your timeline was not changed.")


@app.post("/api/projects/{project_id}/timeline/proposals/{proposal_id}/apply")
async def apply_timeline_proposal(project_id: str, proposal_id: str):
    try:
        result = TimelineProposalService(store).apply(project_id, proposal_id)
        mark_working_timeline_changed(store, project_id, result["timeline"], "Applied AI timeline proposal")
        return result
    except StaleTimelineError as exc:
        return JSONResponse({"detail": str(exc), "current": exc.current}, status_code=409)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(422, str(exc))


@app.post("/api/projects/{project_id}/timeline/proposals/{proposal_id}/reject")
async def reject_timeline_proposal(project_id: str, proposal_id: str):
    try:
        return TimelineProposalService(store).reject(project_id, proposal_id)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(422, str(exc))


def _proxy_manifest(project_id: str, asset_id: str, *, waveform: bool = False, thumbnails: bool = False):
    project = store.project(project_id)
    asset = next((item for item in project.get("raw_files", []) + project.get("audio_files", []) if item.get("file_id") == asset_id), None)
    if not asset:
        raise HTTPException(404, "Asset not found")
    pipeline = ProxyPipeline(store)
    return (pipeline.ensure_audio_asset(project_id, asset, include_waveform=waveform)
            if asset_id.startswith("audio-") else
            pipeline.ensure_asset(project_id, asset, include_waveform=waveform, include_thumbnails=thumbnails))


@app.get("/api/projects/{project_id}/assets/{asset_id}/preview")
async def project_asset_preview(project_id: str, asset_id: str):
    manifest = _proxy_manifest(project_id, asset_id)
    return FileResponse(store.resolve_data_path(manifest["preview_path"]), media_type="audio/mp4" if asset_id.startswith("audio-") else "video/mp4")


@app.get("/api/projects/{project_id}/assets/{asset_id}/waveform")
async def project_asset_waveform(project_id: str, asset_id: str):
    manifest = _proxy_manifest(project_id, asset_id, waveform=True)
    return store.read_json(store.resolve_data_path(manifest["waveform_path"]))


@app.get("/api/projects/{project_id}/assets/{asset_id}/thumbnail/{index}")
async def project_asset_thumbnail(project_id: str, asset_id: str, index: int):
    manifest = _proxy_manifest(project_id, asset_id, thumbnails=True)
    paths = manifest.get("thumbnail_paths", [])
    if index < 0 or index >= len(paths):
        raise HTTPException(404, "Thumbnail not found")
    return FileResponse(store.resolve_data_path(paths[index]), media_type="image/jpeg")


async def _analyze_editor_asset(project_id: str, asset_id: str) -> None:
    try:
        await ProjectAnalysisWorkflow(store).analyze(project_id, refresh=False)
        timeline = TimelineStore(store).mark_asset_analyzed(project_id, asset_id)
        mark_working_timeline_changed(store, project_id, timeline, "New editor asset analysis completed")
        finish_timeline_job(store, project_id)
    except Exception as exc:
        # Editor uploads remain usable for manual timeline work even when their
        # optional semantic analysis fails. Preserve the asset, expose the
        # failure in timeline state, and avoid leaving the project stuck in an
        # analysis status that blocks later editing or export.
        try:
            timeline = TimelineStore(store).mark_asset_analysis_failed(project_id, asset_id, str(exc))
            mark_working_timeline_changed(store, project_id, timeline, "Optional editor asset analysis failed")
            fail_timeline_job(store, project_id, exc)
        except Exception:
            return


@app.post("/api/projects/{project_id}/assets")
async def upload_editor_asset(
    project_id: str, background_tasks: BackgroundTasks, media: UploadFile = File(...),
    analyze_for_ai: bool = Form(False), permission_confirmed: bool = Form(False),
):
    project = store.project(project_id)
    if project.get("status") in ACTIVE_JOB_STATES or project.get("editor_read_only"):
        raise HTTPException(409, "Wait for the current project task to finish before adding media")
    suffix = Path(media.filename or "").suffix.lower()
    audio_extensions = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".aiff", ".ogg"}
    kind = "video" if suffix in VIDEO_EXTENSIONS else "audio" if suffix in audio_extensions else None
    if not kind:
        raise HTTPException(400, "Choose a supported video or audio file")
    if kind == "audio" and not permission_confirmed:
        raise HTTPException(400, "Confirm you have permission to use this audio")
    collection = "raw_files" if kind == "video" else "audio_files"
    existing = project.get(collection, [])
    prefix = "raw" if kind == "video" else "audio"
    asset_id = "%s-%03d" % (prefix, len(existing) + 1)
    folder = store.project_dir(project_id) / ("raw" if kind == "video" else "audio")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (asset_id + "-" + safe_name(media.filename or (asset_id + suffix)))
    written = 0
    try:
        with target.open("wb") as output:
            while chunk := await media.read(1024 * 1024):
                written += len(chunk)
                if written > settings.max_upload_batch_bytes:
                    raise HTTPException(413, "This upload is larger than the 2 GB batch limit")
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    metadata = await asyncio.to_thread(inspect_video, target)
    if metadata.get("inspection_error"):
        target.unlink(missing_ok=True)
        raise HTTPException(400, "PB&J could not inspect this media file")
    record = {
        "file_id": asset_id, "original_name": media.filename or target.name,
        "stored_path": str(target.relative_to(store.data_dir)), "sha256": sha256(target),
        "metadata": metadata, "analysis_status": "pending" if (kind == "video" and analyze_for_ai) else "not_requested",
        "permission_confirmed": bool(permission_confirmed), "uploaded_in_editor": True,
    }
    store.update_project(project_id, **{collection: existing + [record]})
    asset = {
        "asset_id": asset_id, "kind": kind, "original_name": record["original_name"],
        "stored_path": record["stored_path"], "sha256": record["sha256"],
        "duration_us": us_from_seconds(metadata.get("duration_seconds") or 0),
        "has_audio": bool(metadata.get("has_audio")), "width": metadata.get("width"), "height": metadata.get("height"),
        "rotation": metadata.get("rotation", 0), "analyzed": False,
        "analysis_status": record["analysis_status"], "permission_scope": "project_private",
        "media_metadata": metadata,
    }
    timeline = TimelineStore(store).register_asset(project_id, asset)
    mark_working_timeline_changed(store, project_id, timeline, "Added project media")
    pipeline = ProxyPipeline(store)
    proxy = await asyncio.to_thread(pipeline.ensure_asset if kind == "video" else pipeline.ensure_audio_asset, project_id, record)
    store.save_learning_signal(project["style_id"], {
        "source_key": "editor-upload:%s:%s" % (project_id, asset_id), "type": "editor_media_upload",
        "scope": "project_only", "project_id": project_id, "device_id": project.get("device_id"),
        "asset_id": asset_id, "media_kind": kind, "analysis_requested": bool(analyze_for_ai),
        "status": "context", "instruction": "User added project media from the timeline editor.",
    })
    if kind == "video" and analyze_for_ai:
        begin_timeline_job(store, project_id, "analyzing_footage", "Analyzing the newly added video")
        background_tasks.add_task(_analyze_editor_asset, project_id, asset_id)
    return {"asset": asset, "timeline": timeline, "proxy": proxy, "analysis_requested": bool(analyze_for_ai)}


def _run_timeline_export(project_id: str, export_id: str) -> None:
    try:
        TimelineExportService(store).run(project_id, export_id)
    except Exception:
        return


@app.post("/api/projects/{project_id}/exports")
async def create_timeline_export(request: Request, project_id: str, background_tasks: BackgroundTasks):
    payload = await request.json()
    try:
        record = TimelineExportService(store).create(
            project_id, str(payload.get("timeline_hash") or ""),
            approve_on_success=bool(payload.get("approve_on_success")),
            approval_confirmation=bool(payload.get("approval_confirmation")),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    background_tasks.add_task(_run_timeline_export, project_id, record["export_id"])
    return {
        "export_id": record["export_id"],
        "progress_url": "/projects/%s/exports/%s/progress" % (project_id, record["export_id"]),
    }


@app.get("/api/projects/{project_id}/exports/{export_id}")
async def get_timeline_export(project_id: str, export_id: str):
    try:
        return TimelineExportService(store).record(project_id, export_id)
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(404, "Export not found")


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


@app.post("/projects/{project_id}/approve")
async def approve_project_run(project_id: str, confirmation: str = Form("")):
    if confirmation != "approve":
        raise HTTPException(400, "Confirm that this finished cut is approved")
    project = store.project(project_id)
    export = project.get("latest_export") or {}
    if export.get("status") != "complete":
        raise HTTPException(409, "A completed rough cut is required before approval")
    timeline = store.read_json(store.resolve_data_path(export["timeline_path"]))
    receipt = store.read_json(store.resolve_data_path(export["render_receipt_path"]))
    approval = approve_timeline_export(store, project_id, export, timeline, receipt)
    export["approval"] = approval
    export_path = store.project_dir(project_id) / "exports" / export["export_id"] / "export.json"
    store.write_json(export_path, export)
    store.update_project(project_id, status="approved", latest_export=export)
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
    store.update_project(project_id, status="timeline_queued", last_error=None, active_task="Rebuilding the timeline from saved analysis", active_started_at=utc_now())
    background_tasks.add_task(_run_revision, project_id, "Rebuild the cut after the previous preparation failure.")
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
    store.update_project(
        project_id, status="timeline_queued", last_error=None,
        active_task="Replanning from your feedback", active_started_at=utc_now(),
        revision_feedback=history, pending_revision_feedback=combined,
    )
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


@app.get("/api/contracts")
async def api_contracts():
    return {"analysis": ANALYSIS_SCHEMA, "style_profile": STYLE_PROFILE_SCHEMA, "edit_plan": EDIT_PLAN_SCHEMA}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/offline", response_class=HTMLResponse)
async def offline_page(request: Request):
    return templates.TemplateResponse(request, "offline.html", {})
