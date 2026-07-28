from __future__ import annotations

import re


def is_full_figure_set_export_scope(value: object) -> bool:
    """Return whether *value* is a complete all-figures delivery contract."""

    if not isinstance(value, dict):
        return False
    primary_id = str(value.get("primary_figure_id") or "").strip()
    supported_ids = value.get("supported_figure_ids")
    planned_ids = value.get("planned_figure_ids")
    if (
        value.get("kind") != "sciplot_figure_set_export_scope"
        or value.get("status") != "full_figure_set_exact_current"
        or value.get("scope") != "full_figure_set_project_delivery"
        or value.get("secondary_receipt_scope") != "same_project_delivery"
        or value.get("full_figure_set_delivery_complete") is not True
        or not re.fullmatch(r"[a-z0-9][a-z0-9_]*", primary_id)
        or not isinstance(planned_ids, list)
        or primary_id not in planned_ids
        or value.get("blocker") not in {None, ""}
    ):
        return False
    normalized_lists: dict[str, list[str]] = {}
    for key in (
        "planned_figure_ids",
        "blocked_figure_ids",
        "available_figure_ids",
        "unavailable_figure_ids",
    ):
        values = value.get(key)
        if not isinstance(values, list) or not all(
            isinstance(item, str)
            and bool(item.strip())
            and re.fullmatch(r"[a-z0-9][a-z0-9_]*", item)
            for item in values
        ):
            return False
        if len(values) != len(set(values)):
            return False
        normalized_lists[key] = values
    planned_set = set(normalized_lists["planned_figure_ids"])
    blocked_set = set(normalized_lists["blocked_figure_ids"])
    available_set = set(normalized_lists["available_figure_ids"])
    unavailable_set = set(normalized_lists["unavailable_figure_ids"])
    return bool(
        primary_id in available_set
        and primary_id not in unavailable_set
        and available_set.isdisjoint(unavailable_set)
        and available_set | unavailable_set == planned_set
        and supported_ids == normalized_lists["available_figure_ids"]
        and not blocked_set
        and not unavailable_set
    )


def is_primary_figure_set_export_scope(value: object) -> bool:
    """Compatibility name for the complete figure-set contract."""

    return is_full_figure_set_export_scope(value)


__all__ = [
    "is_full_figure_set_export_scope",
    "is_primary_figure_set_export_scope",
]
