"""Write and inspect the default delivery entry to the native live editor."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.launchers.content_hashing import _mask_portable_assignments
from sciplot_core.launchers.portable_shell import portable_sciplot_prelude
from sciplot_core.launchers.structure import _launcher_structure
from sciplot_core.policy import DELIVERY_EDITOR_LAUNCHER


DELIVERY_EDITOR_LAUNCHER_CONTRACT_VERSION = 1
_EDIT_COMMAND = 'exec "${SCIPLOT_CMD}" edit "${DELIVERY_DIR}" --portable-fallback "$@"'


def _delivery_editor_launcher_lines() -> list[str]:
    return [
        *portable_sciplot_prelude(directory_var="DELIVERY_DIR"),
        "",
        'if [[ "${SCIPLOT_LAUNCH_DRY_RUN:-0}" == "1" ]]; then',
        '  print -rl -- "${SCIPLOT_CMD}" edit "${DELIVERY_DIR}" --portable-fallback "$@"',
        "  exit 0",
        "fi",
        _EDIT_COMMAND,
    ]


def write_delivery_editor_launcher(delivery_dir: str | Path) -> Path:
    """Write an executable entry that resolves managed or portable edit targets."""

    root = Path(delivery_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    launcher = root / DELIVERY_EDITOR_LAUNCHER
    launcher.write_text(
        "\n".join(_delivery_editor_launcher_lines()) + "\n", encoding="utf-8"
    )
    launcher.chmod(0o755)
    return launcher


def inspect_delivery_editor_launcher_contract(
    delivery_dir: str | Path,
) -> dict[str, object]:
    """Reject altered shell structure, including extra commands and comments."""

    launcher = Path(delivery_dir).expanduser().resolve() / DELIVERY_EDITOR_LAUNCHER
    exists = launcher.is_file() and not launcher.is_symlink()
    executable = bool(exists and launcher.stat().st_mode & 0o111)
    try:
        content = launcher.read_text(encoding="utf-8") if exists else ""
    except (OSError, UnicodeError):
        content = ""
    structure = _launcher_structure(
        content,
        expected_lines=_mask_portable_assignments(_delivery_editor_launcher_lines()),
        required_command_line=_EDIT_COMMAND,
        directory_var="DELIVERY_DIR",
    )
    return {
        "kind": "sciplot_delivery_editor_launcher_contract",
        "version": DELIVERY_EDITOR_LAUNCHER_CONTRACT_VERSION,
        "path": str(launcher),
        "name": launcher.name,
        "exists": exists,
        "executable": executable,
        **structure,
        "ready": bool(
            exists
            and executable
            and structure["canonical_structure"]
            and structure["required_command_present"]
        ),
    }
