"""Normalize portable shell path and VSZ assignments."""

from __future__ import annotations

import shlex
from pathlib import Path

from sciplot_core.launchers.contracts import (
    _PORTABLE_PATH_PLACEHOLDER,
    _PORTABLE_VSZ_PATH_PLACEHOLDER,
    _PORTABLE_VSZ_NAME_PLACEHOLDER,
)


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
