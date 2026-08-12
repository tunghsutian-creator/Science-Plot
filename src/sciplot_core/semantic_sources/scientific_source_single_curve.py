"""Bind one resolved curve transform to the shared single-task plan."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)

if TYPE_CHECKING:
    from sciplot_core.semantic_sources.scientific_source_models import (
        ResolvedScientificSource,
    )


def bind_single_curve_scientific_source(
    source: Path,
    *,
    rule: SemanticRule,
    request: dict[str, Any],
    template: str,
    transform: ResolvedScientificTransform,
    source_sha256_before: str,
) -> ResolvedScientificSource:
    from sciplot_core.figure_plan.errors import FigurePlanResolutionError
    from sciplot_core.figure_plan.single_curve_resolution import (
        resolve_registered_single_curve_plan,
    )
    from sciplot_core.semantic_sources.scientific_source_models import (
        ResolvedScientificSource,
        ScientificSourceResolutionError,
    )

    source_sha256_after = require_single_curve_source_sha256(source, rule=rule)
    if source_sha256_after != source_sha256_before:
        raise ScientificSourceResolutionError(
            f"{rule.rule_id}_source_changed_during_resolution",
            f"The {rule.rule_id} source changed while its scientific snapshot "
            "was being resolved.",
        )
    try:
        figure_plan = resolve_registered_single_curve_plan(
            rule_id=rule.rule_id,
            request={**request, "template": template},
            source_resolution=transform,
            source_sha256=source_sha256_before,
        )
    except FigurePlanResolutionError as exc:
        raise ScientificSourceResolutionError(exc.reason_code, str(exc)) from exc
    return ResolvedScientificSource(
        rule_id=rule.rule_id,
        source=source,
        domain=transform,
        figure_plan=figure_plan,
        source_sha256=source_sha256_before,
    )


def require_single_curve_source_sha256(
    source: Path,
    *,
    rule: SemanticRule,
) -> str:
    """Fingerprint one source at an explicit scientific-resolution boundary."""

    from sciplot_core.figure_plan.source_binding import source_tree_sha256
    from sciplot_core.semantic_sources.scientific_source_models import (
        ScientificSourceResolutionError,
    )

    try:
        source_sha256 = source_tree_sha256(source)
    except OSError as exc:
        raise ScientificSourceResolutionError(
            f"{rule.rule_id}_source_unavailable",
            f"SciPlot could not fingerprint the {rule.rule_id} source: {exc}",
        ) from exc
    if source_sha256 is None:
        raise ScientificSourceResolutionError(
            f"{rule.rule_id}_source_unavailable",
            f"SciPlot could not fingerprint the {rule.rule_id} source.",
        )
    return source_sha256


def resolve_single_curve_transform(
    source: Path,
    *,
    rule: SemanticRule,
    series_order: object = None,
) -> ResolvedScientificTransform:
    adapter = rule.scientific_source_adapter
    if adapter == "ftir":
        from sciplot_core.semantic_sources.ftir_sources import (
            resolve_ftir_scientific_transform,
        )

        return resolve_ftir_scientific_transform(
            source,
            series_order=series_order,
        )
    if adapter == "registered_paired_curve":
        from sciplot_core.semantic_sources.registered_paired_curve_transform import (
            resolve_registered_paired_curve_transform,
        )

        return resolve_registered_paired_curve_transform(
            source,
            rule=rule,
            series_order=series_order,
        )
    if adapter == "gpc_sec":
        from sciplot_core.semantic_sources.gpc_sources import (
            resolve_gpc_scientific_transform,
        )

        return resolve_gpc_scientific_transform(
            source,
            rule=rule,
            series_order=series_order,
        )
    if adapter == "swelling":
        from sciplot_core.semantic_sources.swelling_transform import (
            resolve_swelling_scientific_transform,
        )

        return resolve_swelling_scientific_transform(
            source,
            series_order=series_order,
        )
    raise ValueError(
        f"Rule {rule.rule_id!r} does not own a single-curve source adapter."
    )


def resolve_single_curve_scientific_source(
    source: Path,
    *,
    rule: SemanticRule,
    request: dict[str, Any],
    template: str,
) -> ResolvedScientificSource:
    from sciplot_core.semantic_sources.scientific_source_models import (
        ScientificSourceResolutionError,
    )

    source_sha256_before = require_single_curve_source_sha256(source, rule=rule)
    try:
        transform = resolve_single_curve_transform(
            source,
            rule=rule,
            series_order=request.get("series_order"),
        )
    except (OSError, ValueError) as exc:
        raise ScientificSourceResolutionError(
            f"{rule.rule_id}_transform_invalid",
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


__all__ = [
    "bind_single_curve_scientific_source",
    "require_single_curve_source_sha256",
    "resolve_single_curve_scientific_source",
    "resolve_single_curve_transform",
]
