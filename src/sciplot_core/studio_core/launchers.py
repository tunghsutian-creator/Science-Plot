"""Write Studio and Veusz launchers with deterministic platform settings."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from sciplot_core.launchers import portable_sciplot_prelude, portable_vsz_finder


def _prefer_offscreen_export_platform() -> None:
    if "PyQt6.QtWidgets" in sys.modules:
        return
    current = os.environ.get("QT_QPA_PLATFORM")
    if current in {None, "", "minimal"}:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


def _write_studio_launcher(project_dir: Path) -> Path:
    launcher = project_dir / "Open_in_SciPlot_Studio.command"
    lines = [
        *portable_sciplot_prelude(),
        *portable_vsz_finder(),
        "",
        'DOCUMENT="$(find_vsz document.vsz)" || die "Cannot locate studio/document.vsz."',
        'if [[ "${1:-}" == "--check" ]]; then',
        '  exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke',
        "fi",
        'exec "${SCIPLOT_CMD}" studio "${PROJECT_DIR}"',
    ]
    launcher.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher


def _write_veusz_launcher(project_dir: Path, document_path: Path) -> Path:
    launcher = project_dir / "Open_in_Veusz.command"
    resolved_document = document_path.expanduser().resolve()
    document_name = shlex.quote(resolved_document.name)
    lines = [
        *portable_sciplot_prelude(),
        *portable_vsz_finder(extra_candidates=[resolved_document]),
        "",
        f"DOCUMENT_NAME={document_name}",
        'DOCUMENT="$(find_vsz "${DOCUMENT_NAME}")" || die "Cannot locate ${DOCUMENT_NAME}."',
        'if [[ "${1:-}" == "--check" ]]; then',
        '  exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke',
        "fi",
        'exec "${SCIPLOT_CMD}" studio "${DOCUMENT}"',
    ]
    launcher.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher


def _write_export_edited_launcher(project_dir: Path) -> Path:
    launcher = project_dir / "Export_Edited_Veusz.command"
    lines = [
        *portable_sciplot_prelude(),
        *portable_vsz_finder(),
        "",
        'DOCUMENT="$(find_vsz document.vsz)" || die "Cannot locate studio/document.vsz."',
        'if [[ "${1:-}" == "--check" ]]; then',
        '  exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke',
        "fi",
        'exec "${SCIPLOT_CMD}" studio "${PROJECT_DIR}" --export pdf,tiff_300 --json',
    ]
    launcher.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher
