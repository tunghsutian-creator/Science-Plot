"""Orchestrate source recognition and supported-template recommendation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sciplot_core.source_inspection.model_recognition import (
    RecognizedSource,
    recognize_source,
)
from sciplot_core.source_inspection.models import (
    InputInspection,
    TemplateRecommendation,
)
from sciplot_core.source_inspection.recommendation_building import (
    recommendation_confidence,
    recommendation_summary,
    template_recommendation,
)
from sciplot_core.source_inspection.source_plans import recommendation_plan


MODEL_LABELS = {
    "curve_table": "Paired curve table (curve_table)",
    "tensile_curve": "Tensile stress-strain curve (tensile_curve)",
    "replicate_table": "Replicate wide table (replicate_table)",
    "heatmap_table": "Heatmap long table (xyz_long_table)",
    "frequency_sweep": "Frequency sweep export table",
    "frequency_metric_sheet": "Frequency sweep metric sheet",
    "temperature_sweep": "Temperature sweep export table",
    "stress_relaxation": "Stress relaxation export table",
    "table_summary": "Compact metrics/table figure input",
}


def _mapping(
    recognized: RecognizedSource,
) -> tuple[dict[str, str], tuple[str, ...]]:
    if recognized.curves:
        first = recognized.curves[0]
        return (
            {"x": first.x_label, "y": first.y_label},
            (
                f"x:{first.x_label}",
                f"y:{first.y_label}",
                "series:" + ", ".join(curve.sample for curve in recognized.curves[:3]),
            ),
        )
    if recognized.replicate_groups:
        first = recognized.replicate_groups[0]
        return (
            {"group": "sample", "value": first.value_label},
            (
                "group:"
                + ", ".join(group.group for group in recognized.replicate_groups[:3]),
            ),
        )
    if recognized.heatmap is not None:
        table = recognized.heatmap
        return (
            {"x": table.x_label, "y": table.y_label, "z": table.z_label},
            (
                f"x:{table.x_label}",
                f"y:{table.y_label}",
                f"z:{table.z_label}",
            ),
        )
    if recognized.intent is not None:
        return (
            {
                key: value
                for key, value in {
                    "x": recognized.intent.x_label,
                    "y": recognized.intent.y_label,
                }.items()
                if value
            },
            (),
        )
    return {}, ()


def _experiment_family(recognized: RecognizedSource) -> str | None:
    if recognized.intent is not None:
        return recognized.intent.experiment_family
    if recognized.model in {
        "frequency_sweep",
        "frequency_metric_sheet",
        "temperature_sweep",
        "stress_relaxation",
    }:
        return "rheology"
    return None


def _inspect_uncached(source: Path, sheet: str | int) -> InputInspection:
    recognized = recognize_source(source, sheet)
    plan = recommendation_plan(source, recognized)
    mapping, role_hints = _mapping(recognized)
    family = _experiment_family(recognized)
    top = template_recommendation(
        plan.template,
        score=plan.score,
        reason=plan.reason,
        rank=1,
        top_score=plan.score,
        model=recognized.model,
        inferred_mapping=mapping,
        experiment_family=family,
        role_hints=role_hints,
        **plan.overrides,
    )
    alternatives = tuple(
        template_recommendation(
            template,
            score=score,
            reason=reason,
            rank=index,
            top_score=plan.score,
            model=recognized.model,
            inferred_mapping=mapping,
            experiment_family=family,
            role_hints=role_hints,
        )
        for index, (template, score, reason) in enumerate(
            plan.alternatives,
            start=2,
        )
    )
    ranked: tuple[TemplateRecommendation, ...] = (top, *alternatives)
    confidence = (
        plan.confidence
        if plan.confidence is not None
        else recommendation_confidence(ranked)
    )
    label = MODEL_LABELS.get(recognized.model, recognized.model)
    return InputInspection(
        model=recognized.model,
        model_label=label,
        recommendations=ranked,
        primary_recommendation=(top,),
        alternative_recommendations=alternatives[:3],
        advanced_templates=alternatives[3:],
        recommendation_confidence=confidence,
        recommendation_summary=recommendation_summary(
            model_label=label,
            recommendations=ranked,
            confidence=confidence,
        ),
        warnings=plan.warnings,
        signals=plan.signals,
    )


@lru_cache(maxsize=64)
def _inspect_cached(
    resolved_path: str,
    _mtime_ns: int,
    sheet: str | int,
) -> InputInspection:
    return _inspect_uncached(Path(resolved_path), sheet)


def inspect_input_file(
    input_path: Path,
    sheet: str | int = 0,
) -> InputInspection:
    """Inspect one source file and rank only currently supported templates."""

    source = Path(input_path)
    return _inspect_cached(str(source.resolve()), source.stat().st_mtime_ns, sheet)


def clear_inspection_cache() -> None:
    _inspect_cached.cache_clear()


__all__ = ["clear_inspection_cache", "inspect_input_file"]
