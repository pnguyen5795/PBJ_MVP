"""Minimal wake/suspend controller for the disposable PBJ demonstration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import hmac
import html
import json
import os
import re
import time
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware


MAX_FORM_BYTES = 1024
MAX_SECRET_BYTES = 256
SERVICE_ID_PATTERN = re.compile(r"^srv-[a-z0-9]+$")


@dataclass(frozen=True)
class LauncherSettings:
    target_service_id: str
    target_url: str
    render_api_key: str
    control_token: str
    access_code: str
    session_secret: str
    session_days: int = 7

    @classmethod
    def from_environment(cls) -> "LauncherSettings":
        return cls(
            target_service_id=os.getenv("PBJ_TARGET_SERVICE_ID", ""),
            target_url=os.getenv("PBJ_TARGET_URL", "").rstrip("/"),
            render_api_key=os.getenv("RENDER_API_KEY", ""),
            control_token=os.getenv("PBJ_DEMO_CONTROL_TOKEN", ""),
            access_code=os.getenv("PBJ_ACCESS_CODE", ""),
            session_secret=os.getenv("PBJ_LAUNCHER_SESSION_SECRET", ""),
        )


def validate_settings(settings: LauncherSettings) -> None:
    target = urlsplit(settings.target_url)
    if (
        target.scheme != "https"
        or not target.netloc
        or target.username is not None
        or target.password is not None
        or target.path not in {"", "/"}
        or target.query
        or target.fragment
    ):
        raise RuntimeError("PBJ_TARGET_URL must be an HTTPS origin.")
    if not SERVICE_ID_PATTERN.fullmatch(settings.target_service_id):
        raise RuntimeError("PBJ_TARGET_SERVICE_ID is invalid.")
    for name, value, minimum in (
        ("RENDER_API_KEY", settings.render_api_key, 20),
        ("PBJ_DEMO_CONTROL_TOKEN", settings.control_token, 32),
        ("PBJ_ACCESS_CODE", settings.access_code, 1),
        ("PBJ_LAUNCHER_SESSION_SECRET", settings.session_secret, 32),
    ):
        try:
            length = len(value.encode("utf-8"))
        except (AttributeError, UnicodeError) as exc:
            raise RuntimeError(f"{name} must be valid UTF-8 text.") from exc
        if not minimum <= length <= MAX_SECRET_BYTES:
            raise RuntimeError(
                f"{name} must be between {minimum} and {MAX_SECRET_BYTES} bytes."
            )


def exact_secret_match(candidate: object, expected: str) -> bool:
    if not isinstance(candidate, str):
        return False
    try:
        candidate_bytes = candidate.encode("utf-8")
        expected_bytes = expected.encode("utf-8")
    except UnicodeError:
        return False
    if len(candidate_bytes) > MAX_SECRET_BYTES or len(expected_bytes) > MAX_SECRET_BYTES:
        return False
    return hmac.compare_digest(candidate_bytes, expected_bytes)


def page(title: str, body: str, *, script: str = "") -> HTMLResponse:
    document = f"""<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">
