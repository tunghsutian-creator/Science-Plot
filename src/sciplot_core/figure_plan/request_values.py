"""Normalize request values shared by impact plan and Studio preparation."""

from __future__ import annotations

from typing import Any


def impact_condition_label_mapping(request: dict[str, Any]) -> dict[str, str]:
    """Return the non-empty impact condition labels from either request layer."""

    render_options_value = request.get("render_options")
    if isinstance(render_options_value, dict):
        render_options = render_options_value
    else:
        render_options = {}
    value = request.get("condition_label_mapping")
    if not isinstance(value, dict):
        value = render_options.get("condition_label_mapping")
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip(): str(label).strip()
        for key, label in value.items()
        if str(key).strip() and str(label).strip()
    }


__all__ = ["impact_condition_label_mapping"]
