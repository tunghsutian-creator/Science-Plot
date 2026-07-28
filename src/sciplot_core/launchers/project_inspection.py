"""Inspect all Veusz-first project launchers."""

from __future__ import annotations

import shlex
from pathlib import Path

from sciplot_core.launchers.contracts import (
    PROJECT_LAUNCHER_CONTRACT_VERSION,
    PROJECT_PRIMARY_LAUNCHER,
    PROJECT_VEUSZ_LAUNCHER,
    PROJECT_EXPORT_LAUNCHER,
    LEGACY_WEB_WORKBENCH_LAUNCHER,
)

from sciplot_core.launchers.structure import (
    _project_launcher_structure,
)


def _project_launcher_record(
    path: Path,
    *,
    role: str,
) -> dict[str, object]:
    exists = path.is_file()
    executable = bool(exists and path.stat().st_mode & 0o111)
    try:
        content = path.read_text(encoding="utf-8") if exists else ""
    except (OSError, UnicodeError):
        content = ""
    structure = _project_launcher_structure(
        content,
        role=role,
    )
    opens_web_workbench = False
    for line in content.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        for index, token in enumerate(tokens[:-1]):
            command = token.rstrip("/")
            if (
                command in {"${SCIPLOT_CMD}", "$SCIPLOT_CMD", "sciplot"}
                or Path(command).name == "sciplot"
            ) and tokens[index + 1] in {"workbench", "intake"}:
                opens_web_workbench = True
                break
        if opens_web_workbench:
            break
    safe = bool(
        exists
        and executable
        and structure["canonical_structure"] is True
        and not opens_web_workbench
    )
    return {
        "path": str(path),
        "name": path.name,
        "role": role,
        "exists": exists,
        "executable": executable,
        **structure,
        "opens_web_workbench": opens_web_workbench,
        "safe": safe,
    }


def inspect_project_launcher_contract(project_dir: str | Path) -> dict[str, object]:
    """Inspect the user-facing launchers for one Veusz-first project.

    The Studio launcher is the single primary daily entrypoint. The direct
    Veusz and exact-current export launchers remain explicit supporting tools.
    The retired Web workbench launcher must not be present in a normal package.
    """

    project = Path(project_dir).expanduser().resolve()
    primary = _project_launcher_record(
        project / PROJECT_PRIMARY_LAUNCHER,
        role="primary_veusz_first_project",
    )
    veusz = _project_launcher_record(
        project / PROJECT_VEUSZ_LAUNCHER,
        role="supporting_direct_veusz_editor",
    )
    export = _project_launcher_record(
        project / PROJECT_EXPORT_LAUNCHER,
        role="supporting_exact_current_export",
    )
    legacy_path = project / LEGACY_WEB_WORKBENCH_LAUNCHER
    legacy_present = legacy_path.is_file() or legacy_path.is_symlink()
    launchers = [primary, veusz, export]
    ready = bool(
        not legacy_present and all(record.get("safe") is True for record in launchers)
    )
    return {
        "kind": "sciplot_project_launcher_contract",
        "version": PROJECT_LAUNCHER_CONTRACT_VERSION,
        "status": "ready" if ready else "blocked",
        "mode": "veusz_first",
        "primary": primary,
        "supporting": {
            "veusz": veusz,
            "export_exact_current": export,
        },
        "legacy_web_workbench_launcher": {
            "name": LEGACY_WEB_WORKBENCH_LAUNCHER,
            "path": str(legacy_path),
            "present": legacy_present,
            "allowed": False,
        },
        "ready": ready,
    }
