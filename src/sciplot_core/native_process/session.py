"""One serial native process, with bounded lifetime and fail-closed disconnection."""

import atexit
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import os
import select
import subprocess
import sys
import tempfile
import threading
from time import monotonic
from typing import BinaryIO, ClassVar
from uuid import uuid4
from weakref import WeakSet

from sciplot_core.veusz_runtime import veusz_worker_environment

from .protocol import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, decode, encode, validate_request, validate_response
from .identity import current_identity

_ACTIVE: ContextVar["PersistentWorker | None"] = ContextVar("sciplot_native_worker", default=None)
_WORKERS: WeakSet["PersistentWorker"] = WeakSet()


class NativeWorkerDisconnected(RuntimeError):
    reason_code = "native_worker_disconnected"


class NativeRuntimeChanged(RuntimeError):
    reason_code = "native_runtime_changed"
    repair: ClassVar[dict[str, str | bool]] = {"action": "restart_local_plot_service", "automatic_retry": False}


class PersistentWorker:
    def __init__(self, *, max_requests: int = 128, worker_command: list[str] | None = None) -> None:
        if type(max_requests) is not int or max_requests < 1:
            raise ValueError("max_requests must be a positive integer.")
        self.max_requests = max_requests
        self.worker_command = worker_command or [sys.executable, "-m", "sciplot_core.veusz_worker.persistent"]
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr: BinaryIO | None = None
        self._lock = threading.Lock()
        self._completed = 0
        self._closed = False
        self.last_pid: int | None = None
        self.starts = 0
        self._runtime_identity: str | None = None
        _WORKERS.add(self)

    def require_current_runtime(self, observed: str | None = None) -> str:
        current = current_identity() if observed is None else observed
        if self._runtime_identity is not None and current != self._runtime_identity:
            raise NativeRuntimeChanged("Native implementation or runtime changed; restart the local plotting service before continuing.")
        return current

    @contextmanager
    def activate(self) -> Iterator[None]:
        token = _ACTIVE.set(self)
        try:
            yield
        finally:
            _ACTIVE.reset(token)

    def _start(self) -> subprocess.Popen[bytes]:
        if self._closed:
            raise NativeWorkerDisconnected("The native worker session has been closed.")
        if self._process is not None and (self._process.poll() is not None or self._completed >= self.max_requests):
            self._stop()
        if self._process is None:
            self._runtime_identity = self.require_current_runtime()
            self._stderr = tempfile.TemporaryFile()
            self._process = subprocess.Popen(self.worker_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self._stderr, env=veusz_worker_environment(), bufsize=0)
            self._completed = 0
            self.starts += 1
            self.last_pid = self._process.pid
        return self._process

    def _diagnostic(self) -> str:
        if self._stderr is None:
            return ""
        self._stderr.seek(0)
        return self._stderr.read(65536).decode(errors="replace")

    def _stop(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            for pipe in (process.stdin, process.stdout):
                if pipe is not None:
                    pipe.close()
        if self._stderr is not None:
            self._stderr.close()
            self._stderr = None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop()

    def __del__(self) -> None:
        if hasattr(self, "_process"):
            self._stop()

    def run(self, command: list[str], *, timeout: float = 120, check: bool = False) -> subprocess.CompletedProcess[str]:
        if command[:3] != [sys.executable, "-m", "sciplot_core.veusz_worker"]:
            raise ValueError("Only the existing native worker entry point may use this session.")
        request_id = uuid4().hex
        request = {"id": request_id, "argv": command[3:]}
        validate_request(request)
        encoded = encode(request)
        if len(encoded) > MAX_REQUEST_BYTES or not 0 < timeout <= 3600:
            raise ValueError("The native request or deadline exceeds its bounds.")
        deadline = monotonic() + timeout
        if not self._lock.acquire(timeout=timeout):
            raise subprocess.TimeoutExpired(command, timeout)
        try:
            self.require_current_runtime()
            process = self._start()
            assert process.stdin is not None and process.stdout is not None
            pending = memoryview(encoded)
            while pending:
                remaining = deadline - monotonic()
                if remaining <= 0 or not select.select([], [process.stdin], [], remaining)[1]:
                    raise subprocess.TimeoutExpired(command, timeout)
                count = os.write(process.stdin.fileno(), pending[:4096])
                pending = pending[count:]
            chunks = bytearray()
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                    raise subprocess.TimeoutExpired(command, timeout, output=bytes(chunks), stderr=self._diagnostic())
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    raise NativeWorkerDisconnected("The native worker disconnected; no command was automatically repeated. " + self._diagnostic()[-2000:])
                chunks.extend(chunk)
                if len(chunks) > MAX_RESPONSE_BYTES:
                    raise NativeWorkerDisconnected("The native worker response exceeded its bounded transport.")
                if b"\n" in chunks:
                    if not chunks.endswith(b"\n") or chunks.count(b"\n") != 1:
                        raise NativeWorkerDisconnected("The native worker returned an invalid response frame.")
                    payload = validate_response(decode(bytes(chunks)), request_id)
                    if payload["pid"] != process.pid:
                        raise NativeWorkerDisconnected("The native response came from a different process.")
                    result = subprocess.CompletedProcess(command, payload["returncode"], payload["stdout"], payload["stderr"])
                    self.require_current_runtime()
                    self._completed += 1
                    if check:
                        result.check_returncode()
                    return result
        except subprocess.CalledProcessError:
            raise
        except (ValueError, UnicodeError, OSError) as exc:
            self._stop()
            raise NativeWorkerDisconnected("The native worker transport failed; no command was automatically repeated.") from exc
        except BaseException:
            self._stop()
            raise
        finally:
            self._lock.release()


def active_worker() -> PersistentWorker | None:
    return _ACTIVE.get()


def verified_runtime_identity() -> str:
    """Do not label old loaded worker code with newly observed recipe bytes."""
    observed = current_identity()
    for worker in tuple(_WORKERS):
        if not worker._closed:
            worker.require_current_runtime(observed)
    return observed


def _close_workers() -> None:
    for worker in tuple(_WORKERS):
        worker.close()


atexit.register(_close_workers)
