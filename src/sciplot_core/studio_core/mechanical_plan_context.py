"""Resolve the mechanical-only context needed by Studio orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.mechanical_figure_contract import MECHANICAL_RULE_IDS
from sciplot_core.presentation_identity import (
    SelectedPresentationIdentity,
    resolve_selected_presentation_identity,
)
from sciplot_core.study_model import normalize_study_model, study_model_from_request


def studio_presentation_identity(
    request: dict[str, Any],
    *,
    current_rule: Any,
    request_rule_id: str,
    terminal_task: FigureTask | None,
    terminal_worker: bool,
    has_terminal_source_binding: bool,
) -> SelectedPresentationIdentity:
    """Honor a mechanical child task without widening the public rule surface."""

    if (
        has_terminal_source_binding
        and terminal_worker
        and terminal_task is not None
        and request_rule_id in MECHANICAL_RULE_IDS
    ):
        return SelectedPresentationIdentity(
            rule_id=request_rule_id,
            template=terminal_task.template,
        )
    return resolve_selected_presentation_identity(
        request,
        current_rule=current_rule,
    )


def initial_studio_study_model(
    request: dict[str, Any],
    *,
    current_rule: Any,
    request_rule_id: str,
    presentation_template: str,
    source_input: Path | None,
    project_dir: Path,
) -> dict[str, Any]:
    """Persist the canonical queue used for a first mechanical preparation."""

    current = request.get("study_model")
    if request_rule_id in MECHANICAL_RULE_IDS and (
        not isinstance(current, dict) or not current
    ):
        return study_model_from_request(
            request=request,
            semantic={
                "rule_id": request_rule_id,
                "semantic_family": (
                    current_rule.semantic_family
                    if current_rule is not None
                    else "unknown"
                ),
                "template": presentation_template,
            },
            input_path=source_input or project_dir,
        )
    return current if isinstance(current, dict) else {}


def normalized_studio_study_model(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize an existing model or the route-neutral empty model."""

    return normalize_study_model(
        value
        or {
            "kind": "sciplot_study_model",
            "version": 1,
            "samples": [],
            "figure_queue": [],
        }
    )


__all__ = [
    "initial_studio_study_model",
    "normalized_studio_study_model",
    "studio_presentation_identity",
]
