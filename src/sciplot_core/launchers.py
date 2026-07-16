from __future__ import annotations

import os
import re
import shlex
import sys
from collections.abc import Iterable
from pathlib import Path

from sciplot_core._paths import REPO_ROOT


def _shell_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Invalid shell variable name: {value!r}")
    return value


def portable_sciplot_prelude(*, directory_var: str = "PROJECT_DIR") -> list[str]:
    """Return a zsh prelude that survives moved projects and installed CLIs."""

    directory_name = _shell_name(directory_var)
    runtime_repo = Path(os.environ.get("SCIPLOT_REPO") or REPO_ROOT).expanduser().resolve()
    source_root = Path(
        os.environ.get("SCIPLOT_SOURCE_ROOT") or Path(__file__).resolve().parents[1]
    ).expanduser().resolve()
    python_candidates = [
        Path(os.environ["SCIPLOT_PYTHON"]).expanduser()
        if os.environ.get("SCIPLOT_PYTHON")
        else None,
        runtime_repo / ".venv" / "bin" / "python",
        Path(sys.executable),
    ]
    runtime_python = next(
        (path.absolute() for path in python_candidates if path is not None and path.is_file()),
        Path(sys.executable).absolute(),
    )
    source_wrapper = source_root.parent / "skill" / "scripts" / "sciplot"
    fallback_repo = shlex.quote(str(runtime_repo))
    fallback_source_root = shlex.quote(str(source_root))
    fallback_python = shlex.quote(str(runtime_python))
    fallback_wrapper = shlex.quote(str(source_wrapper))
    return [
        "#!/bin/zsh",
        "set -euo pipefail",
        f'{directory_name}="${{0:A:h}}"',
        f"FALLBACK_REPO={fallback_repo}",
        f"FALLBACK_SOURCE_ROOT={fallback_source_root}",
        f"FALLBACK_PYTHON={fallback_python}",
        f"FALLBACK_WRAPPER={fallback_wrapper}",
        "",
        "die() {",
        '  print -u2 -- "SciPlot launcher error: $1"',
        '  if [[ -t 0 ]]; then read -r "?Press Return to close."; fi',
        "  exit 1",
        "}",
        "",
        "find_sciplot() {",
        "  local candidate",
        '  if [[ -n "${SCIPLOT_REPO:-}" ]]; then',
        '    candidate="${SCIPLOT_REPO}/skill/scripts/sciplot"',
        '    if [[ -x "${candidate}" ]]; then',
        '      print -r -- "${candidate}"',
        "      return 0",
        "    fi",
        "  fi",
        f'  local cursor="${{{directory_name}}}"',
        '  while [[ "${cursor}" != "/" ]]; do',
        '    candidate="${cursor}/skill/scripts/sciplot"',
        '    if [[ -x "${candidate}" ]]; then',
        '      print -r -- "${candidate}"',
        "      return 0",
        "    fi",
        '    cursor="${cursor:h}"',
        "  done",
        '  candidate="${FALLBACK_WRAPPER}"',
        '  if [[ -x "${candidate}" ]]; then',
        '    print -r -- "${candidate}"',
        "    return 0",
        "  fi",
        '  candidate="${FALLBACK_REPO}/skill/scripts/sciplot"',
        '  if [[ -x "${candidate}" ]]; then',
        '    print -r -- "${candidate}"',
        "    return 0",
        "  fi",
        '  candidate="$(command -v sciplot || true)"',
        '  if [[ -n "${candidate}" ]]; then',
        '    print -r -- "${candidate}"',
        "    return 0",
        "  fi",
        "  return 1",
        "}",
        "",
        'SCIPLOT_CMD="$(find_sciplot)" || die "Cannot locate SciPlot. Set SCIPLOT_REPO or install sciplot."',
        "if [[ "
        '"${SCIPLOT_CMD}" == "${FALLBACK_WRAPPER}" '
        '|| "${SCIPLOT_CMD}" == "${FALLBACK_REPO}/skill/scripts/sciplot" '
        "]]; then",
        '  export SCIPLOT_REPO="${FALLBACK_REPO}"',
        '  if [[ ! -d "${SCIPLOT_SOURCE_ROOT:-}" && -d "${FALLBACK_SOURCE_ROOT}" ]]; then',
        '    export SCIPLOT_SOURCE_ROOT="${FALLBACK_SOURCE_ROOT}"',
        "  fi",
        '  if [[ ! -x "${SCIPLOT_PYTHON:-}" && -x "${FALLBACK_PYTHON}" ]]; then',
        '    export SCIPLOT_PYTHON="${FALLBACK_PYTHON}"',
        "  fi",
        "fi",
        "unset SCIPLOT_STUDIO_QT_RUNTIME || true",
        "unset DYLD_FRAMEWORK_PATH || true",
        "unset DYLD_LIBRARY_PATH || true",
        "unset QT_QPA_PLATFORM || true",
    ]


def portable_vsz_finder(
    *,
    directory_var: str = "PROJECT_DIR",
    extra_candidates: Iterable[str | Path] = (),
) -> list[str]:
    """Return a zsh function that resolves a named VSZ after delivery moves."""

    directory_name = _shell_name(directory_var)
    candidates = [
        f'"${{{directory_name}}}/${{name}}"',
        f'"${{{directory_name}}}/studio/${{name}}"',
        f'"${{{directory_name}}}/veusz/${{name}}"',
        f'"${{{directory_name}}}/../veusz/${{name}}"',
    ]
    candidates.extend(shlex.quote(str(Path(item).expanduser())) for item in extra_candidates)
    lines = [
        "",
        "find_vsz() {",
        '  local name="$1"',
        "  local candidate",
        "  local candidates=(",
    ]
    lines.extend(f"    {candidate}" for candidate in candidates)
    lines.extend(
        [
            "  )",
            '  for candidate in "${candidates[@]}"; do',
            '    if [[ -f "${candidate}" ]]; then',
            '      print -r -- "${candidate}"',
            "      return 0",
            "    fi",
            "  done",
            "  return 1",
            "}",
        ]
    )
    return lines


__all__ = ["portable_sciplot_prelude", "portable_vsz_finder"]
