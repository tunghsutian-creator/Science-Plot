"""Opt-in synchronous Python access evidence; never record arguments or data."""
from __future__ import annotations

import atexit
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, NoReturn
from uuid import uuid4

from sciplot_core.verification.private_process_boundaries import diagnostic_owner, executable_hash, owned_caller, root_scope, runtime_identity, uname_call, wrapper_call, wrapper_inputs

VERSION = 2
DIRECTORY = "SCIPLOT_PRIVATE_AUDIT_DIR"
ROOTS = "SCIPLOT_PRIVATE_AUDIT_ROOTS"
RUN = "SCIPLOT_PRIVATE_AUDIT_RUN"
PARENT = "SCIPLOT_PRIVATE_AUDIT_PARENT"
CHILD = "SCIPLOT_PRIVATE_AUDIT_CHILD"
CONTINUATION = "SCIPLOT_PRIVATE_AUDIT_CONTINUATION"
ZERO = "0" * 64
_SITE = ("import os\ntry:\n"
         "    from sciplot_core.verification.private_observer import install\n    install()\n"
         "    if os.environ.get('SCIPLOT_PUBLIC_INPUT_GUARD'):\n"
         "        from sciplot_core.verification.public_input_guard import install as install_guard\n"
         "        install_guard()\nexcept Exception:\n    os._exit(78)\n")
_PYTEST = "from sciplot_core.verification.private_observer_pytest import *\n"
_observer: Observer | None = None


def frame_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def source_hashes() -> dict[str, str]:
    names = ["private_observer.py", "private_observer_pytest.py", "private_capture.py", "private_process_boundaries.py",
             "suite_evidence.py", "durable_runner.py", "evidence_identity.py", "private_corpus.py"]
    public = Path(__file__).parent / "public_guard_bootstrap/sitecustomize.py"
    if public.is_file():
        names.append("public_guard_bootstrap/sitecustomize.py")
    result = {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() for name in names}
    result["repository:skill/scripts/sciplot"] = hashlib.sha256((Path(__file__).parents[3] / "skill/scripts/sciplot").read_bytes()).hexdigest()
    return result


def bootstrap_sources() -> dict[str, str]:
    return {"sitecustomize.py": _SITE, "sciplot_closure_audit.py": _PYTEST}


def bootstrap_hashes() -> dict[str, str]:
    result = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in bootstrap_sources().items()}
    public = Path(__file__).parent / "public_guard_bootstrap/sitecustomize.py"
    if public.is_file():
        result["public_guard_bootstrap/sitecustomize.py"] = hashlib.sha256(public.read_bytes()).hexdigest()
    return result




