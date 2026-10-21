"""Bind prepared XY science to its verified original views, then display aliases."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sciplot_core.data_mapping.source_projection import verified_mapping_source_groups
from sciplot_core.mapping_contract.source_identity import scientific_group_binding
from sciplot_core.studio_render.models import StudioSeries


def bind_prepared_pairs(series: list[StudioSeries], request: dict[str, Any]) -> tuple[list[StudioSeries], dict[str, Any]]:
    """The existing adapter owns arrays; its sample slot carries logical view IDs.

    The sole original sample fact remains the verified proposal's sample_labels,
    projected here into source_binding.sample. It never comes from that slot.
    """
    groups = verified_mapping_source_groups(request, replicates=False)
    if not groups:
        return series, {}
    by_view = {group["source_id"]: group for group in groups}
    if len({item.label for item in series}) != len(series) or set(by_view) != {item.label for item in series}:
        raise ValueError("Prepared XY logical views differ from their confirmed original selectors.")
    result = []
    bindings = {}
    for item in series:
        group = by_view[item.label]
        current = replace(item, x_name=f"x_{group['source_id']}", y_name=f"y_{group['source_id']}")
        result.append(current)
        bindings[current.x_name] = scientific_group_binding({key: value for key, value in group.items()
            if key not in {"display_label", "path", "sha256", "rows"}})
    return result, bindings


def display_prepared_pairs(series: list[StudioSeries], request: dict[str, Any],
                           bindings: dict[str, Any] | None) -> list[StudioSeries]:
    groups = verified_mapping_source_groups(request, replicates=False)
    if not groups:
        return series
    aliases = {group["source_id"]: group["display_label"] for group in groups}
    if not bindings:
        raise ValueError("XY display aliases require the prepared scientific correspondence.")
    return [replace(item, label=aliases[bindings[item.x_name]["source_id"]]) for item in series]
