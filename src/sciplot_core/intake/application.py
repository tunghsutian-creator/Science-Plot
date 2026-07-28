"""Public intake project creation composed with the Studio lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.studio import prepare_studio_document

from .config import _DEFAULT_OUTPUT_ROOT
from .models import IntakeGroupInput
from .project import create_intake_project as _create_intake_project
from .project import (
    create_intake_project_from_session as _create_intake_project_from_session,
)


def create_intake_project_from_session(
    session: str | Path | dict[str, Any],
) -> dict[str, Any]:
    return _create_intake_project_from_session(
        session,
        studio_preparer=prepare_studio_document,
    )


def create_intake_project(
    *,
    project_name: str,
    data_type_id: str,
    experiment_type_id: str,
    groups: list[IntakeGroupInput],
    output_root: Path = _DEFAULT_OUTPUT_ROOT,
    plot_output: str | Path | None = None,
    exports: list[str] | tuple[str, ...] | None = None,
    render_options: dict[str, Any] | None = None,
    column_confirmations: list[dict[str, Any]] | None = None,
    replicate_mode: str | None = None,
    recognition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _create_intake_project(
        project_name=project_name,
        data_type_id=data_type_id,
        experiment_type_id=experiment_type_id,
        groups=groups,
        output_root=output_root,
        plot_output=plot_output,
        exports=exports,
        render_options=render_options,
        column_confirmations=column_confirmations,
        replicate_mode=replicate_mode,
        recognition=recognition,
        studio_preparer=prepare_studio_document,
    )


__all__ = ["create_intake_project", "create_intake_project_from_session"]
