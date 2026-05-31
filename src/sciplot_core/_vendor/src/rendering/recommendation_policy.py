from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from src.rendering.recommender_models import TemplateRecommendation
from src.rendering.template_catalog import DEFAULT_TEMPLATE_CATALOG

PRIMARY_SCORE_GAP_THRESHOLD = 1.5
ALTERNATIVE_SCORE_GAP_THRESHOLD = 12.0
ALTERNATIVE_FAMILY_QUOTA = 2
VISIBLE_ALTERNATIVE_LIMIT = 3


@dataclass(frozen=True)
class RecommendationPresentation:
    primary_recommendation: tuple[TemplateRecommendation, ...]
    alternative_recommendations: tuple[TemplateRecommendation, ...]
    advanced_templates: tuple[TemplateRecommendation, ...]
    visible_recommendations: tuple[TemplateRecommendation, ...]
    score_gap_to_second_primary: float


def _candidate_family(template_id: str) -> str:
    try:
        return DEFAULT_TEMPLATE_CATALOG.get(template_id).family
    except Exception:
        return "other"


def _canonical_priority_key(recommendation: TemplateRecommendation) -> tuple[int, float, int, str]:
    return (
        0 if recommendation.role == "canonical" else 1,
        -float(recommendation.score),
        int(recommendation.rank or 9999),
        recommendation.template_id,
    )


def _best_visible_candidate(
    candidates: Sequence[TemplateRecommendation],
) -> TemplateRecommendation:
    return min(candidates, key=_canonical_priority_key)


def _group_by_canonical_id(
    recommendations: Sequence[TemplateRecommendation],
) -> list[TemplateRecommendation]:
    grouped: dict[str, list[TemplateRecommendation]] = defaultdict(list)
    for recommendation in recommendations:
        canonical_id = recommendation.canonical_id or recommendation.template_id
        grouped[canonical_id].append(recommendation)

    visible: list[TemplateRecommendation] = []
    for _canonical_id, group in grouped.items():
        best = _best_visible_candidate(group)
        visible.append(best)
    visible.sort(key=_canonical_priority_key)
    return visible


def build_recommendation_presentation(
    recommendations: Sequence[TemplateRecommendation],
    *,
    primary_gap_threshold: float = PRIMARY_SCORE_GAP_THRESHOLD,
    alternative_gap_threshold: float = ALTERNATIVE_SCORE_GAP_THRESHOLD,
    alternative_family_quota: int = ALTERNATIVE_FAMILY_QUOTA,
    visible_alternative_limit: int = VISIBLE_ALTERNATIVE_LIMIT,
) -> RecommendationPresentation:
    visible_candidates = _group_by_canonical_id(recommendations)
    if not visible_candidates:
        return RecommendationPresentation((), (), (), (), 0.0)

    top_score = float(visible_candidates[0].score)
    primary: list[TemplateRecommendation] = [visible_candidates[0]]
    for candidate in visible_candidates[1:]:
        score_gap = top_score - float(candidate.score)
        if score_gap <= primary_gap_threshold and len(primary) < 2:
            primary.append(candidate)
        else:
            break

    selected_ids = {item.template_id for item in primary}
    family_counts: dict[str, int] = defaultdict(int)
    for item in primary:
        family_counts[_candidate_family(item.template_id)] += 1

    alternative: list[TemplateRecommendation] = []
    advanced: list[TemplateRecommendation] = []
    advanced_ids: set[str] = set()
    remaining_families = {
        _candidate_family(candidate.template_id)
        for candidate in visible_candidates
        if candidate.template_id not in selected_ids
    }

    for candidate in visible_candidates[1 + max(len(primary) - 1, 0) :]:
        if candidate.template_id in selected_ids:
            continue
        family = _candidate_family(candidate.template_id)
        score_gap = top_score - float(candidate.score)
        if score_gap <= alternative_gap_threshold and len(alternative) < visible_alternative_limit:
            family_quota_reached = family_counts[family] >= alternative_family_quota
            other_families_available = bool(remaining_families - {family})
            if family_quota_reached and other_families_available:
                advanced.append(candidate)
                advanced_ids.add(candidate.template_id)
            else:
                alternative.append(candidate)
                selected_ids.add(candidate.template_id)
                family_counts[family] += 1
        else:
            advanced.append(candidate)
            advanced_ids.add(candidate.template_id)

    # Preserve lower-scoring but still valid candidates in the advanced lane.
    for candidate in visible_candidates:
        if candidate.template_id in selected_ids or candidate.template_id in advanced_ids:
            continue
        advanced.append(candidate)

    second_primary_gap = top_score - float(primary[1].score) if len(primary) > 1 else (
        top_score - float(alternative[0].score) if alternative else 0.0
    )
    return RecommendationPresentation(
        primary_recommendation=tuple(primary),
        alternative_recommendations=tuple(alternative),
        advanced_templates=tuple(advanced),
        visible_recommendations=tuple([*primary, *alternative]),
        score_gap_to_second_primary=round(max(0.0, second_primary_gap), 1),
    )


__all__ = [
    "ALTERNATIVE_FAMILY_QUOTA",
    "ALTERNATIVE_SCORE_GAP_THRESHOLD",
    "PRIMARY_SCORE_GAP_THRESHOLD",
    "RecommendationPresentation",
    "VISIBLE_ALTERNATIVE_LIMIT",
    "build_recommendation_presentation",
]
