from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from src.data_loader import ReplicateGroup
from src.plot_contract import template_names
from src.rendering.cache import load_replicate_table_cached
from src.rendering.common import summarize_replicate_distribution

_CANONICAL_TO_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "scatter_fit": ("scatter_with_fit",),
    "mean_band": ("replicate_curves_with_band",),
    "bar": ("grouped_bar_error", "grouped_bar_compare"),
}

_DISTRIBUTION_COMPARE_TEMPLATE_ID: Final[str] = "distribution_compare"
_DISTRIBUTION_COMPARE_FALLBACK: Final[str] = "box"

_LIFECYCLE_POLICY: Final[dict[str, str]] = {
    "scatter_with_fit": "deprecated_in_practice",
    "replicate_curves_with_band": "deprecated_in_practice",
    "grouped_bar_error": "indefinite_compat",
    "grouped_bar_compare": "indefinite_compat",
    _DISTRIBUTION_COMPARE_TEMPLATE_ID: "compat_family",
}

_ALIAS_RECOMMENDATION_PENALTY: Final[dict[str, float]] = {
    "scatter_with_fit": 5.0,
    "replicate_curves_with_band": 4.0,
    "grouped_bar_error": 4.0,
    "grouped_bar_compare": 4.0,
}

_ALIAS_TO_CANONICAL: Final[dict[str, str]] = {
    alias: canonical
    for canonical, aliases in _CANONICAL_TO_ALIASES.items()
    for alias in aliases
}


@dataclass(frozen=True)
class TemplateLifecycleEntry:
    template_id: str
    canonical_id: str
    role: str
    lifecycle_policy: str


@dataclass(frozen=True)
class TemplateIdentity:
    requested_template_id: str
    canonical_id: str
    role: str
    lifecycle_policy: str
    implementation_id: str


def distribution_compare_fallback_template_id() -> str:
    return _DISTRIBUTION_COMPARE_FALLBACK


def distribution_compare_variant_template_id(groups: Iterable[ReplicateGroup]) -> str:
    summary = summarize_replicate_distribution(list(groups))
    if summary.group_count >= 6:
        return "box"
    if summary.group_count <= 4 and summary.min_group_points >= 6:
        return "violin"
    return "box_strip"


def resolve_distribution_compare_template_id(
    input_path: Path | None,
    sheet: str | int = 0,
    *,
    fallback: str = _DISTRIBUTION_COMPARE_FALLBACK,
) -> str:
    if input_path is None:
        return fallback
    try:
        groups = load_replicate_table_cached(input_path, sheet)
    except Exception:
        return fallback
    if not groups:
        return fallback
    return distribution_compare_variant_template_id(groups)


def canonical_template_id(
    template_id: str,
    *,
    fallback_distribution: str = _DISTRIBUTION_COMPARE_FALLBACK,
) -> str:
    if template_id == _DISTRIBUTION_COMPARE_TEMPLATE_ID:
        return fallback_distribution
    return _ALIAS_TO_CANONICAL.get(template_id, template_id)


def resolve_template_id(
    template_id: str,
    *,
    input_path: Path | None = None,
    sheet: str | int = 0,
    fallback_distribution: str = _DISTRIBUTION_COMPARE_FALLBACK,
) -> str:
    if template_id == _DISTRIBUTION_COMPARE_TEMPLATE_ID:
        return resolve_distribution_compare_template_id(
            input_path,
            sheet,
            fallback=fallback_distribution,
        )
    return canonical_template_id(template_id, fallback_distribution=fallback_distribution)


def compatibility_template_ids() -> tuple[str, ...]:
    return (
        *_ALIAS_TO_CANONICAL.keys(),
        _DISTRIBUTION_COMPARE_TEMPLATE_ID,
    )


def alias_templates_for(canonical_id: str) -> tuple[str, ...]:
    return _CANONICAL_TO_ALIASES.get(canonical_id, ())


def template_family_ids(canonical_id: str) -> tuple[str, ...]:
    return (canonical_id, *alias_templates_for(canonical_id))


def alias_lifecycle_policy(template_id: str) -> str:
    return _LIFECYCLE_POLICY.get(template_id, "canonical")


def template_role(template_id: str) -> str:
    if template_id == _DISTRIBUTION_COMPARE_TEMPLATE_ID:
        return "family_alias"
    return "alias" if canonical_template_id(template_id) != template_id else "canonical"


def alias_recommendation_penalty(template_id: str) -> float:
    return float(_ALIAS_RECOMMENDATION_PENALTY.get(template_id, 0.0))


def is_supported_template_id(template_id: str) -> bool:
    return template_id in template_names() or template_id in compatibility_template_ids()


def template_identity(
    template_id: str,
    *,
    resolved_template_id: str | None = None,
    input_path: Path | None = None,
    sheet: str | int = 0,
    fallback_distribution: str = _DISTRIBUTION_COMPARE_FALLBACK,
) -> TemplateIdentity:
    implementation_id = resolved_template_id or resolve_template_id(
        template_id,
        input_path=input_path,
        sheet=sheet,
        fallback_distribution=fallback_distribution,
    )
    canonical_id = implementation_id if template_role(template_id) != "canonical" else template_id
    return TemplateIdentity(
        requested_template_id=template_id,
        canonical_id=canonical_id,
        role=template_role(template_id),
        lifecycle_policy=alias_lifecycle_policy(template_id),
        implementation_id=implementation_id,
    )


def template_lifecycle_inventory() -> tuple[TemplateLifecycleEntry, ...]:
    rows: list[TemplateLifecycleEntry] = []
    for canonical_id, aliases in _CANONICAL_TO_ALIASES.items():
        rows.append(
            TemplateLifecycleEntry(
                template_id=canonical_id,
                canonical_id=canonical_id,
                role="canonical",
                lifecycle_policy="canonical",
            )
        )
        for alias_id in aliases:
            rows.append(
                TemplateLifecycleEntry(
                    template_id=alias_id,
                    canonical_id=canonical_id,
                    role="alias",
                    lifecycle_policy=alias_lifecycle_policy(alias_id),
                )
            )
    rows.append(
        TemplateLifecycleEntry(
            template_id=_DISTRIBUTION_COMPARE_TEMPLATE_ID,
            canonical_id=_DISTRIBUTION_COMPARE_FALLBACK,
            role="family_alias",
            lifecycle_policy=alias_lifecycle_policy(_DISTRIBUTION_COMPARE_TEMPLATE_ID),
        )
    )
    return tuple(rows)


__all__ = [
    "TemplateIdentity",
    "TemplateLifecycleEntry",
    "alias_lifecycle_policy",
    "alias_recommendation_penalty",
    "alias_templates_for",
    "canonical_template_id",
    "compatibility_template_ids",
    "distribution_compare_fallback_template_id",
    "distribution_compare_variant_template_id",
    "is_supported_template_id",
    "resolve_distribution_compare_template_id",
    "resolve_template_id",
    "template_identity",
    "template_role",
    "template_family_ids",
    "template_lifecycle_inventory",
]
