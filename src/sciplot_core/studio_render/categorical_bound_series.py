"""Bind declared categorical coordinates to the existing Studio series kinds."""

from __future__ import annotations

from sciplot_core.studio_render.source_artifacts import literal_source_artifact

import math
from typing import Any

import pandas as pd

from sciplot_core.source_tables.parsing import coerce_frame_numeric_series
from sciplot_core.studio_render.categorical_groups import grouped_series_from_records
from sciplot_core.studio_render.categorical_values import _clean_studio_cell
from sciplot_core.studio_render.models import (
    CATEGORICAL_POINT_LINE_KIND, DEFAULT_PALETTE, StudioPreparationBlocked,
    StudioSeries, StudioSourceFrame,
)


class CategoricalMissingValues(StudioPreparationBlocked):
    def __init__(self, missing_cells: list[dict[str, Any]]) -> None:
        super().__init__("categorical_missing_values_confirmation_required", "Selected original values contain missing cells. Explicitly choose missing_values='exclude'; blanks are never zero-filled.")
        self.missing_cells = missing_cells


def _ordered(actual: list[str], selected: Any, *, name: str) -> list[str]:
    if selected is None:
        return actual
    if set(selected) != set(actual):
        raise StudioPreparationBlocked("invalid_categorical_order", f"{name} must order every selected original identity exactly once; use include_categories to exclude samples explicitly. Observed: {actual}.")
    return list(selected)


def bound_categorical_series(frames: list[StudioSourceFrame], *,
                             missing_values: str | None = None) -> tuple[list[StudioSeries], dict[str, Any]]:
    if len(frames) != 1:
        raise StudioPreparationBlocked("categorical_source_ambiguous", "An explicit categorical binding selects one original file and table.")
    source = frames[0]
    frame = source.frame
    binding = frame.attrs["categorical_binding"]
    sample_column = binding["sample_column"]
    condition_column = binding.get("condition_column")
    fields = binding["value_columns"]
    value_facts = frame.attrs["categorical_value_facts"]
    numeric = {field["column_index"]: coerce_frame_numeric_series(frame.iloc[:, field["column_index"]], frame) for field in fields}
    records: list[tuple[str, str, int, float, int]] = []
    samples: list[str] = []
    conditions: list[str] = []
    missing: list[dict[str, Any]] = []
    all_samples: list[str] = []
    include = binding.get("include_categories")
    for row in frame.index:
        sample = _clean_studio_cell(frame.at[row, sample_column])
        condition = (_clean_studio_cell(frame.at[row, condition_column])
                     if condition_column is not None else "")
        values = [_clean_studio_cell(frame.at[row, field["column_index"]]) for field in fields]
        if not sample and not condition and not any(values):
            continue
        if not sample or (condition_column is not None and not condition):
            raise StudioPreparationBlocked("incomplete_categorical_identity", f"Original row {row} needs a sample and, when selected, condition identity.")
        if "source_identity_version" not in binding and (" || " in sample or " || " in condition):
            raise StudioPreparationBlocked("invalid_categorical_identity", "Original sample and condition IDs cannot contain the reserved factor separator ' || '.")
        if sample not in all_samples:
            all_samples.append(sample)
        if include is not None and sample not in include:
            continue
        if sample not in samples:
            samples.append(sample)
        if condition not in conditions:
            conditions.append(condition)
        for value_index, field in enumerate(fields):
            column = field["column_index"]
            number: Any = numeric[column].at[row]
            if pd.isna(number):
                if values[value_index]:
                    raise StudioPreparationBlocked("invalid_categorical_value", f"Original row {row}, column {column} contains nonnumeric text: {values[value_index]!r}.")
                missing.append({"sample": sample, "condition": condition, "row_index": int(row), "column_index": column})
                continue
            if not math.isfinite(float(number)):
                raise StudioPreparationBlocked("invalid_categorical_value", f"Original row {row}, column {column} is not finite.")
            records.append((sample, condition, value_index, float(number), int(row)))
    if include is not None and not set(include) <= set(all_samples):
        raise StudioPreparationBlocked("unknown_categorical_selection", f"include_categories contains unknown original sample IDs; observed {all_samples}.")
    if not samples or not records:
        raise StudioPreparationBlocked("empty_categorical_data", "No measured values remain in the explicitly selected category region.")
    samples = _ordered(samples, binding.get("category_order"), name="category_order")
    conditions = _ordered(conditions, binding.get("condition_order"), name="condition_order")
    aliases = binding.get("category_aliases", {})
    if not set(aliases) <= set(samples) or len(set(aliases.get(sample, sample) for sample in samples)) != len(samples):
        raise StudioPreparationBlocked("invalid_categorical_aliases", "Display aliases must address included original sample IDs and remain unique.")
    if binding["mode"] == "given_values":
        if missing:
            raise StudioPreparationBlocked("incomplete_categorical_given_values", "Given-value point-lines require one provided value for every selected sample/condition/column. Select an explicit complete region; missing values are not invented or interpolated.")
        series = _given_series(records, source=source, samples=samples, conditions=conditions,
                               fields=fields, value_facts=value_facts, aliases=aliases)
        kind = CATEGORICAL_POINT_LINE_KIND
    else:
        if missing and missing_values != "exclude":
            raise CategoricalMissingValues(missing)
        groups = {(sample, condition): [value for row_sample, row_condition, _, value, _ in records
                  if row_sample == sample and row_condition == condition]
                  for sample in samples for condition in conditions}
        insufficient = [f"{sample} / {condition}" for (sample, condition), values in groups.items() if len(values) < 2]
        if insufficient:
            raise StudioPreparationBlocked("categorical_sample_sd_requires_replicates", "Sample SD requires at least two valid original replicates in every selected group: " + ", ".join(insufficient))
        artifact = literal_source_artifact(source.path, source.sha256)
        if condition_column is not None:
            ordered_records = [(sample, condition, value, artifact) for sample in samples for condition in conditions for value in groups[(sample, condition)]]
            series, _ = grouped_series_from_records(ordered_records, value_label=value_facts[0]["output_header"], allow_single_condition=True)
            kind = "categorical_grouped_replicates"
        else:
            series = [StudioSeries(sample, f"category_x_{index}", f"category_y_{index}",
                      tuple(float(index) for _ in groups[(sample, "")]), tuple(groups[(sample, "")]),
                      DEFAULT_PALETTE[(index - 1) % len(DEFAULT_PALETTE)],
                      presentation_kind="categorical_replicates", category_position=float(index),
                      source_artifacts=(artifact,)) for index, sample in enumerate(samples, start=1)]
            kind = "categorical_replicates"
    value_label = (value_facts[0]["output_header"] if len({fact["header"] for fact in value_facts}) == 1
                   else f"Value ({value_facts[0]['unit']})")
    info: dict[str, Any] = {"x_label": "Sample", "y_label": value_label,
        "presentation_kind": kind, "category_labels": [aliases.get(sample, sample) for sample in samples],
        "category_positions": [float(index) for index in range(1, len(samples) + 1)],
        "condition_labels": conditions if condition_column is not None else [],
        "raw_replicate_count": len(records), "source_category_ids": samples,
        "categorical_missing_cells": missing,
        "categorical_source_rows": [{"sample": sample, "condition": condition,
            "column_index": fields[column]["column_index"], "row_index": row}
            for sample, condition, column, _, row in records]}
    if binding.get("source_identity_version") == 1:
        from sciplot_core.studio_render.categorical_source_identity import bind_categorical_identities

        series, info["source_bindings"] = bind_categorical_identities(series, source=source,
            samples=samples, conditions=conditions, binding=binding)
    return series, info


