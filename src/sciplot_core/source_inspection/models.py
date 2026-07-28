"""Define the stable data contract returned by source inspection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TemplateRecommendation:
    template_id: str
    score: float
    why_hard_match: tuple[str, ...]
    why_soft_prior: tuple[str, ...]
    inferred_mapping: dict[str, str]
    optional_enhancements: tuple[str, ...]
    preview_config_summary: dict[str, Any]
    experiment_family: str | None = None
    role_hints: tuple[str, ...] = ()
    recommendation_reason: str | None = None
    recommended_action: str | None = None
    default_render_overrides: dict[str, Any] | None = None
    rank: int | None = None
    reason: str = ""
    suitability_hint: str = ""
    score_gap_to_top: float = 0.0
    canonical_id: str = ""
    role: str = "canonical"
    lifecycle_policy: str = "canonical"
    implementation_id: str = ""
    recommendation_source: str = "rule"


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
class SourceIntent:
    experiment_family: str
    model: str
    recommended_template: str
    reason: str
    x_label: str = ""
    y_label: str = ""
    xscale: str | None = None
    yscale: str | None = None
    reverse_x: bool | None = None
    baseline: str | None = None
    metric_columns: tuple[str, ...] = ()

    @property
    def signals(self) -> tuple[str, ...]:
        signals = [
            f"Detected {self.experiment_family} plot source.",
            self.reason,
        ]
        if self.x_label and self.y_label:
            signals.append(f"Mapped {self.x_label} to X and {self.y_label} to Y.")
        if self.metric_columns:
            signals.append(f"Detected metrics: {', '.join(self.metric_columns)}.")
        return tuple(signals)


__all__ = ["InputInspection", "SourceIntent", "TemplateRecommendation"]