class Observer:
    def __init__(self, environment: dict[str, str], *, activation: dict[str, str] | None = None) -> None:
        self.directory = Path(environment[DIRECTORY]).resolve(strict=True)
        roots = json.loads(environment[ROOTS])
        if not isinstance(roots, list) or not roots or not all(isinstance(p, str) and Path(p).is_absolute() for p in roots):
            raise ValueError("Audit roots must be absolute paths.")
        self.root_scope = root_scope(roots)
        self.roots = tuple(Path(p) for group in self.root_scope.values() for p in group)
        self.run = environment.get(RUN) or uuid4().hex
        self.wrapper_environment = dict(environment)
        self.epoch = uuid4().hex
        self.nodeid: str | None = None
        self.sequence, self.lost, self.head = 0, 0, ZERO
        self.lock = threading.RLock()
        self.reserved: dict[str, str] = {}
        self.guard = threading.local()
        self.writer, self.sync = os.write, os.fsync
        self.fd = os.open(self.directory / f"{self.epoch}.jsonl",
                          os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
        os.set_inheritable(self.fd, False)
        self.pending = self.directory / f"{self.epoch}.pending"
        self.sealed = False
        self._mark_pending()
        continuation = json.loads(environment.get(CONTINUATION, "null"))
        os.environ[RUN] = self.run
        os.environ.pop(CONTINUATION, None)
        bootstrap = getattr(sys.modules.get("sitecustomize"), "__file__", None)
        self.record({"event": "process_start", "parent_epoch": environment.get(PARENT),
                     "child_token": environment.get(CHILD), "continuation": continuation,
                     "observer_sources_sha256": source_hashes(),
                     "root_scope": self.root_scope,
                     "python_runtime": runtime_identity(),
                     "wrapper_inputs": wrapper_inputs(environment),
                     "bootstrap_sha256": executable_hash(bootstrap) if bootstrap else None,
                     "activation": activation,
                     "no_site": bool(sys.flags.no_site), "isolated": bool(sys.flags.isolated),
                     "executable_sha256": executable_hash(sys.executable)}, sync=True)

    def _mark_pending(self) -> None:
        """Independent incomplete state precedes every possibly lost frame."""
        if self.pending.exists():
            return
        descriptor = os.open(self.pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._sync_directory()

    def _sync_directory(self) -> None:
        descriptor = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _close_pending(self) -> None:
        try:
            self.pending.unlink()
            self._sync_directory()
        except OSError:
            try:
                self._mark_pending()
            except OSError:
                os._exit(79)
            raise
        self.sealed = True

    def record(self, value: dict[str, Any], *, sync: bool = False) -> dict[str, Any] | None:
        if getattr(self.guard, "active", False):
            return None
        self.guard.active = True
        try:
            with self.lock:
                if self.sealed:
                    try:
                        self._mark_pending()
                    except OSError:
                        # An already closed stream cannot truthfully remain closed
                        # if its next operation cannot persist incomplete state.
                        os._exit(79)
                    self.sealed = False
                if value.get("event") in {"process_finish", "exec_seal"}:
                    value = {**value, "recorded_events": self.sequence, "lost_events": self.lost}
                frame = {**value, "version": VERSION, "run_id": self.run, "epoch": self.epoch,
                         "pid": os.getpid(), "parent_pid": os.getppid(), "sequence": self.sequence,
                         "previous_sha256": self.head, "lost_events_before": self.lost,
                         "monotonic_ns": time.monotonic_ns(),
                         "nodeid": self.nodeid or os.environ.get("PYTEST_CURRENT_TEST", "")}
                frame["sha256"] = frame_digest(frame)
                pending = memoryview((json.dumps(frame, sort_keys=True) + "\n").encode())
                while pending:
                    try:
                        count = self.writer(self.fd, pending)
                    except InterruptedError:
                        continue
                    if count <= 0 or count > len(pending):
                        raise OSError("Audit write did not make progress.")
                    pending = pending[count:]
                self.sequence += 1
                self.head = frame["sha256"]
                if sync or value.get("event") in {"process_finish", "exec_seal"}:
                    self.sync(self.fd)
                if value.get("event") in {"process_finish", "exec_seal"} and self.lost == 0:
                    self._close_pending()
                return frame
        except (OSError, TypeError, ValueError):
            self.lost += 1
            return None
        finally:
            self.guard.active = False

    def observe(self, event: str, args: tuple[Any, ...]) -> None:
        if getattr(self.guard, "active", False):
            return
        if event in {"open", "os.scandir", "os.listdir"} and args:
            value = args[0]
            if isinstance(value, (str, bytes, os.PathLike)):
                path = Path(os.path.abspath(os.fsdecode(value)))
                resolved = path.resolve()
                if any(path.is_relative_to(root) or resolved.is_relative_to(root) for root in self.roots):
                    diagnostic = diagnostic_owner()
                    self.record({"event": event, "path": str(path), "resolved_path": str(resolved),
                                 "diagnostic_owner": diagnostic})
        elif event in {"os.fork", "os.posix_spawn", "subprocess.Popen"} and not getattr(self.guard, "spawning", False):
            self.record({"event": "unsupported_spawn", "mechanism": event})
        elif event == "os.exec" and not getattr(self.guard, "executing", False):
            self.record({"event": "unsupported_exec"})

    def finish(self) -> None:
        if self.record({"event": "process_finish"}, sync=True) is None:
            self.record({"event": "sensor_failure", "operation": "terminal_write_or_sync"})


def current_observer() -> Observer | None:
    return _observer


def reserve_child_environment(environment: dict[str, str]) -> dict[str, str]:
    """Bind launch propagation before an owner hashes the effective environment."""
    observer = current_observer()
    result = dict(environment)
    if observer is not None and result.get(DIRECTORY) == str(observer.directory):
        token = uuid4().hex
        result.update({PARENT: observer.epoch, CHILD: token})
        observer.reserved[token] = frame_digest(result)
    return result


def _install_process_ports(observer: Observer) -> None:
    original_init, original_wait, original_poll = subprocess.Popen.__init__, subprocess.Popen.wait, subprocess.Popen.poll
    spawn_signature = inspect.signature(original_init)
    children: dict[int, tuple[str, subprocess.Popen[Any]]] = {}

    def spawn(process: subprocess.Popen[Any], *args: Any, **kwargs: Any) -> None:
        token = uuid4().hex
        bound = spawn_signature.bind(process, *args, **kwargs)
        explicit = bound.arguments.get("env")
        environment = dict(os.environ if explicit is None else explicit)
        same_scope = environment.get(DIRECTORY) == str(observer.directory)
        if same_scope:
            reserved = environment.get(CHILD, "")
            if (environment.get(PARENT) == observer.epoch
                    and observer.reserved.pop(reserved, None) == frame_digest(environment)):
                token = reserved
            environment.update({PARENT: observer.epoch, CHILD: token})
        # Preserve explicit scope/propagation failures. Never silently restore a
        # removed audit path, plugin or run identity on behalf of a caller.
        bound.arguments["env"] = environment
        command = bound.arguments.get("args")
        target = bound.arguments.get("executable") or (command[0] if isinstance(command, (list, tuple)) else command)
        target_hash = executable_hash(target, cwd=bound.arguments.get("cwd"), environment=environment) if isinstance(target, (str, bytes, os.PathLike)) else None
        # Evaluate the finite boundary against original invocation inputs, before
        # inserting any audit propagation environment into the launch.
        bound.arguments["env"] = explicit
        input_boundary = uname_call(bound, target_hash) or wrapper_call(bound, environment, observer.wrapper_environment)
        bound.arguments["env"] = environment
        if input_boundary and input_boundary.get("kind") == "owned_sciplot_python_exec":
            target_hash = input_boundary["expected_python_sha256"]
        transfer = owned_caller("durable_runner.py", "start_run")
        if not (transfer and isinstance(command, list) and len(command) == 5
                and command[:3] == [sys.executable, "-m", "sciplot_core.verification.durable_runner"]
                and bound.arguments.get("start_new_session") is True):
            transfer = None
        observer.record({"event": "spawn_attempt", "child_token": token, "expected_executable_sha256": target_hash,
                         "argv_sha256": frame_digest({"argv": [os.fsdecode(value) for value in command]}) if isinstance(command, (list, tuple)) else None,
                         "same_capture_scope": same_scope, "input_boundary": input_boundary,
                         "durable_transfer_owner": transfer,
                         "request_sha256": command[-1] if transfer and isinstance(command, list) else None,
                         "directory_sha256": frame_digest({"directory": str(Path(command[-2]).resolve())}) if transfer and isinstance(command, list) else None})
        observer.guard.spawning = True
        try:
            original_init(*bound.args, **bound.kwargs)
        except BaseException as exc:
            observer.record({"event": "spawn_failed", "child_token": token, "error_class": type(exc).__name__})
            raise
        finally:
            observer.guard.spawning = False
        process.__dict__["_sciplot_audit_child"] = token
        children[process.pid] = token, process
        observer.record({"event": "child_spawn", "child_token": token, "child_pid": process.pid})
        observed_exit(process, process.returncode)

    def observed_exit(process: subprocess.Popen[Any], code: int | None) -> None:
        token = getattr(process, "_sciplot_audit_child", None)
        if code is not None and token and not getattr(process, "_sciplot_audit_exit", False):
            process.__dict__["_sciplot_audit_exit"] = True
            observer.record({"event": "child_exit", "child_token": token,
                             "child_pid": process.pid, "returncode": code})
            children.pop(process.pid, None)

    def wait(process: subprocess.Popen[Any], *args: Any, **kwargs: Any) -> int:
        result = original_wait(process, *args, **kwargs)
        observed_exit(process, result)
        return result

    def poll(process: subprocess.Popen[Any], *args: Any, **kwargs: Any) -> int | None:
        result = original_poll(process, *args, **kwargs)
        observed_exit(process, result)
        return result

    for name, method in (("__init__", spawn), ("wait", wait), ("poll", poll)):
        setattr(subprocess.Popen, name, method)
    original_waitpid = os.waitpid

    def waitpid(pid: int, options: int) -> tuple[int, int]:
        result = original_waitpid(pid, options)
        if result[0] in children:
            observed_exit(children[result[0]][1], os.waitstatus_to_exitcode(result[1]))
        return result

    os.waitpid = waitpid
    originals = {"execve": os.execve, "execvpe": os.execvpe}

    def exec_port(name: str, file: Any, argv: Any, environment: Any) -> NoReturn:
        if getattr(observer.guard, "executing", False):
            originals[name](file, argv, environment)
        token = uuid4().hex
        successor_environment = dict(environment)
        seal = observer.record({"event": "exec_seal", "successor_token": token,
                                "expected_executable_sha256": executable_hash(file, environment=successor_environment)}, sync=True)
        if seal is not None:
            successor_environment[CONTINUATION] = json.dumps({"epoch": observer.epoch, "sha256": seal["sha256"],
                "sequence": seal["sequence"], "successor_token": token})
        observer.guard.executing = True
        try:
            originals[name](file, argv, successor_environment)
        except BaseException as exc:
            observer.record({"event": "exec_failed", "successor_token": token, "error_class": type(exc).__name__})
            raise
        finally:
            observer.guard.executing = False

    for name in originals:
        def execute(file: Any, argv: Any, env: Any, *, _name: str = name) -> NoReturn:
            exec_port(_name, file, argv, env)
        setattr(os, name, execute)


def install() -> Observer | None:
    """Disabled unless both explicit audit settings are present at startup."""
    global _observer
    if _observer is not None:
        return _observer
    if not os.environ.get(DIRECTORY) or not os.environ.get(ROOTS):
        return None
    observer = Observer(dict(os.environ))
    _observer = observer
    sys.addaudithook(observer.observe)
    _install_process_ports(observer)
    atexit.register(observer.finish)
    return observer


def begin_suite_audit(environment: dict[str, str]) -> Observer:
    """Start the bounded suite operation at its existing configuration owner."""
    global _observer
    activation = owned_caller("suite_evidence.py", "_audit_environment")
    if activation is None:
        raise ValueError("Suite audit activation requires its source-bound configuration owner.")
    if _observer is not None:
        if environment[DIRECTORY] != str(_observer.directory):
            _observer.record({"event": "scope_boundary_requested"})
        return _observer
    for key in (DIRECTORY, ROOTS, RUN):
        os.environ[key] = environment[key]
    observer = Observer(environment, activation=activation)
    _observer = observer
    sys.addaudithook(observer.observe)
    _install_process_ports(observer)
    atexit.register(observer.finish)
    return observer


def write_bootstrap(directory: Path) -> None:
    """Create a fresh source-bound thin bootstrap for the existing audit CLI."""
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "sitecustomize.py").write_text(_SITE)
    (directory / "sciplot_closure_audit.py").write_text(_PYTEST)
