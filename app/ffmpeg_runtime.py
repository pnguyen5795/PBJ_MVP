"""Environment-specific FFmpeg controls and bounded child-process execution."""

from __future__ import annotations

import os
from dataclasses import dataclass
import signal
import subprocess
from threading import Lock, Thread
from typing import List


MEDIA_STDERR_TAIL_BYTES = 64 * 1024
MEDIA_CAPTURE_LIMIT_BYTES = 1024 * 1024
MEDIA_TERMINATE_GRACE_SECONDS = 5

_active_media_processes_lock = Lock()
_active_media_processes: set[subprocess.Popen] = set()
_media_process_runtime_stopping = False


@dataclass(frozen=True)
class ManagedProcessResult:
    returncode: int
    stdout: str
    stderr: str
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_bytes: bytes = b""
    stderr_bytes: bytes = b""


class ManagedProcessTimeout(RuntimeError):
    """Raised after a timed-out child has been terminated and reaped."""

    def __init__(self, timeout_seconds: float, result: ManagedProcessResult):
        super().__init__("Media process timed out after %.0f seconds" % timeout_seconds)
        self.timeout_seconds = timeout_seconds
        self.result = result


class ManagedProcessUnavailable(OSError):
    """Raised when shutdown has closed admission for new media children."""


class _BoundedPipeCapture:
    """Continuously drain a pipe while retaining a bounded head or tail."""

    def __init__(self, stream, limit: int, *, keep_tail: bool):
        self.stream = stream
        self.limit = max(0, int(limit))
        self.keep_tail = keep_tail
        self.buffer = bytearray()
        self.truncated = False
        self.lock = Lock()
        self.thread = Thread(target=self._drain, name="pbj-media-pipe", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _drain(self) -> None:
        try:
            while True:
                chunk = self.stream.read(8192)
                if not chunk:
                    return
                with self.lock:
                    if self.keep_tail:
                        self.buffer.extend(chunk)
                        if len(self.buffer) > self.limit:
                            self.truncated = True
                            if self.limit:
                                del self.buffer[:-self.limit]
                            else:
                                self.buffer.clear()
                    else:
                        remaining = max(0, self.limit - len(self.buffer))
                        self.buffer.extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            self.truncated = True
        except (OSError, ValueError):
            # Process termination or pipe closure can race the reader. Bytes
            # already retained remain safe to use.
            return

    def finish(self) -> tuple[bytes, bool]:
        self.thread.join(timeout=1)
        if self.thread.is_alive():
            try:
                self.stream.close()
            except (OSError, ValueError):
                pass
            self.thread.join(timeout=1)
        else:
            try:
                self.stream.close()
            except (OSError, ValueError):
                pass
        with self.lock:
            return bytes(self.buffer), self.truncated


def _untrack_media_process(process: subprocess.Popen) -> None:
    with _active_media_processes_lock:
        _active_media_processes.discard(process)


def active_media_process_count() -> int:
    with _active_media_processes_lock:
        return len(_active_media_processes)


def start_media_process_runtime() -> None:
    """Open media-process admission for a newly started application lifespan."""
    global _media_process_runtime_stopping
    with _active_media_processes_lock:
        _media_process_runtime_stopping = False


def _signal_media_process_group(process: subprocess.Popen, sig: signal.Signals) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, sig)
        elif sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    except ProcessLookupError:
        pass
    except OSError:
        try:
            if sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            pass


def _terminate_media_process(process: subprocess.Popen, grace_seconds: float) -> int:
    if process.poll() is not None:
        return process.wait()
    _signal_media_process_group(process, signal.SIGTERM)
    try:
        return process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        _signal_media_process_group(process, signal.SIGKILL)
        return process.wait()


def terminate_active_media_processes(
    grace_seconds: float = MEDIA_TERMINATE_GRACE_SECONDS,
) -> int:
    """Terminate and reap every child started by the managed runner."""
    with _active_media_processes_lock:
        processes = list(_active_media_processes)
    for process in processes:
        try:
            _terminate_media_process(process, grace_seconds)
        except (OSError, subprocess.SubprocessError):
            continue
    return len(processes)


