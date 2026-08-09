"""Build one read-only machine projection of the current FigurePlan."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, TypedDict

from sciplot_core.figure_plan import (
    FigurePlanResolutionError,
    ResolvedFigurePlanPayload,
    resolve_figure_plan,
)
from sciplot_core.materials_rules import resolve_rule_template
from sciplot_core.semantic import classify_source
from sciplot_core.study_model import study_model_from_request


PLAN_PREVIEW_KIND = "sciplot_figure_plan_preview"
PLAN_PREVIEW_VERSION = 1


PlanPreviewStatus = Literal["planned", "not_applicable", "blocked"]


class PlanPreviewBlocker(TypedDict):
    reason_code: str
    message: str


class PlanPreviewPayload(TypedDict):
    kind: Literal["sciplot_figure_plan_preview"]
    version: Literal[1]
    status: PlanPreviewStatus
    source: str
    rule_id: str | None
    template: str
    resolved_figure_plan: ResolvedFigurePlanPayload | None
    blocker: PlanPreviewBlocker | None


def build_plan_preview(
    input_path: Path,
    *,
    request: dict[str, Any],
) -> PlanPreviewPayload:
    """Resolve semantic intent and selected tasks without rendering or writes."""

    source = input_path.expanduser().resolve()
    request_snapshot = deepcopy(request)
    requested_rule_value = request_snapshot.get("rule_id")
    requested_rule_id = (
        requested_rule_value if isinstance(requested_rule_value, str) else None
    )
    semantic = classify_source(source, requested_rule_id=requested_rule_id)
    semantic_rule_value = semantic.get("rule_id")
    rule_id = (
        semantic_rule_value.strip()
        if isinstance(semantic_rule_value, str) and semantic_rule_value.strip()
        else None
    )
    requested_template_value = request_snapshot.get("template")
    requested_template = (
        requested_template_value
        if isinstance(requested_template_value, str)
        else None
    )
    template = (
        resolve_rule_template(rule_id, requested_template)
        if rule_id is not None
        else str(requested_template or semantic.get("template") or "curve")
    )
    study_model = study_model_from_request(
        request=request_snapshot,
        semantic=semantic,
        input_path=source,
    )
    try:
        plan = resolve_figure_plan(
            rule_id=rule_id,
            template=template,
            study_model=study_model,
            input_path=source,
            request=request_snapshot,
        )
    except FigurePlanResolutionError as exc:
        return {
            **_preview_base(source=source, rule_id=rule_id, template=template),
            "status": "blocked",
            "resolved_figure_plan": None,
            "blocker": {
                "reason_code": exc.reason_code,
                "message": str(exc),
            },
        }
    return {
        **_preview_base(source=source, rule_id=rule_id, template=template),
        "status": "planned" if plan is not None else "not_applicable",
        "resolved_figure_plan": plan.to_payload() if plan is not None else None,
        "blocker": None,
    }


def _preview_base(
    *,
    source: Path,
    rule_id: str | None,
    template: str,
) -> dict[str, Any]:
    return {
        "kind": PLAN_PREVIEW_KIND,
        "version": PLAN_PREVIEW_VERSION,
        "source": str(source),
        "rule_id": rule_id,
        "template": template,
    }


__all__ = [
    "PLAN_PREVIEW_KIND",
    "PLAN_PREVIEW_VERSION",
    "PlanPreviewBlocker",
    "PlanPreviewPayload",
    "PlanPreviewStatus",
    "build_plan_preview",
]
