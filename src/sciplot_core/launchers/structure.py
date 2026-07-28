"""Validate launcher text against canonical generated structure."""

from __future__ import annotations


from sciplot_core.launchers.contracts import (
    _PORTABLE_PATH_ASSIGNMENTS,
    _PORTABLE_PATH_PLACEHOLDER,
    _PORTABLE_VSZ_PATH_PLACEHOLDER,
    _PORTABLE_VSZ_NAME_PLACEHOLDER,
)

from sciplot_core.launchers.portable_shell import (
    portable_sciplot_prelude,
)

from sciplot_core.launchers.content_hashing import (
    _sha256_text,
)

from sciplot_core.launchers.delivery_launcher import (
    _canonical_delivery_launcher_lines,
)

from sciplot_core.launchers.project_launcher import (
    _canonical_project_launcher_lines,
)

from sciplot_core.launchers.portable_values import (
    _normalize_shell_assignment,
    _normalize_indented_vsz_path,
    _normalize_vsz_name_assignment,
)


def _launcher_structure(
    content: str,
    *,
    expected_lines: list[str],
    required_command_line: str,
    directory_var: str,
) -> dict[str, object]:
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

    required_command_present = required_command_line in actual_lines
    prelude_line_count = len(portable_sciplot_prelude(directory_var=directory_var))
    portable_resolution = bool(
        len(normalized_lines) >= prelude_line_count
        and normalized_lines[:prelude_line_count] == expected_lines[:prelude_line_count]
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


def _project_launcher_structure(
    content: str,
    *,
    role: str,
) -> dict[str, object]:
    required_command_lines = {
        "primary_veusz_first_project": (
            'exec "${SCIPLOT_CMD}" studio "${PROJECT_DIR}"'
        ),
        "supporting_direct_veusz_editor": (
            'exec "${SCIPLOT_CMD}" studio "${DOCUMENT}"'
        ),
        "supporting_exact_current_export": (
            'exec "${SCIPLOT_CMD}" studio "${PROJECT_DIR}" --export pdf,tiff_300 --json'
        ),
    }
    return _launcher_structure(
        content,
        expected_lines=_canonical_project_launcher_lines(role),
        required_command_line=required_command_lines[role],
        directory_var="PROJECT_DIR",
    )


def _delivery_launcher_structure(content: str) -> dict[str, object]:
    return _launcher_structure(
        content,
        expected_lines=_canonical_delivery_launcher_lines(),
        required_command_line='exec "${SCIPLOT_CMD}" studio "${DOCUMENT}"',
        directory_var="DELIVERY_DIR",
    )
