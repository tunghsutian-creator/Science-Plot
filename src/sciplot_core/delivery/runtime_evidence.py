"""Keep recorded delivery identities distinct from their scoped physical IO."""

from pathlib import Path
from contextlib import ExitStack
from typing import Any

from sciplot_core.foundation.source_locations import literal_source_path
from sciplot_core.project_store.runtime import projected_runtime_artifact, project_read_window


def path_identity(value: Path) -> Path:
    """The existing locator owns identity; no package field is rewritten."""
    return Path(literal_source_path(value))


def launcher_contract_identity(value: object) -> object:
    """Only the observed path differs after an explicit whole-project import."""
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        return value
    return {**value, "path": str(path_identity(Path(value["path"])))}


def recorded_path_exists(value: Any) -> bool:
    return projected_runtime_artifact(str(value)).exists()


def recorded_artifacts_ready(artifacts: Any) -> bool:
    """Observe the finite recorded artifact set without spanning raw hash IO."""
    if not isinstance(artifacts, list) or not artifacts:
        return False
    with ExitStack() as scope:
        entered = False
        for item in artifacts:
            if (not isinstance(item, dict) or item.get("exists") is not True
                    or not isinstance(item.get("path"), str)):
                return False
            if not entered:
                scope.enter_context(project_read_window())
                entered = True
            if not recorded_path_exists(item["path"]):
                return False
        return True
