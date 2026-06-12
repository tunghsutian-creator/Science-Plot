from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import matplotlib.pyplot as plt

if TYPE_CHECKING:
    from src.rendering.recommender_models import TemplateRecommendation

TemplateName = str
OutputMode = str
RenderFn = Callable[[Path, str | int, "RenderOptions"], list["RenderedPlot"]]


@dataclass(frozen=True)
class RenderOptions:
    width_mm: float
    height_mm: float
    xscale: str
    yscale: str
    reverse_x: bool
    baseline: str
    show_colorbar: bool
    style_preset: str
    palette_preset: str
    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    x_padding_fraction: float | None = None
    x_tick_density: str | None = None
    y_tick_density: str | None = None
    x_tick_edge_labels: str | None = None
    y_tick_edge_labels: str | None = None
    series_order: tuple[str, ...] | None = None
    series_styles: tuple[Mapping[str, Any], ...] | None = None
    series_offsets: tuple[Mapping[str, Any], ...] | None = None
    legend_position: str = "auto"
    series_label_mode: str = "legend"
    x_label_override: str | None = None
    y_label_override: str | None = None
    use_sidecar: bool | None = None
    visual_theme_id: str | None = None
    custom_theme_id: str | None = None
    custom_theme_draft: Mapping[str, Any] | None = None
    fit_options: dict[str, Any] | None = None
    extra_x_axis: Mapping[str, Any] | None = None
    extra_y_axis: Mapping[str, Any] | None = None
    x_axis_breaks: tuple[Mapping[str, Any], ...] | None = None
    y_axis_breaks: tuple[Mapping[str, Any], ...] | None = None
    reference_guides: tuple[Mapping[str, Any], ...] | None = None
    text_annotations: tuple[Mapping[str, Any], ...] | None = None
    shape_annotations: tuple[Mapping[str, Any], ...] | None = None
    analytical_layers: tuple[Mapping[str, Any], ...] | None = None
    data_variables: tuple[Mapping[str, Any], ...] | None = None
    data_transforms: tuple[Mapping[str, Any], ...] | None = None


@dataclass(frozen=True)
class TemplateRenderer:
    render: RenderFn


@dataclass(frozen=True)
class QAIssue:
    id: str
    severity: str
    metric_value: float | str | None
    target: float | str | None
    message: str


@dataclass(frozen=True)
class QAReport:
    score: float
    grade: str
    issues: tuple[QAIssue, ...] = ()
    autofixes_applied: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubmissionCheck:
    id: str
    status: str
    message: str
    metric_value: float | str | None = None
    target: float | str | None = None
    source: str | None = None


@dataclass(frozen=True)
class SubmissionReport:
    context: str
    readiness: str
    summary: str
    template: str | None = None
    style_preset: str | None = None
    palette_preset: str | None = None
    output_count: int = 0
    output_filenames: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    checks: tuple[SubmissionCheck, ...] = ()


@dataclass(frozen=True)
class RenderedPlot:
    filename: str
    figure: plt.Figure
    qa_report: QAReport | None = None
    submission_report: SubmissionReport | None = None


@dataclass(frozen=True)
class Recommendation:
    template: TemplateName
    reason: str
    size: str | None = None
    xscale: str | None = None
    yscale: str | None = None
    reverse_x: bool | None = None
    baseline: str | None = None
    show_colorbar: bool | None = None
    style_preset: str | None = None
    palette_preset: str | None = None
    use_sidecar: bool | None = None
    visual_theme_id: str | None = None


@dataclass(frozen=True)
class InputInspection:
    model: str
    model_label: str
    recommendations: tuple[TemplateRecommendation, ...] = ()
    primary_recommendation: tuple[TemplateRecommendation, ...] = ()
    alternative_recommendations: tuple[TemplateRecommendation, ...] = ()
    advanced_templates: tuple[TemplateRecommendation, ...] = ()
    recommendation_confidence: float = 0.0
    recommendation_summary: str = ""
    warnings: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreflightResult:
    template: TemplateName
    requested_template_id: str
    canonical_id: str
    role: str
    lifecycle_policy: str
    implementation_id: str
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    output_filenames: tuple[str, ...]
    submission_report: SubmissionReport | None = None
