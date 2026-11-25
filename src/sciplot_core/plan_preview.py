"""Build one read-only machine projection of the current FigurePlan."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.data_mapping.plan_binding import (
    resolve_mapping_plan_request,
    verify_mapping_sample_identity,
)

from sciplot_core.figure_plan import (
    FigurePlanResolutionError,
    resolve_figure_plan,
)
from sciplot_core.materials_rules import SemanticRule, get_rule
from sciplot_core.materials_rules.catalog import resolve_rule_template
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.plan_admission import expected_plan_request, require_expected_observation
from sciplot_core.plan_identity import preview_identity_for
from sciplot_core.plan_preview_contract import (
    PLAN_PREVIEW_KIND,
    PLAN_PREVIEW_VERSION,
    PlanPreviewBase as PlanPreviewBase,
    PlanPreviewBlocker,
    PlanPreviewPayload,
    PlanPreviewStatus,
    _blocked_preview,
    _preview_base,
)
from sciplot_core.readiness.registry_io import load_validated_envelope_registry
from sciplot_core.readiness.rule_certification import (
    current_rule_invocation_contract_payload,
)
from sciplot_core.semantic import classify_source
from sciplot_core.semantic_sources.scientific_source import (
    ResolvedScientificSource,
    ScientificSourceResolutionError,
    resolve_scientific_source,
)
from sciplot_core.study_model import study_model_from_request


@dataclass(frozen=True, slots=True)
class PlanPreviewResolution:
    """One operation's preview projection and its live scientific facts."""

    payload: PlanPreviewPayload
    scientific_source: ResolvedScientificSource | None = None


def build_plan_preview(input_path: Path, *, request: dict[str, Any]) -> PlanPreviewPayload:
    """Project the current plan for public consumers; observed data stay in memory."""

    return resolve_plan_preview(input_path, request=request).payload


def resolve_plan_preview(
    input_path: Path,
    *,
    request: dict[str, Any],
    _replay_categorical: bool = False,
) -> PlanPreviewResolution:
    """Observe a source once for the preview and any same-operation consumer."""

    def blocked(**kwargs: Any) -> PlanPreviewResolution:
        return PlanPreviewResolution(_blocked_preview(**kwargs))

    source = input_path.expanduser().resolve()
    if "categorical_binding" in request:
        from sciplot_core.categorical_plan import categorical_preview

        return PlanPreviewResolution(categorical_preview(source, request=request, current_identity=not _replay_categorical))
    if "data_mapping_execution" in request or "data_mapping_proposal_id" in request:
        return _build_mapped_plan_preview(source, request=request)
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
            return blocked(
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
            return blocked(
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
            return blocked(
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
            return blocked(
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
        return blocked(
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
        return blocked(
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
                return blocked(
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
    if inspection_error and not source.is_dir():
        return blocked(
            source=source,
            rule_id=rule_id,
            template=template,
            reason_code="plan_source_inspection_failed",
            message=str(inspection_error),
        )
    from sciplot_core.plan_source_options import validate_source_options

    try:
        options = validate_source_options(source, request_snapshot, rule_id=rule_id, template=template)
    except ValueError as exc:
        return blocked(source=source, rule_id=rule_id, template=template,
            reason_code="plan_source_option_invalid", message=str(exc))
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
        return blocked(
            source=source,
            rule_id=rule_id,
            template=template,
            reason_code=exc.reason_code,
            message=str(exc),
            issues=getattr(exc, "issues", None),
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
        return blocked(
            source=source,
            rule_id=rule_id,
            template=template,
            reason_code=exc.reason_code,
            message=str(exc),
            scientific_transform=scientific_transform,
        )
    if inspection_error and plan is None:
        # A generic file reader cannot validate a directory. Only a complete
        # plan from its existing scientific owner can supersede that failure.
        return blocked(
            source=source, rule_id=rule_id, template=template,
            reason_code="plan_source_inspection_failed", message=str(inspection_error),
        )
    try:
        source_still_current = (
            source_hash is not None and source_tree_sha256(source) == source_hash
        )
    except OSError:
        source_still_current = False
    if not source_still_current or (
        resolved_scientific_source is not None
        and resolved_scientific_source.source_sha256 != source_hash
    ):
        return blocked(
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
    if options:
        payload["source_options"] = options
    assert source_hash is not None
    payload["preview_identity"] = preview_identity_for(
        dict(payload), source_sha256=source_hash
    )
    return PlanPreviewResolution(payload, resolved_scientific_source)


def _build_mapped_plan_preview(
    source: Path, *, request: dict[str, Any]
) -> PlanPreviewResolution:
    """Keep original identity while scientific owners resolve the mapped table."""

    try:
        canonical_request, binding = resolve_mapping_plan_request(source, request)
        from sciplot_core.data_mapping.plan_binding import mapped_preview_request

        effective_request = mapped_preview_request(canonical_request, binding)
        resolved = resolve_plan_preview(
            Path(binding["effective_input"]), request=effective_request
        )
        payload = resolved.payload
        if payload["status"] != "blocked":
            verify_mapping_sample_identity(binding, payload["scientific_transform"])
        # Verification after scientific resolution guards both the original
        # source and every immutable execution artifact against concurrent edits.
        _current_request, current_binding = resolve_mapping_plan_request(source, request)
        if current_binding != binding:
            raise ValueError("The confirmed mapping changed during plan resolution.")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return PlanPreviewResolution(_blocked_preview(
            source=source,
            rule_id=request.get("rule_id"),
            template=str(request.get("template") or "curve"),
            reason_code="plan_mapping_invalid",
            message=str(exc),
        ))
    payload["source"] = str(source)
    payload["data_mapping"] = binding
    if payload["status"] != "blocked":
        payload["preview_identity"] = preview_identity_for(
            dict(payload), source_sha256=binding["original_input_sha256"]
        )
    return resolved


def verify_expected_plan(
    source: Path,
    expected: dict[str, Any],
    *,
    rule_id: str | None,
    template: str | None,
) -> dict[str, Any]:
    """Verify an external preview and return its public projection."""

    return dict(resolve_expected_plan(source, expected, rule_id=rule_id, template=template).payload)


def resolve_expected_plan(
    source: Path,
    expected: dict[str, Any],
    *,
    rule_id: str | None,
    template: str | None,
    observed: PlanPreviewResolution | None = None,
) -> PlanPreviewResolution:
    """Bind a current expectation, reusing only this operation's observation."""

    selected, digest = expected_plan_request(source, expected, rule_id=rule_id, template=template)
    resolved = observed or resolve_plan_preview(
        source,
        request={key: value for key, value in selected.items() if value is not None},
        _replay_categorical=True,
    )
    require_expected_observation(source, expected, resolved.payload, selected=selected,
                                 digest=digest, reused_observation=observed is not None)
    return resolved


__all__ = [
    "PLAN_PREVIEW_KIND",
    "PLAN_PREVIEW_VERSION",
    "PlanPreviewBlocker",
    "PlanPreviewPayload",
    "PlanPreviewStatus",
    "build_plan_preview",
    "verify_expected_plan",
]
