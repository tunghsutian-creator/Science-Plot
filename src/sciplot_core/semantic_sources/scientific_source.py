"""Resolve one source-bound scientific snapshot for shared plot orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.materials_rules import get_rule
from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.semantic_sources.scientific_source_models import (
    ResolvedScientificSource,
    ScientificSourceDomain,
    ScientificSourceResolutionError,
)


def resolve_scientific_source(
    source: Path,
    *,
    rule_id: str | None,
    request: dict[str, Any],
    template: str,
    study_model: dict[str, Any] | None = None,
) -> ResolvedScientificSource | None:
    """Resolve a registered scientific source once without writes or caching."""

    resolved_source = source.expanduser().resolve()
    normalized_rule = str(rule_id or "").strip()
    if not normalized_rule:
        return None
    try:
        rule = get_rule(normalized_rule)
    except ValueError:
        return None
    if rule.fixture_status != "ready":
        return None
    adapter = rule.scientific_source_adapter
    if adapter == "stress_relaxation":
        return _resolve_stress_relaxation_scientific_source(
            resolved_source,
            rule=rule,
            request=request,
            template=template,
        )
    if adapter == "dma_temperature":
        return _resolve_dma_temperature_scientific_source(
            resolved_source,
            rule_id=normalized_rule,
            request=request,
            template=template,
        )
    if adapter == "rheology_frequency":
        return _resolve_rheology_frequency_scientific_source(
            resolved_source,
            rule_id=normalized_rule,
            request=request,
            study_model=study_model or {},
        )
    if adapter == "rheology_temperature":
        return _resolve_rheology_temperature_scientific_source(
            resolved_source,
            rule_id=normalized_rule,
            request=request,
        )
    if rule.figure_plan_adapter == "registered_single_curve":
        from sciplot_core.semantic_sources.scientific_source_single_curve import (
            resolve_single_curve_scientific_source,
        )

        return resolve_single_curve_scientific_source(
            resolved_source,
            rule=rule,
            request=request,
            template=template,
        )
    return None


def _resolve_stress_relaxation_scientific_source(
    source: Path,
    *,
    rule: SemanticRule,
    request: dict[str, Any],
    template: str,
) -> ResolvedScientificSource:
    from sciplot_core.semantic_sources.scientific_source_single_curve import (
        bind_single_curve_scientific_source,
        require_single_curve_source_sha256,
    )
    from sciplot_core.semantic_sources.stress_relaxation_transform import (
        resolve_stress_relaxation_transform,
    )

    source_sha256_before = require_single_curve_source_sha256(source, rule=rule)
    try:
        transform = resolve_stress_relaxation_transform(
            source,
            series_order=request.get("series_order"),
        )
    except (OSError, ValueError) as exc:
        raise ScientificSourceResolutionError(
            "stress_relaxation_transform_invalid",
            str(exc),
        ) from exc
    return bind_single_curve_scientific_source(
        source,
        rule=rule,
        request=request,
        template=template,
        transform=transform,
        source_sha256_before=source_sha256_before,
    )


def _resolve_dma_temperature_scientific_source(
    source: Path,
    *,
    rule_id: str,
    request: dict[str, Any],
    template: str,
) -> ResolvedScientificSource:
    from sciplot_core.figure_plan.errors import FigurePlanResolutionError
    from sciplot_core.figure_plan.dma_temperature_resolution import (
        resolve_dma_temperature_plan,
        resolve_dma_temperature_source,
    )

    try:
        domain = resolve_dma_temperature_source(
            source,
            series_order=request.get("series_order"),
        )
        figure_plan = resolve_dma_temperature_plan(
            input_path=source,
            request={**request, "template": template},
            source_resolution=domain,
        )
    except FigurePlanResolutionError as exc:
        raise ScientificSourceResolutionError(exc.reason_code, str(exc)) from exc
    return ResolvedScientificSource(
        rule_id=rule_id,
        source=source,
        domain=domain.scientific_transform,
        figure_plan=figure_plan,
        source_sha256=domain.facts.source_sha256,
    )


def _resolve_rheology_temperature_scientific_source(
    source: Path,
    *,
    rule_id: str,
    request: dict[str, Any],
) -> ResolvedScientificSource:
    from sciplot_core.figure_plan.errors import FigurePlanResolutionError
    from sciplot_core.figure_plan.temperature_resolution import (
        resolve_temperature_plan,
    )
    from sciplot_core.semantic_sources.rheology_temperature_domain import (
        RheologyTemperatureDomainError,
        resolve_rheology_temperature_domain,
    )

    try:
        domain = resolve_rheology_temperature_domain(source, request=request)
    except RheologyTemperatureDomainError as exc:
        raise ScientificSourceResolutionError(exc.reason_code, str(exc)) from exc
    try:
        figure_plan = resolve_temperature_plan(
            input_path=source,
            request=request,
            source_resolution=domain,
        )
    except FigurePlanResolutionError as exc:
        raise ScientificSourceResolutionError(exc.reason_code, str(exc)) from exc
    return ResolvedScientificSource(
        rule_id=rule_id,
        source=source,
        domain=domain,
        figure_plan=figure_plan,
        source_sha256=domain.source_sha256,
    )


def _resolve_rheology_frequency_scientific_source(
    source: Path,
    *,
    rule_id: str,
    request: dict[str, Any],
    study_model: dict[str, Any],
) -> ResolvedScientificSource | None:
    if not source.is_dir():
        return None
    from sciplot_core.figure_plan.frequency_resolution import resolve_frequency_plan
    from sciplot_core.semantic_sources.rheology_sweep_domain import (
        RheologySweepDomainError,
        resolve_rheology_frequency_domain,
    )

    try:
        domain = resolve_rheology_frequency_domain(source, request=request)
    except RheologySweepDomainError as exc:
        raise ScientificSourceResolutionError(exc.reason_code, str(exc)) from exc
    figure_plan = resolve_frequency_plan(
        study_model=study_model,
        input_path=source,
        request=request,
        source_resolution=domain,
    )
    return ResolvedScientificSource(
        rule_id=rule_id,
        source=source,
        domain=domain,
        figure_plan=figure_plan,
        source_sha256=domain.source_sha256,
    )


__all__ = [
    "ResolvedScientificSource",
    "ScientificSourceDomain",
    "ScientificSourceResolutionError",
    "resolve_scientific_source",
]
