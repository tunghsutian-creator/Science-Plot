"""Bind the pure project status builder to the live figure-set service."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_gui.studio_project_status.builder import build_studio_project_status as _build_studio_project_status
from sciplot_gui.studio_project_status.figure_set_scope import (
    _resolve_figure_set_export_scope as _resolve_status_figure_set_export_scope,
)

from sciplot_core.studio import observe_studio_source_content, resolve_studio_mapping_application

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
    revision = None
    if project_dir is not None and request_path is not None:
        revision = observe_studio_source_content(None, project_dir=project_dir, request_path=request_path, audit_source=False)

    def source_observer(path: Path | None, *, audit_source: bool) -> dict[str, Any] | None:
        assert project_dir is not None and request_path is not None
        return observe_studio_source_content(path, project_dir=project_dir,
            request_path=request_path, audit_source=audit_source, expected_revision=revision)

    def mapping_resolver(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        assert project_dir is not None and request_path is not None
        return resolve_studio_mapping_application(request, project_dir=project_dir,
            request_path=request_path, expected_revision=revision)

    return _build_studio_project_status(
        document_path=document_path,
        document=document,
        project_dir=project_dir,
        request_path=request_path,
        render_sha256=render_sha256,
        audit_source=audit_source,
        _figure_set_scope_resolver=_figure_set_scope_resolver,
        _source_content_observer=source_observer if project_dir is not None else None,
        _mapping_application_resolver=mapping_resolver if project_dir is not None else None,
    )
