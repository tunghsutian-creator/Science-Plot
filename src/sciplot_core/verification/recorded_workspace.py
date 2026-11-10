"""Allocate persistent generated pytest data before recorded identity capture.

The receipt directory and generated data have different lifecycles. This owner
never deletes a workspace, including one whose collection or execution failed.
"""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import stat
import tempfile
from typing import Any, Mapping

from platformdirs import user_cache_path, user_state_path

from sciplot_core.foundation.research_destination import require_data_destination
from sciplot_core.verification.development_storage import without_development_storage

BINDING_ENV = "SCIPLOT_RECORDED_WORKSPACE"


def _destination(path: Path) -> Path:
    destination = require_data_destination(path)
    cache = user_cache_path("SciPlot").resolve()
    if destination == cache or destination.is_relative_to(cache):
        raise ValueError(f"Recorded pytest data cannot use the evictable SciPlot cache: {destination}")
    return destination


def _identity(path: Path, operation: str) -> dict[str, Any]:
    current = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(current.st_mode):
        raise ValueError("Recorded pytest workspace is not a directory.")
    return {"kind": "sciplot_recorded_workspace", "version": 1, "path": str(path), "operation": operation,
            "device": current.st_dev, "inode": current.st_ino,
            "mode": stat.S_IMODE(current.st_mode)}


def validate_recorded_workspace(environment: Mapping[str, str]) -> dict[str, Any] | None:
    """Observe a bound directory afresh; historical environments remain unbound."""
    encoded = environment.get(BINDING_ENV)
    if encoded is None:
        return None
    try:
        binding = json.loads(encoded)
    except (ValueError, TypeError) as exc:
        raise ValueError("Malformed recorded pytest workspace binding.") from exc
    if (not isinstance(binding, dict)
            or set(binding) != {"kind", "version", "path", "operation", "device", "inode", "mode"}
            or binding.get("kind") != "sciplot_recorded_workspace" or binding.get("version") != 1
            or not isinstance(binding.get("path"), str)
            or not isinstance(binding.get("operation"), str) or not Path(binding["operation"]).is_absolute()
            or any(type(binding.get(key)) is not int for key in ("device", "inode", "mode"))):
        raise ValueError("Malformed recorded pytest workspace binding.")
    path = Path(binding["path"])
    if not path.is_absolute() or _destination(path) != path:
        raise ValueError("Recorded pytest workspace path changed or follows a new alias.")
    if environment.get("PYTEST_DEBUG_TEMPROOT") != str(path) or _identity(path, binding["operation"]) != binding:
        raise ValueError("Recorded pytest workspace directory identity or environment changed.")
    return binding


def prepare_recorded_environment(
    repo_root: Path, environment: Mapping[str, str], *, legacy: bool = False,
) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Allocate once for a new check, or validate its explicitly retained binding.

An operator's external temp root is a parent, not deletion authority: a new
exclusive run child is used. Legacy reuse never allocates a pytest workspace.
"""
    effective = without_development_storage(environment)
    binding = validate_recorded_workspace(effective)
    if legacy:
        return effective, binding
    # A second temp allocator or failure-only retention would defeat the bound
    # generated-data destination. Other addopts retain their existing meaning.
    options = shlex.split(effective.get("PYTEST_ADDOPTS", ""))
    if any(option.startswith("--basetemp") or "tmp_path_retention_" in option for option in options):
        raise ValueError("Recorded pytest workspace conflicts with PYTEST_ADDOPTS temp/retention overrides.")
    finish = effective.get("SCIPLOT_VERIFY_FINISH")
    if not finish:
        raise ValueError("Recorded pytest workspace requires its completion destination before collection.")
    completion = Path(finish).expanduser()
    operation = str((completion if completion.is_absolute() else repo_root / completion).resolve().parent)
    if binding is not None:
        if binding["operation"] == operation:
            return effective, binding
        # A nested recorded check is a new operation. An inherited marker is
        # not permission to share its caller's generated inputs and outputs.
        effective.pop(BINDING_ENV)
        effective.pop("PYTEST_DEBUG_TEMPROOT")
    explicit = effective.get("PYTEST_DEBUG_TEMPROOT")
    parent = Path(explicit).expanduser() if explicit else user_state_path("SciPlot") / "verification-workspaces"
    parent = _destination(parent if parent.is_absolute() else repo_root / parent)
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    workspace = Path(tempfile.mkdtemp(prefix="run-", dir=parent)).resolve()
    binding = _identity(workspace, operation)
    effective.update({"PYTEST_DEBUG_TEMPROOT": str(workspace),
                      BINDING_ENV: json.dumps(binding, sort_keys=True, separators=(",", ":"))})
    return effective, binding
