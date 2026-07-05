from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_SPLIT_MAX_SERIES_PER_PANEL = 4
DEFAULT_SPLIT_DELIVERY = "multi_figure_same_metric"
STACKED_TALL_FIGURE_HEIGHT_MM = 100.0
SUPPORTED_SPLIT_MODES = frozenset({"series_chunks"})
SUPPORTED_SPLIT_TEMPLATES = frozenset({"stacked_curve", "stacked_area", "segmented_stacked_curve"})
DEFAULT_STACK_SPLIT_POLICY = {
    "trigger": "still_unreadable_after_taller_preset",
    "mode": "series_chunks",
    "max_series_per_panel": DEFAULT_SPLIT_MAX_SERIES_PER_PANEL,
    "preserve_shared_x_axis": True,
    "delivery": DEFAULT_SPLIT_DELIVERY,
}


def normalize_split_policy(policy: object) -> dict[str, Any] | None:
    if policy is None or policy is False:
        return None
    if not isinstance(policy, Mapping):
        raise ValueError("`split_policy` must be an object when supplied.")
    if policy.get("enabled") is False:
        return None

    raw_mode = policy.get("mode") or "series_chunks"
    mode = str(raw_mode).strip()
    if mode not in SUPPORTED_SPLIT_MODES:
        known = ", ".join(sorted(SUPPORTED_SPLIT_MODES))
        raise ValueError(f"Unsupported split_policy.mode `{mode}`. Supported modes: {known}.")

    try:
        max_series = int(policy.get("max_series_per_panel") or DEFAULT_SPLIT_MAX_SERIES_PER_PANEL)
    except (TypeError, ValueError) as exc:
        raise ValueError("`split_policy.max_series_per_panel` must be an integer.") from exc
    if max_series < 1:
        raise ValueError("`split_policy.max_series_per_panel` must be at least 1.")

    delivery = str(policy.get("delivery") or DEFAULT_SPLIT_DELIVERY).strip() or DEFAULT_SPLIT_DELIVERY
    trigger = str(policy.get("trigger") or "explicit_request").strip() or "explicit_request"
    return {
        "trigger": trigger,
        "mode": mode,
        "max_series_per_panel": max_series,
        "preserve_shared_x_axis": bool(policy.get("preserve_shared_x_axis", True)),
        "delivery": delivery,
    }


def series_chunks(labels: Sequence[str], *, max_series_per_panel: int) -> list[list[str]]:
    cleaned = [str(label).strip() for label in labels if str(label).strip()]
    if not cleaned:
        return []
    return [
        cleaned[index : index + max_series_per_panel]
        for index in range(0, len(cleaned), max_series_per_panel)
    ]


def build_split_plan(
    labels: Sequence[str],
    *,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    max_series = int(policy["max_series_per_panel"])
    chunks = series_chunks(labels, max_series_per_panel=max_series)
    applied = len(chunks) > 1
    return {
        "applied": applied,
        "reason": "series_count_exceeds_policy" if applied else "series_count_within_policy",
        "policy": dict(policy),
        "series_count": sum(len(chunk) for chunk in chunks),
        "chunk_count": len(chunks),
        "chunks": [
            {
                "index": index + 1,
                "series_count": len(chunk),
                "series": list(chunk),
            }
            for index, chunk in enumerate(chunks)
        ],
    }


__all__ = [
    "DEFAULT_SPLIT_MAX_SERIES_PER_PANEL",
    "DEFAULT_STACK_SPLIT_POLICY",
    "STACKED_TALL_FIGURE_HEIGHT_MM",
    "SUPPORTED_SPLIT_MODES",
    "SUPPORTED_SPLIT_TEMPLATES",
    "build_split_plan",
    "normalize_split_policy",
    "series_chunks",
]