def _given_series(records: list[tuple[str, str, int, float, int]], *, source: StudioSourceFrame,
                  samples: list[str], conditions: list[str], fields: list[dict[str, Any]],
                  value_facts: list[dict[str, Any]], aliases: dict[str, str]) -> list[StudioSeries]:
    grouped: dict[tuple[str, str, int], list[float]] = {}
    for sample, condition, column, value, _ in records:
        grouped.setdefault((sample, condition, column), []).append(value)
    expected = {(sample, condition, column) for sample in samples for condition in conditions for column in range(len(fields))}
    if set(grouped) != expected or any(len(values) != 1 for values in grouped.values()):
        raise StudioPreparationBlocked("categorical_given_values_ambiguous", "Given-value mode requires exactly one original value per sample/condition/selected column; choose repeat statistics explicitly for repeated measurements.")
    result: list[StudioSeries] = []
    for condition in conditions:
        for column, field in enumerate(fields):
            value_label = field.get("label", value_facts[column]["header"])
            label = condition if len(fields) == 1 and condition else (f"{value_label} ({condition})" if condition else value_label)
            index = len(result) + 1
            result.append(StudioSeries(label, f"category_x_{index}", f"category_y_{index}",
                tuple(float(index) for index in range(1, len(samples) + 1)),
                tuple(grouped[(sample, condition, column)][0] for sample in samples),
                DEFAULT_PALETTE[(index - 1) % len(DEFAULT_PALETTE)],
                presentation_kind=CATEGORICAL_POINT_LINE_KIND,
                component_labels=tuple(aliases.get(sample, sample) for sample in samples),
                source_artifacts=(literal_source_artifact(source.path, source.sha256),)))
    return result


def categorical_style_request(request: dict[str, Any], *, series: list[StudioSeries],
                              axis_info: dict[str, Any]) -> dict[str, Any]:
    """Expand declared condition styles over existing grouped series identities."""
    styles = request["categorical_binding"].get("series_styles", [])
    if axis_info.get("source_bindings"):
        from sciplot_core.studio_render.categorical_source_identity import freeze_categorical_styles

        frozen = freeze_categorical_styles(request["categorical_binding"], series=series,
            identities=axis_info["source_bindings"], allow_labels=False)
        return {**request, "render_options": {**request.get("render_options", {}), "series_styles": frozen.get("series_styles", [])}}
    labels = {item.label for item in series}
    grouped = axis_info["presentation_kind"] == "categorical_grouped_replicates"
    expanded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for style in styles:
        target = style["label"]
        targets = ([item.label for item in series if item.label.partition(" || ")[2] == target]
                   if grouped and target in axis_info["condition_labels"] else [target])
        if not targets or any(label not in labels for label in targets):
            raise StudioPreparationBlocked("unknown_categorical_style", f"Style label {target!r} does not identify a plotted series or grouped condition.")
        if seen.intersection(targets):
            raise StudioPreparationBlocked("duplicate_categorical_style", "A series cannot receive conflicting duplicate style declarations.")
        seen.update(targets)
        expanded.extend({**style, "label": label} for label in targets)
    return {**request, "render_options": {**request.get("render_options", {}), "series_styles": expanded}}
