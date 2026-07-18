from __future__ import annotations

import hashlib
import os
import re
import shlex
import sys
from collections.abc import Iterable
from pathlib import Path

from sciplot_core._paths import REPO_ROOT


PROJECT_LAUNCHER_CONTRACT_VERSION = 3
PROJECT_PRIMARY_LAUNCHER = "Open_in_SciPlot_Studio.command"
PROJECT_VEUSZ_LAUNCHER = "Open_in_Veusz.command"
PROJECT_EXPORT_LAUNCHER = "Export_Edited_Veusz.command"
LEGACY_WEB_WORKBENCH_LAUNCHER = "Open_SciPlot_Project.command"
_PORTABLE_PATH_ASSIGNMENTS = (
    "FALLBACK_REPO",
    "FALLBACK_RUNTIME_REPO",
    "FALLBACK_SOURCE_ROOT",
    "FALLBACK_PYTHON",
    "FALLBACK_WRAPPER",
)
_PORTABLE_PATH_PLACEHOLDER = "<portable-absolute-path>"
_PORTABLE_VSZ_PATH_PLACEHOLDER = "<portable-absolute-vsz-path>"
_PORTABLE_VSZ_NAME_PLACEHOLDER = "<portable-vsz-name>"


def _shell_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Invalid shell variable name: {value!r}")
    return value


