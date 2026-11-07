"""Write the project exact-current headless export command."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from sciplot_core.launchers import inspect_project_export_command
from sciplot_core.launchers.project_launcher import _project_export_command_lines


def _prefer_offscreen_export_platform() -> None:
    if "PyQt6.QtWidgets" in sys.modules:
        return
    current = os.environ.get("QT_QPA_PLATFORM")
    if current in {None, "", "minimal"}:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


def _write_export_edited_launcher(project_dir: Path) -> Path:
    launcher = project_dir / "Export_Edited_Veusz.command"
    if launcher.exists() or launcher.is_symlink():
        if inspect_project_export_command(project_dir)["safe"] is not True:
            raise ValueError("The existing export command is not a recognized headless script.")
        return launcher  # Historical registered bytes and permissions remain unchanged.
    with launcher.open("x", encoding="utf-8") as handle:
        handle.write("\n".join(_project_export_command_lines()) + "\n")
    launcher.chmod(0o755)
    return launcher
