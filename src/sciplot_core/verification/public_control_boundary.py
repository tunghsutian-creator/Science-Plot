"""Finite source-owned generated observer launch, only in a verified stage.

This removes CPython startup enforcement for the generated observer subtree so
its genuine missing-hook controls can execute. Private inputs must be absent;
this port does not claim OS isolation or complete native access observation.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import inspect
import json
import os
from pathlib import Path
import sys
from types import CodeType
from typing import Any, Iterator

from sciplot_core.verification.public_stage import validate_stage

_grant: ContextVar[dict[str, Any] | None] = ContextVar("sciplot_generated_observer_launch", default=None)
_KEYS = ("SCIPLOT_PUBLIC_INPUT_GUARD", "SCIPLOT_PUBLIC_GUARD_BOOTSTRAP", "SCIPLOT_PUBLIC_GUARD_WRAPPER_BOOTSTRAP")


def _owned_caller(root: Path, filename: str, function: str) -> bool:
    from sciplot_core.verification.private_process_boundaries import _code_hash

    path = root / filename
    compiled = compile(path.read_bytes(), str(path), "exec", dont_inherit=True, optimize=sys.flags.optimize)
    owned = next((code for code in compiled.co_consts if isinstance(code, CodeType) and code.co_name == function), None)
    frame = inspect.currentframe()
    try:
        while frame is not None:
            if (frame.f_code.co_name == function and Path(frame.f_code.co_filename).resolve() == path.resolve()
                    and owned is not None and _code_hash(frame.f_code) == _code_hash(owned)):
                return True
            frame = frame.f_back
    finally:
        del frame
    return False


def _generated_test_caller(root: Path) -> bool:
    from sciplot_core.verification.private_process_boundaries import _code_hash

    frame = inspect.currentframe()
    try:
        for filename in ("tests/test_private_observer.py", "tests/test_private_observer_native.py"):
            path = root / filename
            module = compile(path.read_bytes(), str(path), "exec", dont_inherit=True, optimize=sys.flags.optimize)
            owned = {code.co_name: code for code in module.co_consts if isinstance(code, CodeType) and code.co_name.startswith("test_")}
            current = frame
            while current is not None:
                code = owned.get(current.f_code.co_name)
                if code is not None and Path(current.f_code.co_filename).resolve() == path and _code_hash(code) == _code_hash(current.f_code):
                    return True
                current = current.f_back
    finally:
        del frame
    return False


def _generated_port(root: Path) -> bool:
    return _generated_test_caller(root) and (
        _owned_caller(root, "tests/private_observer_support.py", "execute_observed")
        or _owned_caller(root, "tests/private_observer_support.py", "launch_generated_suite"))


@contextmanager
def generated_control(environment: dict[str, str], command: list[str], cwd: Path, *, durable: bool,
                      directory: Path | None = None) -> Iterator[dict[str, str]]:
    """Owned test-helper port; ordinary callers cannot waive startup guards."""
    if not os.environ.get(_KEYS[0]):
        yield environment
        return
    root = Path(__file__).resolve().parents[3]
    if not _generated_port(root):
        raise PermissionError("Only the source-owned generated observer helper can use this port.")
    before = validate_stage(root, dict(os.environ))
    # Check the real launch environment too; a caller cannot quietly inherit a
    # second source/reference/runtime namespace through an explicit child env.
    validate_stage(root, environment)
    if durable and (directory is None or not directory.absolute().is_relative_to(cwd.absolute() / ".tmp_verify")):
        raise ValueError("Generated durable launch must bind its exact ignored directory.")
    child = {key: value for key, value in environment.items() if key not in _KEYS}
    token = _grant.set({"root": root, "command": list(command), "cwd": cwd.absolute(),
                        "environment": child, "durable": durable, "directory": directory.absolute() if directory is not None else None})
    try:
        yield child
    finally:
        _grant.reset(token)
        if validate_stage(root, dict(os.environ)) != before:
            raise ValueError("Generated observer source-stage closure changed.")


def generated_launch_allowed(executable: Any, arguments: list[Any], cwd: Any, environment: Any) -> bool:
    """Called by each installed guard; authorization remains process-local."""
    grant = _grant.get()
    if grant is None or not isinstance(environment, dict):
        return False
    root = grant["root"]
    if not _generated_port(root):
        return False
    if Path(os.fsdecode(executable)).resolve() != Path(sys.executable).resolve() or Path(cwd or Path.cwd()).absolute() != grant["cwd"]:
        return False
    expected = grant["environment"]
    ignored = {"SCIPLOT_PRIVATE_AUDIT_PARENT", "SCIPLOT_PRIVATE_AUDIT_CHILD", "SCIPLOT_VERIFY_FINISH"}
    if any(key in environment for key in _KEYS) or {key: value for key, value in environment.items() if key not in ignored} != {
            key: value for key, value in expected.items() if key not in ignored}:
        return False
    if grant["durable"]:
        if not _owned_caller(root, "src/sciplot_core/verification/durable_runner.py", "start_run"):
            return False
        if arguments[:3] != [sys.executable, "-m", "sciplot_core.verification.durable_runner"] or len(arguments) != 5:
            return False
        directory = Path(str(arguments[3]))
        if directory != grant["directory"]:
            return False
        request = json.loads((directory / "request.json").read_bytes())
        return bool(request.get("command") == grant["command"] and request.get("repo_root") == str(grant["cwd"]))
    return bool(arguments == grant["command"])
