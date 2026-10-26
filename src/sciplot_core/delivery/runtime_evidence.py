"""Keep recorded delivery identities distinct from their scoped physical IO."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.source_locations import literal_source_path, resolve_source_path


def path_identity(value: Path) -> Path:
    """The existing locator owns identity; no package field is rewritten."""
    return Path(literal_source_path(value))


def launcher_contract_identity(value: object) -> object:
    """Only the observed path differs after an explicit whole-project import."""
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        return value
    return {**value, "path": str(path_identity(Path(value["path"])))}


def recorded_path_exists(value: Any) -> bool:
    return Path(resolve_source_path(str(value))).exists()
