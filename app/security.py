"""Small, process-local security controls for the single-instance private beta."""

from collections import OrderedDict, deque
from hashlib import sha256
import hmac
import secrets
from threading import Lock
import time
from urllib.parse import urlsplit


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_SECRET_BYTES = 256


def exact_secret_match(supplied: object, configured: object, *, max_bytes: int = MAX_SECRET_BYTES) -> bool:
    """Compare short user-entered secrets exactly without early-exit comparison."""
    if not isinstance(supplied, str) or not isinstance(configured, str) or not configured:
        return False
    try:
        supplied_bytes = supplied.encode("utf-8")
        configured_bytes = configured.encode("utf-8")
    except UnicodeError:
        return False
    if len(supplied_bytes) > max_bytes or len(configured_bytes) > max_bytes:
        return False
    return secrets.compare_digest(supplied_bytes, configured_bytes)


def client_fingerprint(host: str, secret: str) -> str:
    """Keep proxy/client addresses out of the limiter's in-memory keys."""
    return hmac.new(secret.encode("utf-8"), (host or "unknown").encode("utf-8"), sha256).hexdigest()


class LoginRateLimiter:
    """A bounded failure-only limiter for PB&J's one-process private demo."""

    def __init__(self, *, client_limit: int = 10, global_limit: int = 100,
                 window_seconds: int = 15 * 60, max_clients: int = 512, clock=time.monotonic):
        self.client_limit = client_limit
        self.global_limit = global_limit
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self.clock = clock
        self._clients: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._global: deque[float] = deque()
        self._lock = Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._global and self._global[0] <= cutoff:
            self._global.popleft()
        for key in list(self._clients):
            failures = self._clients[key]
            while failures and failures[0] <= cutoff:
                failures.popleft()
            if not failures:
                del self._clients[key]

    def _retry_after(self, failures: deque[float], now: float) -> int:
        if not failures:
            return 0
        return max(1, int(self.window_seconds - (now - failures[0]) + 0.999))

    def retry_after(self, client: str, endpoint: str) -> int:
        now = self.clock()
        with self._lock:
            self._prune(now)
            failures = self._clients.get((client, endpoint), deque())
            if len(self._global) >= self.global_limit:
                return self._retry_after(self._global, now)
            if len(failures) >= self.client_limit:
                return self._retry_after(failures, now)
            return 0

    def record_failure(self, client: str, endpoint: str) -> int:
        now = self.clock()
        key = (client, endpoint)
        with self._lock:
            self._prune(now)
            failures = self._clients.setdefault(key, deque())
            failures.append(now)
            self._clients.move_to_end(key)
            self._global.append(now)
            while len(self._clients) > self.max_clients:
                self._clients.popitem(last=False)
            if len(self._global) >= self.global_limit:
                return self._retry_after(self._global, now)
            if len(failures) >= self.client_limit:
                return self._retry_after(failures, now)
            return 0

    def record_success(self, client: str, endpoint: str) -> None:
        with self._lock:
            self._clients.pop((client, endpoint), None)

    def reset(self) -> None:
        """Clear process-local state, primarily for deterministic tests."""
        with self._lock:
            self._clients.clear()
            self._global.clear()


def same_origin(request, *, hosted: bool) -> bool:
    """Validate browser mutation metadata against the request's canonical host."""
    if request.method.upper() not in UNSAFE_METHODS:
        return True
    if request.headers.get("sec-fetch-site", "").casefold() == "cross-site":
        return False
    host = request.headers.get("host", "").strip().casefold()
    if not host:
        return False
    scheme = "https" if hosted else request.url.scheme.casefold()
    candidate = request.headers.get("origin") or request.headers.get("referer")
    if not candidate:
        return not hosted
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return False
    return (
        parsed.scheme.casefold() == scheme
        and parsed.netloc.casefold() == host
        and (request.headers.get("origin") is None or (not parsed.path and not parsed.query and not parsed.fragment))
    )


CONTENT_SECURITY_POLICY = "; ".join((
    "default-src 'self'",
    "base-uri 'none'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "connect-src 'self'",
    "font-src 'self'",
    "manifest-src 'self'",
    "worker-src 'none'",
))


def apply_security_headers(response, *, path: str, hosted: bool):
    """Apply browser defenses while retaining explicit public-asset caching."""
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if hosted:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if not (path.startswith("/static/") or path in {"/ui.css", "/manifest.webmanifest"}):
        response.headers["Cache-Control"] = "private, no-store"
    return response
