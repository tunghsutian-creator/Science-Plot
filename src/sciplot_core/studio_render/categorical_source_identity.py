"""Project explicit categorical column/factor facts into stable series bindings."""

from dataclasses import replace
from typing import Any

from sciplot_core.mapping_contract.source_identity import scientific_group_binding, source_view_id
from sciplot_core.studio_render.models import StudioSeries, StudioSourceFrame


def bind_categorical_identities(series: list[StudioSeries], *, source: StudioSourceFrame,
                                samples: list[str], conditions: list[str],
                                binding: dict[str, Any]) -> tuple[list[StudioSeries], dict[str, Any]]:
    """Source rows establish factors; labels are only a late display projection."""
    aliases = binding.get("category_aliases", {})
    fields = binding["value_columns"]
    selection = binding["table_selection"]
    sample_column, condition_column = binding["sample_column"], binding.get("condition_column")
    groups = []
    if binding["mode"] == "given_values":
        for condition in conditions:
            for field in fields:
                group_id = source_view_id(binding["source_namespace"], selection,
                    [sample_column, *([condition_column] if condition_column is not None else []), field["column_index"]],
                    selector={"condition": condition if condition_column is not None else None})
                groups.append({"version": 2, "source_id": group_id, "source_namespace": binding["source_namespace"], "categories": list(samples),
                               "condition": condition if condition_column is not None else None,
                               "value_column": field["column_index"]})
    else:
        for sample in samples:
            for condition in conditions:
                group_id = source_view_id(binding["source_namespace"], selection,
                    [sample_column, *([condition_column] if condition_column is not None else []), fields[0]["column_index"]],
                    selector={"sample": sample, "condition": condition if condition_column is not None else None})
                groups.append({"version": 1, "source_id": group_id, "source_namespace": binding["source_namespace"], "sample": sample,
                               "category": sample, "condition": condition if condition_column is not None else None})
    result, identities = [], {}
    for item, group in zip(series, groups, strict=True):
        label = item.label
        if group["version"] == 1:
            label = aliases.get(group["sample"], group["sample"])
            if group["condition"] is not None:
                label = f"{label} || {group['condition']}"
        current = replace(item, label=label, x_name=f"x_{group['source_id']}", y_name=f"y_{group['source_id']}")
        result.append(current)
        identities[current.x_name] = scientific_group_binding(group)
    return result, identities


def freeze_categorical_styles(binding: dict[str, Any], *, series: list[StudioSeries],
                              identities: dict[str, Any], allow_labels: bool) -> dict[str, Any]:
    """Resolve creation selectors once; saved styles retain only ID authority."""
    by_id = {identities[item.x_name]["source_id"]: item for item in series}
    result = []
    seen: set[str] = set()
    for style in binding.get("series_styles", []):
        if "series_id" in style:
            selected = [by_id[style["series_id"]]] if style["series_id"] in by_id else []
        elif allow_labels:
            conditions = [item for item in series if identities[item.x_name]["condition"] == style["label"]]
            labels = [item for item in series if item.label == style["label"]]
            if len(labels) > 1 or (conditions and labels and set(item.x_name for item in labels) != set(item.x_name for item in conditions)):
                raise ValueError("A creation style selector is ambiguous; use an advertised exact series_id.")
            selected = conditions or labels
        else:
            raise ValueError("Saved current categorical styles require their frozen series_id.")
        if not selected:
            raise ValueError("A categorical style selector does not identify a retained source group.")
        for item in selected:
            group_id = identities[item.x_name]["source_id"]
            if group_id in seen:
                raise ValueError("A retained source group has duplicate categorical style declarations.")
            seen.add(group_id)
            result.append({**style, "label": item.label, "series_id": group_id})
    return {**binding, **({"series_styles": result} if "series_styles" in binding else {})}
