"""Job-aware idle suspension for the disposable hosted demonstration."""

from __future__ import annotations

import asyncio
import logging
import time
from threading import Lock
from typing import Awaitable, Callable

import httpx


logger = logging.getLogger("pbj.demo_lifecycle")


class DemoActivityTracker:
    """Track deliberate browser activity separately from in-flight requests."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = Lock()
        self._last_activity = clock()
        self._active_requests = 0
        self._suspend_requested = False

    def touch(self) -> None:
        with self._lock:
            self._last_activity = self._clock()
            self._suspend_requested = False

    def request_started(self) -> None:
        with self._lock:
            self._active_requests += 1

    def request_finished(self) -> None:
        with self._lock:
            self._active_requests = max(0, self._active_requests - 1)

    def snapshot(self) -> tuple[float, int, bool]:
        with self._lock:
            return (
                max(0.0, self._clock() - self._last_activity),
                self._active_requests,
                self._suspend_requested,
            )

    def mark_suspend_requested(self) -> None:
        with self._lock:
            self._suspend_requested = True


class DemoLifecycleManager:
    """Ask a separate always-reachable controller to suspend PBJ when safe."""

    def __init__(
        self,
        *,
        enabled: bool,
        controller_url: str,
        control_token: str,
        idle_seconds: int,
        tracker: DemoActivityTracker,
        has_active_work: Callable[[], bool],
        check_seconds: float = 30.0,
        post_suspend: Callable[[], Awaitable[bool]] | None = None,
    ):
        self.enabled = enabled
        self.controller_url = controller_url.rstrip("/")
        self.control_token = control_token
        self.idle_seconds = idle_seconds
        self.tracker = tracker
        self.has_active_work = has_active_work
        self.check_seconds = check_seconds
        self._post_suspend = post_suspend or self._request_suspend
        self._task: asyncio.Task | None = None

    async def _request_suspend(self) -> bool:
        # A free launcher can be cold. The launcher performs a final callback to
        # PBJ before suspension, so a user returning during this wait is safe.
        async with httpx.AsyncClient(timeout=90.0, follow_redirects=False) as client:
            response = await client.post(
                self.controller_url + "/internal/suspend",
                headers={"Authorization": "Bearer " + self.control_token},
            )
        return response.status_code in {200, 202, 204}

    async def attempt_suspend_if_idle(self) -> bool:
        if not self.enabled:
            return False
        idle_for, active_requests, already_requested = self.tracker.snapshot()
        if already_requested or active_requests or idle_for < self.idle_seconds:
            return False
        try:
            if self.has_active_work():
                return False
        except Exception as exc:
            logger.warning(
                "PBJ_DEMO_SUSPEND_SKIPPED active_work_check=%s", type(exc).__name__,
            )
            return False
        try:
            accepted = await self._post_suspend()
        except (httpx.HTTPError, OSError) as exc:
            logger.warning(
                "PBJ_DEMO_SUSPEND_FAILED error_type=%s", type(exc).__name__,
            )
            return False
        if not accepted:
            logger.warning("PBJ_DEMO_SUSPEND_FAILED controller_rejected=true")
            return False
        self.tracker.mark_suspend_requested()
        logger.warning("PBJ_DEMO_SUSPEND_REQUESTED idle_seconds=%d", int(idle_for))
        return True

    async def _watch(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.check_seconds)
                await self.attempt_suspend_if_idle()
        except asyncio.CancelledError:
            return

    def start(self) -> None:
        if self.enabled and self._task is None:
            self._task = asyncio.create_task(self._watch(), name="pbj-demo-idle-watchdog")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        await task
