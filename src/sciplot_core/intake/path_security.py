"""Filesystem path admission for intake data and retained artifacts."""

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


def resolve_intake_destinations(
    *, source: str | None, project_name: str, project_slug: str,
    output_root: Path | None, delivery_root: Path | None,
    plot_output: str | Path | None,
) -> tuple[Path, Path | None]:
    """Resolve and admit all independent roots before raw-data materialization."""
    from sciplot_core.output_contract import resolve_user_output_layout
    if output_root is None:
        original = source
        if not original:
            raise ValueError("In-memory intake sources require an explicit external output_root.")
        default_layout = resolve_user_output_layout(Path(original), project_name=project_name)
        resolved_output_root = default_layout.workspace_root / "intake_projects"
        if delivery_root is None:
            delivery_root = default_layout.delivery_root
    else:
        resolved_output_root = output_root.expanduser().resolve()
    from sciplot_core.foundation.research_destination import require_data_destination
    require_data_destination(resolved_output_root)
    if delivery_root is not None:
        require_data_destination(delivery_root)
    if plot_output is not None and str(plot_output).strip():
        candidate = Path(plot_output).expanduser()
        if not candidate.is_absolute():
            candidate = Path(os.path.normpath(resolved_output_root / project_slug / candidate))
        require_data_destination(candidate)
    return resolved_output_root, delivery_root
