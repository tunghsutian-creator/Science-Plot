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
from sciplot_core.materials_rules import SemanticRule, get_rule, resolve_rule_template
from sciplot_core.readiness.registry_io import load_validated_envelope_registry
from sciplot_core.readiness.rule_certification import (
    current_rule_invocation_contract_payload,
)
from sciplot_core.semantic import classify_source
from sciplot_core.semantic_sources.scientific_source import (
    ScientificSourceResolutionError,
    resolve_scientific_source,
)
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
    scientific_transform: dict[str, Any] | None
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
    requested_template_value = request_snapshot.get("template")
    requested_template = (
        requested_template_value
        if isinstance(requested_template_value, str)
        else None
    )
    preview_template = str(requested_template or "curve")
    explicit_rule: SemanticRule | None = None
    explicit_template: str | None = None
    if "rule_id" in request_snapshot:
        if (
            not isinstance(requested_rule_value, str)
            or not requested_rule_value
            or requested_rule_value.strip() != requested_rule_value
        ):
            return _blocked_preview(
                source=source,
                rule_id=None,
                template=preview_template,
                reason_code="plan_rule_invalid",
                message=(
                    "Plan rule_id must be one non-empty canonical identifier "
                    "when explicitly provided."
                ),
            )
        try:
            explicit_rule = get_rule(requested_rule_value)
        except ValueError as exc:
            return _blocked_preview(
                source=source,
                rule_id=requested_rule_value,
                template=preview_template,
                reason_code="plan_rule_unknown",
                message=str(exc),
            )
        try:
            explicit_template = resolve_rule_template(
                explicit_rule,
                requested_template,
            )
        except ValueError as exc:
            return _blocked_preview(
                source=source,
                rule_id=explicit_rule.rule_id,
                template=preview_template,
                reason_code="plan_template_unsupported",
                message=str(exc),
            )
        invocation = current_rule_invocation_contract_payload(
            rule=explicit_rule,
            registry=load_validated_envelope_registry(),
        )
        if invocation["availability"] != "ready":
            reasons = invocation["reason_codes"]
            return _blocked_preview(
                source=source,
                rule_id=explicit_rule.rule_id,
                template=explicit_template or explicit_rule.template,
                reason_code=reasons[0],
                message=(
                    f"Material rule `{explicit_rule.rule_id}` is not available "
                    "for deterministic invocation: " + ", ".join(reasons) + "."
                ),
            )
    if not source.exists():
        return _blocked_preview(
            source=source,
            rule_id=explicit_rule.rule_id if explicit_rule is not None else None,
            template=explicit_template or preview_template,
            reason_code="plan_source_not_found",
            message=f"Input not found: {input_path}",
        )
    requested_rule_id = (
        requested_rule_value if isinstance(requested_rule_value, str) else None
    )
    try:
        semantic = classify_source(source, requested_rule_id=requested_rule_id)
    except (OSError, UnicodeError) as exc:
        return _blocked_preview(
            source=source,
            rule_id=explicit_rule.rule_id if explicit_rule is not None else None,
            template=explicit_template or preview_template,
            reason_code="plan_source_inspection_failed",
            message=str(exc),
        )
    semantic_rule_value = semantic.get("rule_id")
    rule_id = (
        semantic_rule_value.strip()
        if isinstance(semantic_rule_value, str) and semantic_rule_value.strip()
        else None
    )
    if explicit_rule is not None:
        template = explicit_template or explicit_rule.template
    elif rule_id is not None:
        classified_rule = get_rule(rule_id)
        if requested_template is not None:
            try:
                template = resolve_rule_template(classified_rule, requested_template)
            except ValueError as exc:
                return _blocked_preview(
                    source=source,
                    rule_id=rule_id,
                    template=preview_template,
                    reason_code="plan_template_unsupported",
                    message=str(exc),
                )
        else:
            template = resolve_rule_template(classified_rule)
    else:
        template = str(requested_template or semantic.get("template") or "curve")
    inspection_error = semantic.get("vendor_error")
    if inspection_error:
        return _blocked_preview(
            source=source,
            rule_id=rule_id,
            template=template,
            reason_code="plan_source_inspection_failed",
            message=str(inspection_error),
        )
    study_model = study_model_from_request(
        request=request_snapshot,
        semantic=semantic,
        input_path=source,
    )
    try:
        resolved_scientific_source = resolve_scientific_source(
            source,
            rule_id=rule_id,
            request=request_snapshot,
            template=template,
            study_model=study_model,
        )
    except (FigurePlanResolutionError, ScientificSourceResolutionError) as exc:
        return _blocked_preview(
            source=source,
            rule_id=rule_id,
            template=template,
            reason_code=exc.reason_code,
            message=str(exc),
        )
    transform = (
        resolved_scientific_source.transform
        if resolved_scientific_source is not None
        else None
    )
    scientific_transform = (
        transform.contract.to_payload() if transform is not None else None
    )
    try:
        plan = (
            resolved_scientific_source.figure_plan
            if resolved_scientific_source is not None
            else resolve_figure_plan(
                rule_id=rule_id,
                template=template,
                study_model=study_model,
                input_path=source,
                request=request_snapshot,
            )
        )
    except FigurePlanResolutionError as exc:
        return _blocked_preview(
            source=source,
            rule_id=rule_id,
            template=template,
            reason_code=exc.reason_code,
            message=str(exc),
            scientific_transform=scientific_transform,
        )
    return {
        **_preview_base(source=source, rule_id=rule_id, template=template),
        "status": "planned" if plan is not None else "not_applicable",
        "resolved_figure_plan": plan.to_payload() if plan is not None else None,
        "scientific_transform": scientific_transform,
        "blocker": None,
    }


def _blocked_preview(
    *,
    source: Path,
    rule_id: str | None,
    template: str,
    reason_code: str,
    message: str,
    scientific_transform: dict[str, Any] | None = None,
) -> PlanPreviewPayload:
    return {
        **_preview_base(source=source, rule_id=rule_id, template=template),
        "status": "blocked",
        "resolved_figure_plan": None,
        "scientific_transform": scientific_transform,
        "blocker": {
            "reason_code": reason_code,
            "message": message,
        },
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
