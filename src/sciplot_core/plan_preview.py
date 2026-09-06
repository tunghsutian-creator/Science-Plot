"""Build one read-only machine projection of the current FigurePlan."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Final, Literal, TypedDict

from sciplot_core.figure_plan import (
    FigurePlanResolutionError,
    ResolvedFigurePlanPayload,
    resolve_figure_plan,
)
from sciplot_core.materials_rules import SemanticRule, get_rule
from sciplot_core.materials_rules.catalog import resolve_rule_template
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.plan_identity import preview_identity_for
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


PLAN_PREVIEW_KIND: Final = "sciplot_figure_plan_preview"
PLAN_PREVIEW_VERSION: Final = 1


PlanPreviewStatus = Literal["planned", "not_applicable", "blocked"]


class PlanPreviewBlocker(TypedDict):
    reason_code: str
    message: str


class PlanPreviewBase(TypedDict):
    kind: Literal["sciplot_figure_plan_preview"]
    version: Literal[1]
    source: str
    rule_id: str | None
    template: str
    preview_identity: dict[str, Any] | None


class PlanPreviewPayload(PlanPreviewBase):
    status: PlanPreviewStatus
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
        requested_template_value if isinstance(requested_template_value, str) else None
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
        source_hash = source_tree_sha256(source)
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
    try:
        source_still_current = (
            source_hash is not None and source_tree_sha256(source) == source_hash
        )
    except OSError:
        source_still_current = False
    if not source_still_current:
        return _blocked_preview(
            source=source,
            rule_id=rule_id,
            template=template,
            reason_code="plan_source_changed_during_preview",
            message="Source changed while resolving the plan; inspect its current version again.",
        )
    payload: PlanPreviewPayload = {
        **_preview_base(source=source, rule_id=rule_id, template=template),
        "status": "planned" if plan is not None else "not_applicable",
        "resolved_figure_plan": plan.to_payload() if plan is not None else None,
        "scientific_transform": scientific_transform,
        "blocker": None,
    }
    assert source_hash is not None
    payload["preview_identity"] = preview_identity_for(
        dict(payload), source_sha256=source_hash
    )
    return payload


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
) -> PlanPreviewBase:
    return {
        "kind": PLAN_PREVIEW_KIND,
        "version": PLAN_PREVIEW_VERSION,
        "source": str(source),
        "rule_id": rule_id,
        "template": template,
        "preview_identity": None,
    }


def verify_expected_plan(
    source: Path,
    expected: dict[str, Any],
    *,
    rule_id: str | None,
    template: str | None,
) -> dict[str, Any]:
    """Rebuild a fresh preview before project creation; this is not a run lock."""
    if (
        not isinstance(expected, dict)
        or expected.get("kind") != "sciplot_figure_plan_preview"
        or type(expected.get("version")) is not int
        or expected.get("version") != 1
        or expected.get("status") not in ("planned", "not_applicable")
        or expected.get("blocker") is not None
    ):
        raise ValueError("--expected-plan requires a successful current plan preview.")
    identity = expected.get("preview_identity")
    digest = identity.get("source_tree_sha256") if isinstance(identity, dict) else None
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("Expected plan has no valid input identity; run plan again.")
    if canonical_json_sha256(identity, allow_nan=False) != canonical_json_sha256(
        preview_identity_for(expected, source_sha256=digest), allow_nan=False
    ):
        raise ValueError("Expected plan contents or identity changed; run plan again.")
    if source_tree_sha256(source) != digest:
        raise ValueError("Source changed since the expected plan; run plan again.")
    selected = {
        "rule_id": rule_id if rule_id is not None else expected.get("rule_id"),
        "template": template if template is not None else expected.get("template"),
    }
    current = build_plan_preview(
        source,
        request={key: value for key, value in selected.items() if value is not None},
    )
    if current["status"] == "blocked":
        blocker = current.get("blocker")
        raise ValueError(
            "Expected plan can no longer execute: "
            + (
                blocker["message"]
                if blocker
                else "the current scientific plan is blocked"
            )
        )
    if canonical_json_sha256(current, allow_nan=False) != canonical_json_sha256(
        expected, allow_nan=False
    ):
        raise ValueError(
            "Expected plan is stale or its rule, template, or scientific selections changed; run plan again."
        )
    # Recheck as close as possible to run_one_step's source consumer. The normal
    # workflow owns source snapshots and publication checks after this preflight.
    if source_tree_sha256(source) != digest:
        raise ValueError(
            "Source changed during expected-plan validation; run plan again."
        )
    return dict(current)


__all__ = [
    "PLAN_PREVIEW_KIND",
    "PLAN_PREVIEW_VERSION",
    "PlanPreviewBlocker",
    "PlanPreviewPayload",
    "PlanPreviewStatus",
    "build_plan_preview",
    "verify_expected_plan",
]
