"""Validate the complete figure-set scope expected by Studio publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import (
    ResolvedFigurePlan,
    resolved_figure_plan_from_payload,
)
from sciplot_core.figure_plan.constants import REQUIRED_FIGURE_PLAN_RULE_IDS
from sciplot_core.studio_figure_set_contract import (
    is_full_figure_set_export_scope,
)

from sciplot_core.studio_core.figure_requests import (
    _rheology_frequency_figure_queue,
)
from sciplot_core.studio_core.figure_set_state import (
    _read_studio_figure_set,
    _studio_figure_set_export_scope,
)


def validated_figure_set_scope(
    project_dir: Path,
    *,
    request: dict[str, Any],
    figure_plan: ResolvedFigurePlan | None = None,
    figure_set: dict[str, Any] | None = None,
    figure_set_loaded: bool = False,
) -> dict[str, Any] | None:
    """Require the complete scope expected by a prepared publication plan."""

    try:
        request_plan = figure_plan or resolved_figure_plan_from_payload(
            request.get("resolved_figure_plan")
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "invalid_resolved_figure_plan: Studio cannot establish an export "
            "scope from the persisted FigurePlan."
        ) from exc
    selected_plan = (
        request_plan
        if request_plan is not None
        and request_plan.rule_id in REQUIRED_FIGURE_PLAN_RULE_IDS
        else None
    )
    registry = figure_set if figure_set_loaded else _read_studio_figure_set(project_dir)
    scope = _studio_figure_set_export_scope(
        project_dir,
        request=request,
        figure_set=registry,
        figure_set_loaded=True,
    )
    scope_expected = bool(
        selected_plan is not None
        or registry is not None
        or _rheology_frequency_figure_queue(request)
    )
    if selected_plan is not None and not is_full_figure_set_export_scope(scope):
        raise RuntimeError(
            "A selected required FigurePlan needs a matching task-aware v2 "
            "Studio figure-set registry before export. No project delivery "
            "receipt was published."
        )
    if scope_expected and not is_full_figure_set_export_scope(scope):
        raise RuntimeError(
            "SciPlot could not establish the complete all-figures figure-set "
            "export scope. No project delivery receipt was published."
        )
    return scope


__all__ = ["validated_figure_set_scope"]
