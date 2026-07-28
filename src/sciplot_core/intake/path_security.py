"""Filesystem authorization for browser-visible intake artifacts."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from sciplot_core._paths import resolved_path_is_within


def _resolve_path_within_root(
    path: str | Path,
    *,
    root: str | Path,
    require_regular_file: bool,
) -> Path:
    """Resolve one path beneath a trusted root without following symlinks."""

    trusted_root = Path(root).expanduser().resolve(strict=True)
    requested = Path(path).expanduser()
    if not requested.is_absolute():
        requested = trusted_root / requested
    lexical_path = Path(os.path.abspath(requested))
    try:
        relative = lexical_path.relative_to(trusted_root)
    except ValueError as exc:
        raise PermissionError("Path is outside the authorized SciPlot root.") from exc

    current = trusted_root
    for part in relative.parts:
        current = current / part
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(current_stat.st_mode):
            raise PermissionError(
                "Symlink-backed SciPlot artifacts are not authorized."
            )

    resolved = lexical_path.resolve(strict=False)
    if not resolved_path_is_within(resolved, trusted_root):
        raise PermissionError("Path is outside the authorized SciPlot root.")
    if require_regular_file:
        try:
            resolved_stat = resolved.stat()
        except FileNotFoundError:
            raise FileNotFoundError(resolved) from None
        if not stat.S_ISREG(resolved_stat.st_mode):
            raise FileNotFoundError(resolved)
    return resolved
