"""Generate canonical Veusz-first project launchers."""

from __future__ import annotations

import shlex
from pathlib import Path

from sciplot_core.launchers.contracts import (
    _PORTABLE_VSZ_PATH_PLACEHOLDER,
    _PORTABLE_VSZ_NAME_PLACEHOLDER,
)

from sciplot_core.launchers.portable_shell import (
    portable_sciplot_prelude,
    portable_vsz_finder,
)

from sciplot_core.launchers.content_hashing import (
    _mask_portable_assignments,
)


def _canonical_project_launcher_lines(role: str) -> list[str]:
    """Return the generator-owned launcher structure with portable values masked."""

    prelude = _mask_portable_assignments(portable_sciplot_prelude())

    if role == "supporting_direct_veusz_editor":
        sentinel = Path("/__sciplot_launcher_contract__/document.vsz")
        finder = portable_vsz_finder(extra_candidates=[sentinel])
        sentinel_line = f"    {shlex.quote(str(sentinel))}"
        finder[finder.index(sentinel_line)] = f"    {_PORTABLE_VSZ_PATH_PLACEHOLDER}"
        tail = [
            "",
            f"DOCUMENT_NAME={_PORTABLE_VSZ_NAME_PLACEHOLDER}",
            'DOCUMENT="$(find_vsz "${DOCUMENT_NAME}")" || die "Cannot locate ${DOCUMENT_NAME}."',
            'if [[ "${1:-}" == "--check" ]]; then',
            '  exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke',
            "fi",
            'exec "${SCIPLOT_CMD}" studio "${DOCUMENT}"',
        ]
    elif role == "supporting_exact_current_export":
        finder = portable_vsz_finder()
        tail = [
            "",
            'DOCUMENT="$(find_vsz document.vsz)" || die "Cannot locate studio/document.vsz."',
            'if [[ "${1:-}" == "--check" ]]; then',
            '  exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke',
            "fi",
            'exec "${SCIPLOT_CMD}" studio "${PROJECT_DIR}" --export pdf,tiff_300 --json',
        ]
    elif role == "primary_veusz_first_project":
        finder = portable_vsz_finder()
        tail = [
            "",
            'DOCUMENT="$(find_vsz document.vsz)" || die "Cannot locate studio/document.vsz."',
            'if [[ "${1:-}" == "--check" ]]; then',
            '  exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke',
            "fi",
            'exec "${SCIPLOT_CMD}" studio "${PROJECT_DIR}"',
        ]
    else:
        raise ValueError(f"Unknown project launcher role: {role!r}")
    return [*prelude, *finder, *tail]
