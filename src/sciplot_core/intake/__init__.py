"""Headless intake domain and loopback confirmation application."""

from .application import create_intake_project
from .browser_app import serve_intake
from .catalog import (
    converge_material_review_notes,
    intake_catalog_payload,
)
from .config import (
    APPROVED_INTAKE_SIZE_PRESETS,
    SAXS_SCALING_REVIEW_NOTE,
)
from .models import IncomingFile, IntakeGroupInput
from .packaging import (
    _write_zip as _write_zip,
    converge_intake_project_launchers,
    refresh_intake_project_zip,
)
from .project import create_intake_project_from_session as _restore_intake_session
from .run import create_and_run_intake_project
from .session import prepare_intake_session
from .status import (
    _resolve_project_artifact as _resolve_project_artifact,
    intake_project_status,
    list_intake_projects,
)
from .table_preview import (
    _tensile_export_dirs as _tensile_export_dirs,
    preview_table_payload,
)


def create_intake_project_from_session(session):
    """Restore a confirmed session through the public project factory."""

    from sciplot_core.studio import prepare_studio_document

    return _restore_intake_session(
        session,
        studio_preparer=prepare_studio_document,
        project_factory=create_intake_project,
    )


__all__ = [
    "APPROVED_INTAKE_SIZE_PRESETS",
    "IncomingFile",
    "IntakeGroupInput",
    "SAXS_SCALING_REVIEW_NOTE",
    "converge_intake_project_launchers",
    "converge_material_review_notes",
    "create_and_run_intake_project",
    "create_intake_project",
    "create_intake_project_from_session",
    "intake_catalog_payload",
    "intake_project_status",
    "list_intake_projects",
    "prepare_intake_session",
    "preview_table_payload",
    "refresh_intake_project_zip",
    "serve_intake",
]
