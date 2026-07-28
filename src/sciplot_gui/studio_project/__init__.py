"""Native Veusz project bridge API and compatibility facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_gui.studio_project.bridge import (
    StudioProjectBridge,
    attach_studio_project as _attach_studio_project,
)
from sciplot_gui.studio_project.services import (
    _is_primary_figure_set_export_scope as _is_primary_figure_set_export_scope,
    _studio_figure_set_export_scope as _studio_figure_set_export_scope,
    atomic_save_veusz_document as atomic_save_veusz_document,
    configure_studio_project_services,
    export_studio_document as export_studio_document,
    publish_standalone_export_receipt as publish_standalone_export_receipt,
    publish_studio_export_run as publish_studio_export_run,
)
from sciplot_gui.studio_project.status_adapter import (
    _resolve_figure_set_export_scope,
    build_studio_project_status as _build_studio_project_status_adapter,
)
from sciplot_gui.studio_project_status import (
    export_result_message,
)


def build_studio_project_status(
    *,
    document_path: Path,
    document: Any,
    project_dir: Path | None,
    request_path: Path | None,
    render_sha256: str | None = None,
    audit_source: bool = False,
) -> dict[str, Any]:
    """Build status while preserving the historical resolver patch seam."""

    return _build_studio_project_status_adapter(
        document_path=document_path,
        document=document,
        project_dir=project_dir,
        request_path=request_path,
        render_sha256=render_sha256,
        audit_source=audit_source,
        _figure_set_scope_resolver=_resolve_figure_set_export_scope,
    )


def attach_studio_project(
    window: Any,
    document_path: Path,
    *,
    project_dir: Path | None = None,
    request_path: Path | None = None,
) -> StudioProjectBridge:
    """Attach the dock while preserving the historical save patch seam."""

    return _attach_studio_project(
        window,
        document_path,
        project_dir=project_dir,
        request_path=request_path,
        atomic_save_document=lambda document, target: atomic_save_veusz_document(
            document,
            target,
        ),
    )


__all__ = [
    "StudioProjectBridge",
    "attach_studio_project",
    "build_studio_project_status",
    "configure_studio_project_services",
    "export_result_message",
]
