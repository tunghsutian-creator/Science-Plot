"""Inspect the launcher embedded in a visible delivery."""

from __future__ import annotations

from pathlib import Path
from sciplot_core.policy import DELIVERY_LAUNCHER

from sciplot_core.launchers.contracts import (
    DELIVERY_LAUNCHER_CONTRACT_VERSION,
)

from sciplot_core.launchers.structure import (
    _delivery_launcher_structure,
)


def inspect_delivery_launcher_contract(
    delivery_dir: str | Path,
) -> dict[str, object]:
    """Inspect the generated launcher that is part of a minimal delivery."""

    root = Path(delivery_dir).expanduser().resolve()
    launcher = root / DELIVERY_LAUNCHER
    exists = launcher.is_file()
    executable = bool(exists and launcher.stat().st_mode & 0o111)
    try:
        content = launcher.read_text(encoding="utf-8") if exists else ""
    except (OSError, UnicodeError):
        content = ""
    structure = _delivery_launcher_structure(content)
    ready = bool(
        exists
        and executable
        and structure["canonical_structure"] is True
        and structure["required_command_present"] is True
    )
    return {
        "kind": "sciplot_delivery_launcher_contract",
        "version": DELIVERY_LAUNCHER_CONTRACT_VERSION,
        "path": str(launcher),
        "name": launcher.name,
        "exists": exists,
        "executable": executable,
        **structure,
        "ready": ready,
    }
