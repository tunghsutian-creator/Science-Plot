"""Inspect only the exact-current headless project export command."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.launchers.contracts import PROJECT_EXPORT_LAUNCHER
from sciplot_core.launchers.structure import _project_export_command_structure


def inspect_project_export_command(project_dir: str | Path) -> dict[str, object]:
    """Read script structure without executing it or observing old GUI files.

    This establishes a canonical command artifact, not scientific readiness or
    authority to reopen, alter or export an arbitrary document.
    """
    path = Path(project_dir).expanduser().resolve() / PROJECT_EXPORT_LAUNCHER
    exists = path.is_file() and not path.is_symlink()
    executable = bool(exists and path.stat().st_mode & 0o111)
    try:
        content = path.read_text(encoding="utf-8") if exists else ""
    except (OSError, UnicodeError):
        content = ""
    structure = _project_export_command_structure(content)
    return {
        "kind": "sciplot_project_export_command", "version": 1,
        "path": str(path), "name": path.name, "role": "exact_current_export",
        "exists": exists, "executable": executable, **structure,
        "safe": bool(exists and executable and structure["canonical_structure"] is True),
    }
