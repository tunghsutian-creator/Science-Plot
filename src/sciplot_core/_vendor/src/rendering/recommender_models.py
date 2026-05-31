from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.rendering.dataset_models import NormalizedDataset


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


class TemplateRecommender(Protocol):
    def recommend(self, dataset: NormalizedDataset, limit: int = 5) -> tuple[TemplateRecommendation, ...]: ...


__all__ = ["TemplateRecommendation", "TemplateRecommender"]
