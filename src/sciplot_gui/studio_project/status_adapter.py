"""Bind the pure project status builder to the live figure-set service."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_gui.studio_project_status import (
    _resolve_figure_set_export_scope as _resolve_status_figure_set_export_scope,
    build_studio_project_status as _build_studio_project_status,
)

from sciplot_gui.studio_project.services import (
    _studio_figure_set_export_scope,
)


def _resolve_figure_set_export_scope(
    *,
    project_dir: Path,
    request: dict[str, Any],
    latest_run: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    return _resolve_status_figure_set_export_scope(
        project_dir=project_dir,
        request=request,
        latest_run=latest_run,
        _scope_builder=_studio_figure_set_export_scope,
    )


def build_studio_project_status(
    *,
    document_path: Path,
    document: Any,
    project_dir: Path | None,
    request_path: Path | None,
    render_sha256: str | None = None,
    audit_source: bool = False,
    _figure_set_scope_resolver: Any = _resolve_figure_set_export_scope,
) -> dict[str, Any]:
    return _build_studio_project_status(
        document_path=document_path,
        document=document,
        project_dir=project_dir,
        request_path=request_path,
        render_sha256=render_sha256,
        audit_source=audit_source,
        _figure_set_scope_resolver=_figure_set_scope_resolver,
    )
