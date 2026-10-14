"""One task-local detached verification command, with immutable completion.

No scheduler, automatic retries, process killing or network publication. Reopen
the same directory to inspect a disconnected run; never start it a second time.
Requests contain local paths and must stay in ignored local storage. Environment
values are inherited by the supervisor but only their hash is persisted.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.verification.evidence import ARTIFACT_NAMES, atomic_json, load_receipt, make_receipt
from sciplot_core.verification.evidence_identity import capture_identity, digest

def artifact_hashes(directory: Path) -> dict[str, str]:
    """Hash known execution files, never paths supplied by a receipt."""
    if any((directory / name).is_symlink() for name in ARTIFACT_NAMES):
        raise ValueError("execution artifacts cannot be symlinks")
    return {name: file_sha256(directory / name) for name in sorted(ARTIFACT_NAMES)}


def _capture(spec: dict[str, Any], environment: dict[str, str]) -> dict[str, Any]:
    arguments = {key: value for key, value in spec.items() if key != "environment_sha256"}
    return capture_identity(**{**arguments, "environment": environment,
                               "repo_root": Path(spec["repo_root"])})


def prepare_run(*, directory: Path, spec: dict[str, Any]) -> tuple[Path, dict[str, str], str]:
    """Reserve an immutable original request; no process is launched here.

