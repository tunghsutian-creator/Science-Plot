"""Define immutable semantic rule, axis, and analysis contract models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from sciplot_core.policy import (
    CURVE_RENDER_OPTIONS,
    DEFAULT_RENDER_OPTIONS as _DEFAULT_RENDER_OPTIONS,
    POINT_LINE_RENDER_OPTIONS,
)
from sciplot_core.study_model import experiment_recommendation_payload

from sciplot_core.materials_rules.unit_formatting import (
    format_unit_label,
)

ELONGATION_AT_BREAK_METRIC = "elongation_at_break_percent"


LEGACY_STRAIN_AT_BREAK_METRIC = "strain_at_break_percent"


ELONGATION_AT_BREAK_IQR_METRIC = "elongation_at_break_iqr_percent"


ELONGATION_AT_BREAK_LABEL = "Elongation at break (%)"


RenderAdapterId = Literal[
    "performance",
    "impact",
    "mechanical",
    "dma_temperature",
    "rheology",
    "generic",
]


ScientificSourceAdapterId = Literal[
    "stress_relaxation",
    "dma_temperature",
    "ftir",
    "rheology_frequency",
    "rheology_temperature",
    "registered_paired_curve",
    "gpc_sec",
    "swelling",
]


FigurePlanAdapterId = Literal[
    "dma_temperature",
    "impact",
    "mechanical",
    "performance",
    "registered_single_curve",
    "rheology_frequency",
    "rheology_temperature",
]


PreparationAdapterId = Literal["rheology", "curve_family", "mechanical"]


@dataclass(frozen=True)
class AxisSpec:
    canonical_label: str
    canonical_unit: str
    display_label: str
    aliases: tuple[str, ...] = ()
    priority_labels: tuple[str, ...] = ()
    scale: str = "linear"
    reverse: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "canonical_label": self.canonical_label,
            "canonical_unit": self.canonical_unit,
            "display_label": self.display_label,
            "aliases": list(self.aliases),
            "priority_labels": list(self.priority_labels),
            "scale": self.scale,
            "reverse": self.reverse,
        }


@dataclass(frozen=True)
class AnalysisSpec:
    metric: str
    method: str
    required_inputs: tuple[str, ...] = ()
    unit: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "method": self.method,
            "required_inputs": list(self.required_inputs),
            "unit": format_unit_label(self.unit),
        }


@dataclass(frozen=True)
class SemanticRule:
    rule_id: str
    semantic_family: str
    recipe: str | None
    template: str
    x_axis: AxisSpec
    y_axis: AxisSpec
    render_adapter: RenderAdapterId = "generic"
    scientific_source_adapter: ScientificSourceAdapterId | None = None
    figure_plan_adapter: FigurePlanAdapterId | None = None
    preparation_adapter: PreparationAdapterId | None = None
    presentation_data_shape: str = "series"
    supported_templates: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    path_keywords: tuple[str, ...] = ()
    column_aliases: tuple[str, ...] = ()
    vendor_models: tuple[str, ...] = ()
    experiment_families: tuple[str, ...] = ()
    render_options: dict[str, Any] = field(default_factory=dict)
    analysis: tuple[AnalysisSpec, ...] = ()
    available_metrics: tuple[str, ...] = ()
    fixture_path: str | None = None
    fixture_status: str = "pending"
    priority: int = 100
    reason: str = ""

    @property
    def presentation_templates(self) -> tuple[str, ...]:
        return self.supported_templates or (self.template,)

    def presentation_contract_payload(self) -> dict[str, Any]:
        return {
            "kind": "sciplot_presentation_contract",
            "version": 1,
            "data_shape": self.presentation_data_shape,
            "default_template": self.template,
            "supported_templates": list(self.presentation_templates),
            "selection_policy": "explicit_supported_template_or_default",
        }

    def invocation_contract_payload(self) -> dict[str, Any]:
        """Project this rule into the existing plan/autoplot call surface."""

        ready = self.fixture_status == "ready"
        return {
            "kind": "sciplot_rule_invocation",
            "version": 1,
            "availability": "ready" if ready else "needs_rule_repair",
            "reason_codes": [] if ready else ["fixture_backed_rule_acceptance"],
            "operations": {"preview": "plan", "render": "autoplot"},
            "required_arguments": ["input", "template"],
            "fixed_arguments": {"rule": self.rule_id},
            "template": {
                "argument": "template",
                "default": self.template,
                "choices": list(self.presentation_templates),
            },
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "semantic_family": self.semantic_family,
            "recipe": self.recipe,
            "template": self.template,
            "presentation_contract": self.presentation_contract_payload(),
            "invocation": self.invocation_contract_payload(),
            "axis_plan": {"x": self.x_axis.to_payload(), "y": self.y_axis.to_payload()},
            "unit_plan": {
                "x": format_unit_label(self.x_axis.canonical_unit),
                "y": format_unit_label(self.y_axis.canonical_unit),
            },
            "analysis_plan": [item.to_payload() for item in self.analysis],
            "available_metrics": list(
                self.available_metrics or tuple(item.metric for item in self.analysis)
            ),
            "experiment_recommendation": experiment_recommendation_payload(
                rule_id=self.rule_id,
                semantic_family=self.semantic_family,
                experiment_type_id=self.rule_id,
            ),
            "keywords": list(self.keywords),
            "path_keywords": list(self.path_keywords),
            "column_aliases": list(self.column_aliases),
            "render_options": dict(self.render_options),
            "fixture_path": self.fixture_path,
            "fixture_status": self.fixture_status,
            "priority": self.priority,
            "reason": self.reason,
        }


def _rule(
    rule_id: str,
    semantic_family: str,
    recipe: str | None,
    template: str,
    x: AxisSpec,
    y: AxisSpec,
    *,
    keywords: tuple[str, ...] = (),
    path_keywords: tuple[str, ...] = (),
    column_aliases: tuple[str, ...] = (),
    vendor_models: tuple[str, ...] = (),
    experiment_families: tuple[str, ...] = (),
    render_options: dict[str, Any] | None = None,
    analysis: tuple[AnalysisSpec, ...] = (),
    available_metrics: tuple[str, ...] = (),
    fixture_path: str | None = None,
    fixture_status: str = "pending",
    priority: int = 100,
    reason: str = "",
    presentation_data_shape: str = "series",
    supported_templates: tuple[str, ...] = (),
    render_adapter: RenderAdapterId = "generic",
    scientific_source_adapter: ScientificSourceAdapterId | None = None,
    figure_plan_adapter: FigurePlanAdapterId | None = None,
    preparation_adapter: PreparationAdapterId | None = None,
) -> SemanticRule:
    normalized_templates = tuple(
        dict.fromkeys(
            str(item).strip()
            for item in (supported_templates or (template,))
            if str(item).strip()
        )
    )
    if template not in normalized_templates:
        raise ValueError(
            f"Default template `{template}` must be included in supported_templates "
            f"for material rule `{rule_id}`."
        )
    default_options = {
        "point_line": POINT_LINE_RENDER_OPTIONS,
        "curve": CURVE_RENDER_OPTIONS,
    }.get(template, _DEFAULT_RENDER_OPTIONS)
    return SemanticRule(
        rule_id=rule_id,
        semantic_family=semantic_family,
        recipe=recipe,
        template=template,
        x_axis=x,
        y_axis=y,
        render_adapter=render_adapter,
        scientific_source_adapter=scientific_source_adapter,
        figure_plan_adapter=figure_plan_adapter,
        preparation_adapter=preparation_adapter,
        presentation_data_shape=presentation_data_shape,
        supported_templates=normalized_templates,
        keywords=keywords,
        path_keywords=path_keywords,
        column_aliases=column_aliases,
        vendor_models=vendor_models,
        experiment_families=experiment_families,
        render_options={**default_options, **(render_options or {})},
        analysis=analysis,
        available_metrics=available_metrics,
        fixture_path=fixture_path,
        fixture_status=fixture_status,
        priority=priority,
        reason=reason,
    )