def shutdown_media_process_runtime(
    grace_seconds: float = MEDIA_TERMINATE_GRACE_SECONDS,
) -> int:
    """Close child admission, then terminate and reap the current snapshot."""
    global _media_process_runtime_stopping
    with _active_media_processes_lock:
        _media_process_runtime_stopping = True
        processes = list(_active_media_processes)
    for process in processes:
        try:
            _terminate_media_process(process, grace_seconds)
        except (OSError, subprocess.SubprocessError):
            continue
    return len(processes)


def run_media_process(
    command: List[str],
    *,
    timeout_seconds: float,
    terminate_grace_seconds: float = MEDIA_TERMINATE_GRACE_SECONDS,
    capture_stdout: bool = False,
    stdout_limit_bytes: int = MEDIA_CAPTURE_LIMIT_BYTES,
    decode_stdout: bool = True,
    capture_stderr: bool = True,
    stderr_limit_bytes: int = MEDIA_STDERR_TAIL_BYTES,
    stderr_tail: bool = True,
) -> ManagedProcessResult:
    """Run a bounded, shutdown-visible media child in its own process group."""
    with _active_media_processes_lock:
        if _media_process_runtime_stopping:
            raise ManagedProcessUnavailable("Media processing is shutting down")
        # Spawn and registration share the shutdown lock so a child can never
        # appear after shutdown has taken its final active-process snapshot.
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture_stderr else subprocess.DEVNULL,
            start_new_session=True,
        )
        _active_media_processes.add(process)
    stdout_capture = None
    stderr_capture = None
    timed_out = False
    returncode = -1
    stdout_bytes = b""
    stderr_bytes = b""
    stdout_truncated = False
    stderr_truncated = False
    try:
        if capture_stdout:
            assert process.stdout is not None
            stdout_capture = _BoundedPipeCapture(
                process.stdout, stdout_limit_bytes, keep_tail=False,
            )
            stdout_capture.start()
        if capture_stderr:
            assert process.stderr is not None
            stderr_capture = _BoundedPipeCapture(
                process.stderr, stderr_limit_bytes, keep_tail=stderr_tail,
            )
            stderr_capture.start()
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = _terminate_media_process(process, terminate_grace_seconds)
    finally:
        try:
            if process.poll() is None:
                _terminate_media_process(process, terminate_grace_seconds)
        finally:
            if stdout_capture is not None:
                stdout_bytes, stdout_truncated = stdout_capture.finish()
            if stderr_capture is not None:
                stderr_bytes, stderr_truncated = stderr_capture.finish()
            _untrack_media_process(process)

    result = ManagedProcessResult(
        returncode=returncode,
        stdout=stdout_bytes.decode("utf-8", errors="replace") if decode_stdout else "",
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
    )
    if timed_out:
        raise ManagedProcessTimeout(timeout_seconds, result)
    return result


def low_memory_mode() -> bool:
    """Return whether FFmpeg should bound parallel work for hosted renders."""
    enabled = {"1", "true", "yes", "on"}
    return any(
        os.getenv(name, "").strip().lower() in enabled
        for name in ("RENDER", "PBJ_HOSTED_MODE", "PBJ_LOW_MEMORY_MODE")
    )


def global_options() -> List[str]:
    if not low_memory_mode():
        return []
    return ["-filter_threads", "1", "-filter_complex_threads", "1"]


def input_options() -> List[str]:
    """Bound per-input probing buffers when one timeline opens many clips."""
    if not low_memory_mode():
        return []
    return ["-threads", "1", "-probesize", "1M", "-analyzeduration", "2M"]


def video_encoder_options() -> List[str]:
    if not low_memory_mode():
        return ["-preset", "medium"]
    return [
        # Preserve the normal quality/size profile while preventing FFmpeg from
        # decoding, filtering, and encoding many phone clips in parallel.
        "-preset", "medium", "-threads", "1",
        "-x264-params", "threads=1:lookahead_threads=1:sync-lookahead=0",
    ]