def portable_sciplot_prelude(*, directory_var: str = "PROJECT_DIR") -> list[str]:
    """Return a zsh prelude that survives moved projects and installed CLIs."""

    directory_name = _shell_name(directory_var)
    source_repo = REPO_ROOT
    runtime_repo = Path(
        os.environ.get("SCIPLOT_RUNTIME_REPO")
        or os.environ.get("SCIPLOT_REPO")
        or REPO_ROOT
    ).expanduser().resolve()
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
    fallback_repo = shlex.quote(str(source_repo))
    fallback_runtime_repo = shlex.quote(str(runtime_repo))
    fallback_source_root = shlex.quote(str(source_root))
    fallback_python = shlex.quote(str(runtime_python))
    fallback_wrapper = shlex.quote(str(source_wrapper))
    return [
        "#!/bin/zsh",
        "set -euo pipefail",
        f'{directory_name}="${{0:A:h}}"',
        f"FALLBACK_REPO={fallback_repo}",
        f"FALLBACK_RUNTIME_REPO={fallback_runtime_repo}",
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
        '  export SCIPLOT_RUNTIME_REPO="${FALLBACK_RUNTIME_REPO}"',
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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_project_launcher_lines(role: str) -> list[str]:
    """Return the generator-owned launcher structure with portable values masked."""

    prelude = portable_sciplot_prelude()
    for index, line in enumerate(prelude):
        for name in _PORTABLE_PATH_ASSIGNMENTS:
            if line.startswith(f"{name}="):
                prelude[index] = f"{name}={_PORTABLE_PATH_PLACEHOLDER}"
                break

    if role == "supporting_direct_veusz_editor":
        sentinel = Path("/__sciplot_launcher_contract__/document.vsz")
        finder = portable_vsz_finder(extra_candidates=[sentinel])
        sentinel_line = f"    {shlex.quote(str(sentinel))}"
        finder[finder.index(sentinel_line)] = (
            f"    {_PORTABLE_VSZ_PATH_PLACEHOLDER}"
        )
        tail = [
            "",
            f"DOCUMENT_NAME={_PORTABLE_VSZ_NAME_PLACEHOLDER}",
            'DOCUMENT="$(find_vsz "${DOCUMENT_NAME}")" || die "Cannot locate ${DOCUMENT_NAME}."',
            'if [[ "${1:-}" == "--check" ]]; then',
            '  exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke',
            "fi",
            'exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --advanced-editor',
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


def _normalize_shell_assignment(line: str, name: str) -> str | None:
    try:
        tokens = shlex.split(line, comments=False, posix=True)
    except ValueError:
        return None
    prefix = f"{name}="
    if len(tokens) != 1 or not tokens[0].startswith(prefix):
        return None
    value = tokens[0][len(prefix) :]
    if (
        not value
        or not Path(value).is_absolute()
        or line != f"{name}={shlex.quote(value)}"
    ):
        return None
    return f"{name}={_PORTABLE_PATH_PLACEHOLDER}"


def _normalize_indented_vsz_path(line: str) -> str | None:
    if not line.startswith("    "):
        return None
    expression = line[4:]
    try:
        tokens = shlex.split(expression, comments=False, posix=True)
    except ValueError:
        return None
    if len(tokens) != 1:
        return None
    value = tokens[0]
    if (
        not value
        or not Path(value).is_absolute()
        or Path(value).suffix.casefold() != ".vsz"
        or expression != shlex.quote(value)
    ):
        return None
    return f"    {_PORTABLE_VSZ_PATH_PLACEHOLDER}"


def _normalize_vsz_name_assignment(line: str) -> str | None:
    name = "DOCUMENT_NAME"
    try:
        tokens = shlex.split(line, comments=False, posix=True)
    except ValueError:
        return None
    prefix = f"{name}="
    if len(tokens) != 1 or not tokens[0].startswith(prefix):
        return None
    value = tokens[0][len(prefix) :]
    if (
        not value
        or value in {".", ".."}
        or Path(value).name != value
        or Path(value).suffix.casefold() != ".vsz"
        or line != f"{name}={shlex.quote(value)}"
    ):
        return None
    return f"{name}={_PORTABLE_VSZ_NAME_PLACEHOLDER}"


def _project_launcher_structure(
    content: str,
    *,
    role: str,
) -> dict[str, object]:
    expected_lines = _canonical_project_launcher_lines(role)
    expected_text = "\n".join(expected_lines) + "\n"
    normalized_lines: list[str] = []
    errors: list[str] = []

    if "\x00" in content:
        errors.append("nul_byte")
    if "\r" in content:
        errors.append("noncanonical_line_endings")
    if not content.endswith("\n"):
        errors.append("missing_final_newline")

    actual_lines = content.splitlines()
    if len(actual_lines) != len(expected_lines):
        errors.append("line_count_mismatch")

    for index, expected in enumerate(expected_lines):
        if index >= len(actual_lines):
            normalized_lines.append("<missing>")
            continue
        actual = actual_lines[index]
        normalized: str | None
        portable_assignment = next(
            (
                name
                for name in _PORTABLE_PATH_ASSIGNMENTS
                if expected == f"{name}={_PORTABLE_PATH_PLACEHOLDER}"
            ),
            None,
        )
        if portable_assignment is not None:
            normalized = _normalize_shell_assignment(actual, portable_assignment)
        elif expected == f"    {_PORTABLE_VSZ_PATH_PLACEHOLDER}":
            normalized = _normalize_indented_vsz_path(actual)
        elif expected == f"DOCUMENT_NAME={_PORTABLE_VSZ_NAME_PLACEHOLDER}":
            normalized = _normalize_vsz_name_assignment(actual)
        else:
            normalized = actual
        if normalized is None:
            normalized = "<invalid-portable-value>"
            errors.append(f"invalid_portable_value_line_{index + 1}")
        normalized_lines.append(normalized)

    if len(actual_lines) > len(expected_lines):
        normalized_lines.extend(actual_lines[len(expected_lines) :])

    normalized_text = "\n".join(normalized_lines) + "\n"
    expected_structure_sha256 = _sha256_text(expected_text)
    structure_sha256 = _sha256_text(normalized_text)
    structure_matches = bool(
        not errors
        and normalized_lines == expected_lines
        and structure_sha256 == expected_structure_sha256
    )
    if not structure_matches and "structure_mismatch" not in errors:
        errors.append("structure_mismatch")

    required_command_lines = {
        "primary_veusz_first_project": (
            'exec "${SCIPLOT_CMD}" studio "${PROJECT_DIR}"'
        ),
        "supporting_direct_veusz_editor": (
            'exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --advanced-editor'
        ),
        "supporting_exact_current_export": (
            'exec "${SCIPLOT_CMD}" studio "${PROJECT_DIR}" '
            "--export pdf,tiff_300 --json"
        ),
    }
    required_command_line = required_command_lines[role]
    required_command_present = required_command_line in actual_lines
    prelude_line_count = len(portable_sciplot_prelude())
    portable_resolution = bool(
        len(normalized_lines) >= prelude_line_count
        and normalized_lines[:prelude_line_count]
        == expected_lines[:prelude_line_count]
    )
    return {
        "canonical_structure": structure_matches,
        "uses_portable_sciplot_resolution": portable_resolution,
        "required_command_present": required_command_present,
        "content_sha256": _sha256_text(content),
        "structure_sha256": structure_sha256,
        "expected_structure_sha256": expected_structure_sha256,
        "validation_errors": errors,
    }


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


__all__ = [
    "LEGACY_WEB_WORKBENCH_LAUNCHER",
    "PROJECT_EXPORT_LAUNCHER",
    "PROJECT_LAUNCHER_CONTRACT_VERSION",
    "PROJECT_PRIMARY_LAUNCHER",
    "PROJECT_VEUSZ_LAUNCHER",
    "inspect_project_launcher_contract",
    "portable_sciplot_prelude",
    "portable_vsz_finder",
]
