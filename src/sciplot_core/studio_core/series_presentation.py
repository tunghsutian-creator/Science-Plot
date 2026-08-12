"""Project a persisted source series inventory into its visible presentation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from sciplot_core.studio_core.axis_data_visibility import (
    axis_data_visibility_payload,
)
from sciplot_core.studio_core.series_encoding_contract import (
    series_encoding_contract_payload,
)


PRESENTATION_SERIES_SELECTION_KIND = "sciplot_presentation_series_selection"
PRESENTATION_SERIES_SELECTION_VERSION = 1


def series_selection_payload(
    source_order: Sequence[object],
    active_order: Sequence[object],
) -> dict[str, Any]:
    """Return one canonical visual selection over a complete source order."""

    source = _labels(source_order)
    active = _labels(active_order)
    if not source or len(source) != len(set(source)):
        raise ValueError("Presentation source order must contain unique labels.")
    if (
        not active
        or len(active) != len(set(active))
        or any(label not in source for label in active)
    ):
        raise ValueError(
            "Presentation active order must be a non-empty subset of source order."
        )
    return {
        "kind": PRESENTATION_SERIES_SELECTION_KIND,
        "version": PRESENTATION_SERIES_SELECTION_VERSION,
        "active_order": active,
    }


def spec_source_series_order(spec: Mapping[str, Any]) -> list[str]:
    """Return the complete source-bound series order declared by a spec."""

    series = spec.get("series")
    if not isinstance(series, list) or not series:
        raise ValueError("Veusz specification has no source series inventory.")
    labels = [
        str(item.get("label") or "").strip()
        for item in series
        if isinstance(item, Mapping)
    ]
    if len(labels) != len(series) or not all(labels) or len(labels) != len(set(labels)):
        raise ValueError("Veusz specification source series labels are invalid.")
    return labels


def selected_series_order(spec: Mapping[str, Any]) -> list[str]:
    """Return the persisted visible order, defaulting to the source order."""

    source = spec_source_series_order(spec)
    raw = spec.get("presentation_series_selection")
    if raw is None:
        return source
    if not isinstance(raw, Mapping):
        raise ValueError("Presentation series selection must be an object.")
    selection = series_selection_payload(
        source,
        raw.get("active_order") if isinstance(raw.get("active_order"), list) else [],
    )
    if (
        raw.get("kind") != PRESENTATION_SERIES_SELECTION_KIND
        or raw.get("version") != PRESENTATION_SERIES_SELECTION_VERSION
    ):
        raise ValueError(
            "Presentation series selection does not match the source inventory."
        )
    return list(selection["active_order"])


def persist_series_selection(
    payload: Mapping[str, Any],
    *,
    source_order: Sequence[object],
    active_order: Sequence[object],
) -> dict[str, Any]:
    """Copy a request, spec, or registry payload with one visual selection."""

    updated = deepcopy(dict(payload))
    selection = series_selection_payload(source_order, active_order)
    updated["presentation_series_selection"] = selection
    return updated


def effective_series_presentation(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact visible spec while retaining the persisted source spec."""

    effective = deepcopy(dict(spec))
    if "presentation_series_selection" not in effective:
        return effective
    source_order = spec_source_series_order(effective)
    active_order = selected_series_order(effective)
    if active_order == source_order:
        return effective

    series = effective["series"]
    by_label = {str(item["label"]): item for item in series}
    effective["series"] = [by_label[label] for label in active_order]

    categorical = effective.get("categorical")
    if isinstance(categorical, dict):
        _project_categorical_presentation(
            effective,
            categorical=categorical,
            source_order=source_order,
            active_order=active_order,
        )
    if "series_encoding_contract" in effective:
        effective["series_encoding_contract"] = series_encoding_contract_payload(
            effective["series"]
        )
    if "axis_data_visibility" in effective:
        effective["axis_data_visibility"] = axis_data_visibility_payload(
            series_specs=effective["series"],
            axes=effective.get("axes"),
            render_options=effective.get("render_options"),
        )
    return effective


def _project_categorical_presentation(
    spec: dict[str, Any],
    *,
    categorical: dict[str, Any],
    source_order: list[str],
    active_order: list[str],
) -> None:
    groups = categorical.get("groups")
    if not isinstance(groups, list):
        raise ValueError("Categorical presentation has no source group inventory.")
    by_label = {
        str(group.get("label") or "").strip(): group
        for group in groups
        if isinstance(group, dict)
    }
    if set(by_label) != set(source_order):
        raise ValueError(
            "Categorical source groups do not match the source series inventory."
        )

    box_index_by_label: dict[str, int] = {}
    box_index = 0
    for label in source_order:
        if by_label[label].get("boxplot_eligible") is True:
            box_index += 1
            box_index_by_label[label] = box_index

    projected_groups: list[dict[str, Any]] = []
    projected_series: list[dict[str, Any]] = []
    series_by_label = {str(item["label"]): item for item in spec["series"]}
    for position, label in enumerate(active_order, start=1):
        group = by_label[label]
        old_position = float(group["position"])
        new_position = float(position)
        projected_group = deepcopy(group)
        projected_group["position"] = new_position
        if label in box_index_by_label:
            suffix = box_index_by_label[label]
            projected_group["boxplot_name"] = f"categorical_boxplot_{suffix}"
            projected_group["median_name"] = f"categorical_box_median_{suffix}"
        projected_groups.append(projected_group)

        item = deepcopy(series_by_label[label])
        item["category_position"] = new_position
        x_values = item.get("x_values")
        if isinstance(x_values, list):
            delta = new_position - old_position
            item["x_values"] = [float(value) + delta for value in x_values]
        projected_series.append(item)

    spec["series"] = projected_series
    categorical["groups"] = projected_groups
    categorical["raw_replicate_count"] = sum(
        int(group.get("replicate_count") or 0) for group in projected_groups
    )
    insufficient = categorical.get("insufficient_replicate_groups")
    if isinstance(insufficient, list):
        active = set(active_order)
        categorical["insufficient_replicate_groups"] = [
            value
            for value in insufficient
            if str(value.get("label") if isinstance(value, Mapping) else value).strip()
            in active
        ]

    axes = spec.get("axes")
    x_axis = axes.get("x") if isinstance(axes, dict) else None
    if not isinstance(x_axis, dict):
        raise ValueError("Categorical presentation has no x-axis contract.")
    positions = [float(index) for index in range(1, len(active_order) + 1)]
    x_axis["category_labels"] = list(active_order)
    x_axis["category_positions"] = positions
    x_axis["min"] = 0.5
    x_axis["max"] = len(active_order) + 0.5
    x_axis["ticks"] = positions


def _labels(values: Sequence[object]) -> list[str]:
    return [str(value).strip() for value in values if str(value).strip()]


__all__ = [
    "PRESENTATION_SERIES_SELECTION_KIND",
    "PRESENTATION_SERIES_SELECTION_VERSION",
    "effective_series_presentation",
    "persist_series_selection",
    "selected_series_order",
    "series_selection_payload",
    "spec_source_series_order",
]
