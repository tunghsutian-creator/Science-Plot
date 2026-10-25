"""Read-only path validation for historical annotation companion evidence."""

from pathlib import Path
from typing import Any

from sciplot_core.studio_core.delivery_recovery_state import canonical_path


def companion_path(project: Path, record: dict[str, Any]) -> Path:
    relative = Path(record["relative"])
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("studio",):
        raise ValueError("The edit specification must be a managed studio file")
    return canonical_path(project / relative)