<meta name=\"theme-color\" content=\"#6f4bf2\"><title>{html.escape(title)} · PBJ</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(160deg,#fff8e9,#fff 55%);color:#17151c;font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif;min-height:100vh;display:grid;place-items:center;padding:24px}}
main{{width:min(100%,440px);background:rgba(255,255,255,.9);border:1px solid #e7dfd2;border-radius:28px;padding:32px 24px;box-shadow:0 24px 70px rgba(58,39,20,.12)}}
.mark{{width:58px;height:58px;border-radius:18px;background:#6f4bf2;color:white;display:grid;place-items:center;font-weight:850;font-size:23px}} h1{{font-size:32px;line-height:1.05;margin:26px 0 12px}} p{{color:#645d69;line-height:1.55}}
input,button,a.button{{width:100%;min-height:54px;border-radius:15px;font:inherit;font-weight:750}} input{{border:1px solid #cfc7d4;padding:0 15px;margin:12px 0}} button,a.button{{display:grid;place-items:center;border:0;background:#17151c;color:#fff;text-decoration:none;padding:0 18px;cursor:pointer}} .error{{color:#a52222}} .spinner{{width:34px;height:34px;border:4px solid #ddd4fa;border-top-color:#6f4bf2;border-radius:50%;animation:spin .8s linear infinite;margin:24px 0}} @keyframes spin{{to{{transform:rotate(360deg)}}}}
</style></head><body><main><div class=\"mark\">PBJ</div>{body}</main>{script}</body></html>"""
    return HTMLResponse(document, headers={"Cache-Control": "no-store"})


def create_app(config: LauncherSettings | None = None) -> FastAPI:
    settings = config or LauncherSettings.from_environment()

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        validate_settings(settings)
        yield

    launcher = FastAPI(
        title="PBJ Demo Launcher", docs_url=None, redoc_url=None,
        lifespan=lifespan,
    )
    launcher.add_middleware(
        SessionMiddleware, secret_key=settings.session_secret or "invalid-not-for-runtime",
        max_age=settings.session_days * 86400, same_site="lax", https_only=True,
    )
    failures: dict[str, tuple[float, int]] = {}

    @launcher.middleware("http")
    async def browser_defenses(request: Request, call_next):
        response = await call_next(request)
        response.headers.update({
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY", "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        })
        return response

    def authorized(request: Request) -> bool:
        return request.session.get("authorized") is True

    def api_headers() -> dict[str, str]:
        return {"Authorization": "Bearer " + settings.render_api_key, "Accept": "application/json"}

    async def service_suspension_state(client: httpx.AsyncClient) -> str:
        response = await client.get(
            f"https://api.render.com/v1/services/{settings.target_service_id}",
            headers=api_headers(),
        )
        if response.status_code != 200:
            raise HTTPException(502, "Render could not check PBJ right now.")
        value = response.json().get("suspended")
        if value not in {"suspended", "not_suspended"}:
            raise HTTPException(502, "Render returned an unexpected PBJ status.")
        return value

    async def set_suspended(suspend: bool) -> None:
        action = "suspend" if suspend else "resume"
        desired = "suspended" if suspend else "not_suspended"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            if await service_suspension_state(client) == desired:
                return
            response = await client.post(
                f"https://api.render.com/v1/services/{settings.target_service_id}/{action}",
                headers=api_headers(),
            )
            if response.status_code == 202:
                return
            if await service_suspension_state(client) == desired:
                return
        raise HTTPException(502, f"Render could not {action} PBJ right now.")

    async def target_confirms_suspension() -> bool:
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
                response = await client.post(
                    settings.target_url + "/internal/demo/can-suspend",
                    headers={"Authorization": "Bearer " + settings.control_token},
                )
        except httpx.HTTPError:
            return False
        if response.status_code != 200:
            return False
        try:
            return response.json().get("allowed") is True
        except (AttributeError, ValueError):
            return False

    @launcher.get("/health")
    async def health():
        return {"status": "ok"}

    @launcher.get("/")
    async def home(request: Request):
        if authorized(request):
            return RedirectResponse("/start", status_code=303)
        error = '<p class="error">That access code did not match.</p>' if request.query_params.get("error") else ""
        return page("Open PBJ", f"<h1>Open PBJ</h1><p>Use the private demo code. PBJ will start automatically, then open when it is ready.</p>{error}<form method=\"post\" action=\"/access\"><input type=\"password\" name=\"code\" autocomplete=\"current-password\" placeholder=\"Access code\" required><button type=\"submit\">Start PBJ</button></form>")

    @launcher.post("/access")
    async def access(request: Request):
        declared = request.headers.get("content-length", "")
        if declared and (not declared.isdigit() or int(declared) > MAX_FORM_BYTES):
            return Response("Request is too large.", status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_FORM_BYTES:
                return Response("Request is too large.", status_code=413)
            body.extend(chunk)
        try:
            code = parse_qs(body.decode("utf-8"), strict_parsing=True).get("code", [""])[0]
        except (UnicodeError, ValueError):
            code = ""
        client_key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        if client_key not in failures and len(failures) >= 512:
            failures.pop(min(failures, key=lambda key: failures[key][0]), None)
        window, count = failures.get(client_key, (now, 0))
        if now - window > 300:
            window, count = now, 0
        if count >= 8:
            return Response("Try again later.", status_code=429, headers={"Retry-After": "300"})
        if not exact_secret_match(code, settings.access_code):
            failures[client_key] = (window, count + 1)
            return RedirectResponse("/?error=1", status_code=303)
        failures.pop(client_key, None)
        request.session.clear()
        request.session["authorized"] = True
        return RedirectResponse("/start", status_code=303)

    @launcher.get("/start")
    async def start(request: Request):
        if not authorized(request):
            return RedirectResponse("/", status_code=303)
        try:
            await set_suspended(False)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "PBJ could not be started right now.")
        target = html.escape(settings.target_url, quote=True)
        script = f"""<script>
const target={json.dumps(settings.target_url)};
async function check(){{try{{const r=await fetch('/status',{{cache:'no-store'}});const x=await r.json();if(x.ready){{location.replace(target);return}}}}catch(e){{}}setTimeout(check,2500)}}
check();</script>"""
        return page("Starting", f'<h1>Starting PBJ…</h1><div class="spinner" aria-label="Starting"></div><p>Render is waking the private demo. This usually takes a minute or two.</p><a class="button" href="{target}">Check PBJ now</a>', script=script)

    @launcher.get("/status")
    async def status(request: Request):
        if not authorized(request):
            raise HTTPException(401, "Access required.")
        ready = False
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
                response = await client.get(settings.target_url + "/health")
                ready = response.status_code == 200
        except httpx.HTTPError:
            pass
        return JSONResponse({"ready": ready}, headers={"Cache-Control": "no-store"})

    @launcher.post("/internal/suspend", status_code=202)
    async def suspend(request: Request):
        authorization = request.headers.get("authorization", "")
        prefix = "Bearer "
        supplied = authorization[len(prefix):] if authorization.startswith(prefix) else ""
        if not exact_secret_match(supplied, settings.control_token):
            raise HTTPException(401, "Unauthorized.")
        if not await target_confirms_suspension():
            raise HTTPException(409, "PBJ is active and will remain running.")
        try:
            await set_suspended(True)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "PBJ could not be suspended right now.")
        return {"accepted": True}

    return launcher


app = create_app()