``spec`` is exactly capture_identity's keyword arguments (repo_root a string).
For pytest, command must explicitly load ``sciplot_core.verification.pytest_finish``
and selected_tests must contain collected nodeids, in execution order. Pass the
complete effective child environment; this function adds its bound finish path.
"""
    directory = directory.expanduser().resolve()
    root = Path(spec["repo_root"]).expanduser().resolve()
    if not directory.is_relative_to(root / ".tmp_verify"):
        raise ValueError("durable evidence must remain under repository .tmp_verify")
    if directory.exists():
        raise FileExistsError("run directory already exists; inspect its status")
    # Evidence cannot be one of its own dependencies, even indirectly.
    for binding in spec["inputs"].values():
        for name in binding.get("paths", []):
            path = Path(name).expanduser()
            path = (path if path.is_absolute() else root / path).resolve()
            if directory.is_relative_to(path) or path.is_relative_to(directory):
                raise ValueError("execution artifacts overlap identity inputs")
    spec = json.loads(json.dumps(spec, allow_nan=False))
    spec["repo_root"] = str(root)
    from sciplot_core.verification.private_observer import reserve_child_environment

    environment = spec.pop("environment")
    environment["SCIPLOT_VERIFY_FINISH"] = str(directory / "finish.json")
    environment = reserve_child_environment(environment)
    spec["environment_sha256"] = digest(environment)
    if spec["scope"]["kind"] == "pytest":
        command = spec["command"]
        if not any(command[index:index + 2] == ["-p", "sciplot_core.verification.pytest_finish"]
                   for index in range(len(command) - 1)):
            raise ValueError("pytest command must load the session-finish plugin")
    _capture(spec, environment)  # Refuse incomplete identity before launching work.
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    atomic_json(directory / "request.json", spec)
    request_hash = file_sha256(directory / "request.json")
    return directory, environment, request_hash


def start_run(*, directory: Path, spec: dict[str, Any]) -> dict[str, Any]:
    """Prepare and launch one transport-independent original supervisor."""
    directory, environment, request_hash = prepare_run(directory=directory, spec=spec)
    root = Path(spec["repo_root"]).expanduser().resolve()
    with (directory / "supervisor.log").open("xb") as stream:
        child = subprocess.Popen(
            [sys.executable, "-m", __name__, str(directory), request_hash], cwd=root,
            env=environment, stdin=subprocess.DEVNULL,
            stdout=stream, stderr=subprocess.STDOUT, close_fds=True,
            start_new_session=True,
        )
    # Separate launch metadata avoids racing the supervisor's status writer.
    atomic_json(directory / "launch.json", {"supervisor_pid": child.pid,
                                            "request_sha256": request_hash})
    return {"status": "RUNNING", "reused": False, "directory": str(directory),
            "supervisor_pid": child.pid}


def run_status(directory: Path) -> dict[str, Any]:
    """Read status only; disconnection never launches or repeats a command."""
    state = load_receipt(directory / "state.json")
    if not isinstance(state, dict):
        launch = load_receipt(directory / "launch.json")
        try:
            if not isinstance(launch, dict) or set(launch) != {"supervisor_pid", "request_sha256"} or type(launch["supervisor_pid"]) is not int or launch["supervisor_pid"] <= 0:
                raise ValueError("invalid launch")
            if (directory / "request.json").is_symlink() or file_sha256(directory / "request.json") != launch["request_sha256"]:
                raise ValueError("request drift")
            os.kill(launch["supervisor_pid"], 0)
            return {"status": "RUNNING", "reused": False, "reason": "supervisor_starting",
                    "supervisor_pid": launch["supervisor_pid"]}
        except (OSError, KeyError, TypeError, ValueError, OverflowError):
            return {"status": "BLOCKED", "reused": False, "reason": "completion_unavailable"}
    if state.get("phase") == "completed":
        receipt = load_receipt(directory / "receipt.json")
        if not isinstance(receipt, dict) or digest(receipt) != state.get("receipt_digest"):
            return {"status": "BLOCKED", "reused": False, "reason": "receipt_drift"}
        try:
            if artifact_hashes(directory) != receipt.get("artifacts"):
                raise ValueError("execution artifact drift")
            # Validate internal receipt even for failed runs, without claiming reuse.
            rebuilt = make_receipt(**{key: receipt[key] for key in (
                "before", "after", "exit_code", "session_finish", "wall_seconds", "artifacts", "provenance",
            )})
            if receipt != rebuilt:
                raise ValueError("receipt malformed")
            completion = load_receipt(directory / "completion.json")
            if not isinstance(completion, dict) or completion.get("exit_code") != receipt["exit_code"]:
                raise ValueError("original wait completion differs from receipt")
            # Legacy receipts remain readable, but supported capture separately
            # requires both actual PIDs sealed by the immutable artifact hash.
            if {"child_pid", "supervisor_pid"} & completion.keys() and any(
                    type(completion.get(key)) is not int or completion[key] <= 0
                    or completion[key] != state.get(key) for key in ("child_pid", "supervisor_pid")):
                raise ValueError("mutable progress PID differs from original wait completion")
            return {"status": receipt["status"], "reused": False, "reason": receipt["reason"],
                    "wall_seconds": receipt["wall_seconds"], "claim": "original_execution_only",
                    "scope": receipt["before"]["scope"],
                    "selected_tests": receipt["before"]["selected_tests"]}
        except (OSError, TypeError, KeyError, ValueError):
            return {"status": "BLOCKED", "reused": False, "reason": "evidence_drift"}
    if state.get("phase") == "blocked":
        return {"status": "BLOCKED", "reused": False, "reason": state.get("reason", "supervisor_failed")}
    if state.get("phase") != "running" or type(state.get("supervisor_pid")) is not int or state["supervisor_pid"] <= 0:
        return {"status": "BLOCKED", "reused": False, "reason": "invalid_run_state"}
    try:
        os.kill(state["supervisor_pid"], 0)
    except (OSError, KeyError, TypeError, OverflowError):
        return {"status": "BLOCKED", "reused": False, "reason": "supervisor_interrupted"}
    return {"status": "RUNNING", "reused": False, "reason": "completion_not_yet_proven",
            "supervisor_pid": state["supervisor_pid"]}


def supervise(directory: Path, expected_request_hash: str) -> int:
    """Execute once. No completion receipt exists after abrupt interruption."""
    started = time.monotonic()
    state = {"phase": "running", "supervisor_pid": os.getpid()}
    atomic_json(directory / "state.json", state)
    try:
        request_hash = file_sha256(directory / "request.json")
        if request_hash != expected_request_hash:
            raise ValueError("request changed before execution")
        spec = load_receipt(directory / "request.json")
        if not isinstance(spec, dict):
            raise ValueError("invalid request")
        environment = dict(os.environ)
        if digest(environment) != spec["environment_sha256"]:
            raise ValueError("supervisor environment differs from requested environment")
        from sciplot_core.verification.private_observer import reserve_child_environment

        environment = reserve_child_environment(environment)
        capture_started = time.monotonic()
        before = _capture(spec, environment)
        command_started = time.monotonic()
        with (directory / "command.log").open("xb") as stream:
            child = subprocess.Popen(spec["command"], cwd=spec["repo_root"],
                                     env=environment, stdin=subprocess.DEVNULL,
                                     stdout=stream, stderr=subprocess.STDOUT,
                                     close_fds=True, start_new_session=True)
            state["child_pid"] = child.pid
            atomic_json(directory / "state.json", state)
            code = child.wait()
            stream.flush()
            os.fsync(stream.fileno())
        command_ended = time.monotonic()
        after = _capture(spec, environment)
        capture_ended = time.monotonic()
        if request_hash != file_sha256(directory / "request.json"):
            raise ValueError("request changed during execution")
        if spec["scope"]["kind"] != "pytest":
            atomic_json(directory / "finish.json", {"complete": True, "exit_code": code,
                                                   "selected_tests": spec["selected_tests"]})
        finish = load_receipt(directory / "finish.json")
        if finish is not None and not isinstance(finish, dict):
            raise ValueError("session finish is malformed")
        if finish is None:
            atomic_json(directory / "finish.json", {"complete": False})
        wall = time.monotonic() - started
        timings = {"capture_before_seconds": command_started - capture_started,
                   "command_seconds": command_ended - command_started,
                   "capture_after_seconds": capture_ended - command_ended}
        # Completion is immutable and precedes receipt; state is deliberately
        # excluded from the receipt to avoid circular hashes.
        atomic_json(directory / "completion.json", {
            "exit_code": code, "child_pid": child.pid, "supervisor_pid": os.getpid(),
            "before_sha256": before["sha256"],
            "after_sha256": after["sha256"], "wall_seconds": wall, "timings": timings,
        })
        receipt = make_receipt(before=before, after=after, exit_code=code,
                               session_finish=finish, wall_seconds=wall,
                               artifacts=artifact_hashes(directory), provenance={"timings": timings})
        atomic_json(directory / "receipt.json", receipt)
        atomic_json(directory / "state.json", {**state, "phase": "completed",
                                              "receipt_digest": digest(receipt)})
        return 0 if receipt["status"] == "PASS" else 1
    except Exception as exc:
        # Error text can reveal private paths; local log retains traceback class only.
        atomic_json(directory / "state.json", {**state, "phase": "blocked",
                                              "reason": type(exc).__name__})
        return 1


if __name__ == "__main__":
    sys.exit(supervise(Path(sys.argv[1]), sys.argv[2]))
