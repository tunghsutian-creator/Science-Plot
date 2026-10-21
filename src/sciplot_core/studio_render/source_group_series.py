"""Construct series from independent, verified original replicate groups."""

from __future__ import annotations

from typing import Any

import pandas as pd

from sciplot_core.mapping_contract.source_identity import scientific_group_binding
from sciplot_core.studio_render.models import DEFAULT_PALETTE, StudioSeries, StudioSourceFrame
from sciplot_core.studio_render.categorical_groups import source_group_width_fraction


def source_group_key_visible(series: list[StudioSeries], bindings: dict[str, Any] | None,
                              options: dict[str, Any], *, request: dict[str, Any]) -> bool:
    if not bindings or any(item.presentation_kind != "categorical_replicates" for item in series):
        return False
    from sciplot_core.studio_render.series_option_context import request_option_authority

    _, explicit = request_option_authority(request, "legend_position")
    hidden = str(options.get("legend_position") or "auto").casefold() in {"none", "hide", "hidden", "off"}
    return source_group_width_fraction(series, bindings) is not None and not (explicit and hidden)


def source_group_series(frames: list[StudioSourceFrame]) -> tuple[list[StudioSeries], dict[str, Any]]:
    series: list[StudioSeries] = []
    bindings = {}
    categories: list[str] = []
    for frame in frames:
        binding = frame.frame.attrs["sciplot_source_group"]
        if list(frame.frame.columns) != ["Impact strength"]:
            raise ValueError("A raw source group must retain its declared original metric.")
        category = binding["category"]
        if category not in categories:
            categories.append(category)
        group_id = binding["source_id"]
        values = tuple(float(value) for value in frame.frame.iloc[:, 0] if pd.notna(value))
        item = StudioSeries(label=binding["display_label"], x_name=f"x_{group_id}", y_name=f"y_{group_id}",
            x_values=tuple(float(categories.index(category) + 1) for _ in values), y_values=values,
            color=DEFAULT_PALETTE[len(series) % len(DEFAULT_PALETTE)], presentation_kind="categorical_replicates",
            category_position=float(categories.index(category) + 1),
            source_artifacts=((str(frame.path), frame.sha256),))
        series.append(item)
        bindings[item.x_name] = scientific_group_binding({key: value for key, value in binding.items()
                                 if key not in {"path", "sha256", "rows", "display_label"}})
    return series, {"x_label": "Sample", "y_label": "Impact strength (kJ/m^{2})",
                    "presentation_kind": "categorical_replicates", "source_bindings": bindings,
                    "category_labels": categories,
                    "category_positions": [float(index + 1) for index in range(len(categories))],
                    "raw_replicate_count": sum(len(item.y_values) for item in series)}
