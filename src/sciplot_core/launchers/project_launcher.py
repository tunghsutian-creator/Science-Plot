"""Describe the exact-current headless project export script and its old check."""

from __future__ import annotations

from sciplot_core.launchers.portable_shell import portable_sciplot_prelude, portable_vsz_finder


def _project_export_command_lines(*, legacy_check: bool = False) -> list[str]:
    """The historical check is a read-only codec, never a new script default."""
    check = ('  exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke' if legacy_check
             else '  exec "${SCIPLOT_CMD}" project inspect "${PROJECT_DIR}" --json')
    return [
        *portable_sciplot_prelude(), *portable_vsz_finder(), "",
        'DOCUMENT="$(find_vsz document.vsz)" || die "Cannot locate studio/document.vsz."',
        'if [[ "${1:-}" == "--check" ]]; then', check, "fi",
        'exec "${SCIPLOT_CMD}" studio "${PROJECT_DIR}" --export pdf,tiff_300 --json',
    ]
