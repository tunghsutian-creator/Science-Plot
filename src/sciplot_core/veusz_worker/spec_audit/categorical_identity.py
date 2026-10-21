"""Audit categorical display using saved original facts or historical labels."""

from typing import Any

from sciplot_core.mapping_contract.categorical_identity import validate_categorical_correspondence
from sciplot_core.studio_render.categorical_values import _category_axis_label


def categorical_series_labels(spec: dict[str, Any], groups: dict[str, Any],
                              series_by_y: dict[str, Any], kind: str) -> list[str]:
    validate_categorical_correspondence(spec)
    labels = []
    structured = any(item.get("source_binding") for item in series_by_y.values())
    for y_name, group in groups.items():
        item = series_by_y.get(y_name)
        if item is None or str(group.get("label") or "") != str(item.get("label") or ""):
            raise ValueError("Categorical group labels do not match their rendered series identities.")
        labels.append(str(group["source_binding"]["category"] if structured else
                          group.get("sample_label") if kind == "grouped_bar_error" else group.get("label") or ""))
    if kind == "grouped_bar_error" or structured:
        labels = list(dict.fromkeys(labels))
    request = spec.get("source_request", {})
    if isinstance(request, dict) and "categorical_binding" in request:
        from sciplot_core.mapping_contract.categorical import validate_categorical_context

        validate_categorical_context(request)
        aliases = request["categorical_binding"].get("category_aliases", {})
        labels = [aliases.get(label, label) for label in labels]
    return [_category_axis_label(label) for label in labels] if structured else labels
