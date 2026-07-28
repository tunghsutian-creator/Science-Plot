"""Generate and write the canonical delivery launcher."""

from __future__ import annotations

from pathlib import Path
from sciplot_core.policy import DELIVERY_LAUNCHER

from sciplot_core.launchers.portable_shell import (
    portable_sciplot_prelude,
)

from sciplot_core.launchers.content_hashing import (
    _mask_portable_assignments,
)


def _delivery_launcher_lines() -> list[str]:
    return [
        *portable_sciplot_prelude(directory_var="DELIVERY_DIR"),
        "",
        'documents=("${DELIVERY_DIR}"/project/*.vsz(N))',
        "if (( ${#documents[@]} == 0 )); then",
        '  die "No Veusz project files found in ${DELIVERY_DIR}/project"',
        "fi",
        'if [[ "${1:-}" == "--check" ]]; then',
        '  for DOCUMENT in "${documents[@]}"; do',
        '    "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke',
        "  done",
        "  exit 0",
        "fi",
        "if (( $# > 0 )); then",
        '  DOCUMENT="$1"',
        '  [[ "${DOCUMENT}" = /* ]] || DOCUMENT="${DELIVERY_DIR}/project/${DOCUMENT}"',
        "elif (( ${#documents[@]} == 1 )); then",
        '  DOCUMENT="${documents[1]}"',
        "else",
        '  print "Select a figure to edit in Veusz:"',
        "  for index in {1..${#documents[@]}}; do",
        '    print "${index}) ${documents[$index]:t:r}"',
        "  done",
        "  while true; do",
        '    read "choice?> "',
        '    if [[ "${choice}" = <-> ]] && (( choice >= 1 && choice <= ${#documents[@]} )); then',
        '      DOCUMENT="${documents[$choice]}"',
        "      break",
        "    fi",
        '    print -u2 "Enter a number from 1 to ${#documents[@]}."',
        "  done",
        "fi",
        'if [[ ! -f "${DOCUMENT}" ]]; then',
        '  print -u2 "Veusz document not found: ${DOCUMENT}"',
        "  exit 1",
        "fi",
        'if [[ "${SCIPLOT_LAUNCH_DRY_RUN:-0}" == "1" ]]; then',
        '  print -r -- "${DOCUMENT}"',
        "  exit 0",
        "fi",
        'exec "${SCIPLOT_CMD}" studio "${DOCUMENT}"',
    ]


def write_delivery_launcher(delivery_dir: str | Path) -> Path:
    """Write the canonical portable launcher for one minimal delivery."""

    root = Path(delivery_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    launcher = root / DELIVERY_LAUNCHER
    launcher.write_text(
        "\n".join(_delivery_launcher_lines()) + "\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher


def _canonical_delivery_launcher_lines() -> list[str]:
    return _mask_portable_assignments(_delivery_launcher_lines())
