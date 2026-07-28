"""Hash launcher text and mask portable path assignments."""

from __future__ import annotations

import hashlib

from sciplot_core.launchers.contracts import (
    _PORTABLE_PATH_ASSIGNMENTS,
    _PORTABLE_PATH_PLACEHOLDER,
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mask_portable_assignments(lines: list[str]) -> list[str]:
    masked = list(lines)
    for index, line in enumerate(masked):
        for name in _PORTABLE_PATH_ASSIGNMENTS:
            if line.startswith(f"{name}="):
                masked[index] = f"{name}={_PORTABLE_PATH_PLACEHOLDER}"
                break
    return masked
