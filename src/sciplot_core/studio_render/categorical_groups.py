"""Resolve grouped categorical identities, factor grids, and grouped series."""

from __future__ import annotations

import math
from typing import Any
import pandas as pd
from sciplot_core.policy import (
    CATEGORICAL_GROUPED_BAR_CENTER_OFFSET,
)

from sciplot_core.studio_render.models import (
    DEFAULT_PALETTE,
    StudioPreparationBlocked,
    StudioSeries,
    StudioSourceFrame,
)

from sciplot_core.studio_render.categorical_values import (
    _clean_studio_cell,
    _categorical_component_column,
)

from sciplot_core.studio_render.metric_columns import (
    _axis_label_from_column,
)

_GROUPED_BAR_LABEL_SEPARATOR = " || "


def _factor_pair_identity(label: str) -> tuple[str, str]:
    sample, separator, condition = str(label).partition(_GROUPED_BAR_LABEL_SEPARATOR)
    if not separator or not sample.strip() or not condition.strip():
        raise StudioPreparationBlocked(
            "invalid_factor_pair_identity",
            "Factor-paired series must preserve both sample and condition labels.",
        )
    return sample.strip(), condition.strip()


def _grouped_bar_identity(label: str) -> tuple[str, str]:
    try:
        return _factor_pair_identity(label)
    except StudioPreparationBlocked as exc:
        raise StudioPreparationBlocked(
            "invalid_grouped_bar_identity",
            "Grouped-bar series must preserve both sample and condition labels.",
        ) from exc


def _factorized_curve_grid(
    series: list[StudioSeries],
    *,
    template_id: str,
) -> dict[str, Any] | None:
    """Resolve a complete sample-by-condition curve grid from paired labels."""

    if template_id not in {"curve", "point_line"} or not series:
        return None
    paired = [_GROUPED_BAR_LABEL_SEPARATOR in str(item.label) for item in series]
    if not any(paired):
        return None
    if not all(paired):
        raise StudioPreparationBlocked(
            "mixed_factorized_curve_labels",
            "A factorized curve figure cannot mix paired and ordinary labels.",
        )
    formula_order: list[str] = []
    condition_order: list[str] = []
    combinations: dict[tuple[str, str], StudioSeries] = {}
    for item in series:
        formula, condition = _factor_pair_identity(item.label)
        if formula not in formula_order:
            formula_order.append(formula)
        if condition not in condition_order:
            condition_order.append(condition)
        key = (formula, condition)
        if key in combinations:
            raise StudioPreparationBlocked(
                "duplicate_factorized_curve_combination",
                f"Factorized curve pair `{formula}` / `{condition}` is duplicated.",
            )
        combinations[key] = item
    if len(condition_order) != 2:
        raise StudioPreparationBlocked(
            "unsupported_factorized_curve_condition_count",
            "A factorized curve legend requires exactly two ordered conditions.",
        )
    if not 2 <= len(formula_order) <= 4:
        raise StudioPreparationBlocked(
            "unsupported_factorized_curve_formula_count",
            "A factorized curve legend requires two to four formula groups.",
        )
    expected = {
        (formula, condition)
        for formula in formula_order
        for condition in condition_order
    }
    if set(combinations) != expected:
        missing = sorted(
            f"{formula} / {condition}"
            for formula, condition in expected - set(combinations)
        )
        raise StudioPreparationBlocked(
            "incomplete_factorized_curve_grid",
            "Every formula must contain both curve conditions; missing: "
            + ", ".join(missing),
        )
    return {
        "formula_order": formula_order,
        "condition_order": condition_order,
        "combinations": combinations,
    }


def _categorical_grouped_series_from_frames(
    frames: list[StudioSourceFrame],
) -> tuple[list[StudioSeries], dict[str, Any]] | None:
    """Read long-form Sample/Condition/value replicates for grouped bars."""

    records: list[tuple[str, str, float, tuple[str, str]]] = []
    value_labels: list[str] = []
    detected = False
    for source_frame in frames:
        frame = source_frame.frame
        sample_column = _categorical_component_column(
            frame,
            aliases={"sample", "samples", "specimen"},
        )
        condition_column = _categorical_component_column(
            frame,
            aliases={
                "condition",
                "conditions",
                "series",
                "weightreduction",
                "weightreductioncondition",
            },
        )
        if sample_column is None or condition_column is None:
            if detected and not frame.empty:
                raise StudioPreparationBlocked(
                    "mixed_categorical_grouped_shapes",
                    "Every source in one grouped bar must use the same "
                    "Sample/Condition/value long-form shape.",
                )
            continue
        detected = True
        numeric_candidates: list[Any] = []
        for column in frame.columns:
            if column in {sample_column, condition_column}:
                continue
            nonblank = frame[column].map(_clean_studio_cell).ne("")
            numeric = pd.to_numeric(frame[column], errors="coerce")
            if nonblank.any() and numeric[nonblank].notna().all():
                numeric_candidates.append(column)
        if len(numeric_candidates) != 1:
            raise StudioPreparationBlocked(
                "ambiguous_categorical_grouped_value",
                "Grouped-bar input needs exactly one numeric replicate column "
                "in addition to Sample and Condition.",
            )
        value_column = numeric_candidates[0]
        value_labels.append(_axis_label_from_column(frame, value_column))
        for row_index in frame.index:
            sample = _clean_studio_cell(frame.at[row_index, sample_column])
            condition = _clean_studio_cell(frame.at[row_index, condition_column])
            value_text = _clean_studio_cell(frame.at[row_index, value_column])
            if not sample and not condition and not value_text:
                continue
            if not sample or not condition or not value_text:
                raise StudioPreparationBlocked(
                    "incomplete_categorical_grouped_row",
                    "Every grouped-bar row needs Sample, Condition, and value.",
                )
            numeric_value = pd.to_numeric(
                pd.Series([frame.at[row_index, value_column]]),
                errors="coerce",
            ).iloc[0]
            if pd.isna(numeric_value) or not math.isfinite(float(numeric_value)):
                raise StudioPreparationBlocked(
                    "invalid_categorical_grouped_value",
                    f"Grouped-bar value is not finite at row {row_index + 2}.",
                )
            records.append(
                (
                    sample,
                    condition,
                    float(numeric_value),
                    (str(source_frame.path), source_frame.sha256),
                )
            )
    if not detected:
        return None
    if not records:
        raise StudioPreparationBlocked(
            "empty_categorical_grouped_data",
            "Grouped-bar input contains no plottable replicate values.",
        )
    distinct_value_labels = list(dict.fromkeys(value_labels))
    if len(distinct_value_labels) != 1:
        raise StudioPreparationBlocked(
            "mixed_categorical_grouped_metrics",
            "One grouped bar must use one value metric; found: "
            + ", ".join(distinct_value_labels),
        )

    sample_order: list[str] = []
    condition_order: list[str] = []
    grouped: dict[tuple[str, str], list[float]] = {}
    artifacts: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for sample, condition, value, artifact in records:
        if sample not in sample_order:
            sample_order.append(sample)
        if condition not in condition_order:
            condition_order.append(condition)
        key = (sample, condition)
        grouped.setdefault(key, []).append(value)
        artifacts.setdefault(key, set()).add(artifact)
    if len(condition_order) < 2:
        raise StudioPreparationBlocked(
            "insufficient_grouped_bar_conditions",
            "A grouped bar requires at least two conditions.",
        )
    if len(condition_order) > 3:
        raise StudioPreparationBlocked(
            "too_many_grouped_bar_conditions",
            "A grouped bar supports at most three adjacent conditions.",
        )
    expected_conditions = set(condition_order)
    for sample in sample_order:
        actual_conditions = {
            condition for item_sample, condition in grouped if item_sample == sample
        }
        if actual_conditions != expected_conditions:
            raise StudioPreparationBlocked(
                "incomplete_grouped_bar_sample",
                f"Sample `{sample}` does not contain every grouped-bar condition.",
            )

    condition_count = len(condition_order)
    if condition_count == 2:
        offsets = (
            -CATEGORICAL_GROUPED_BAR_CENTER_OFFSET,
            CATEGORICAL_GROUPED_BAR_CENTER_OFFSET,
        )
    else:
        offsets = tuple(
            CATEGORICAL_GROUPED_BAR_CENTER_OFFSET * (index - 1)
            for index in range(condition_count)
        )
    series: list[StudioSeries] = []
    for sample_index, sample in enumerate(sample_order, start=1):
        for condition_index, condition in enumerate(condition_order):
            key = (sample, condition)
            values = grouped[key]
            position = float(sample_index) + offsets[condition_index]
            series.append(
                StudioSeries(
                    label=(f"{sample}{_GROUPED_BAR_LABEL_SEPARATOR}{condition}"),
                    x_name=(f"category_grouped_x_{sample_index}_{condition_index + 1}"),
                    y_name=(f"category_grouped_y_{sample_index}_{condition_index + 1}"),
                    x_values=tuple(position for _ in values),
                    y_values=tuple(values),
                    color=DEFAULT_PALETTE[(sample_index - 1) % len(DEFAULT_PALETTE)],
                    presentation_kind="categorical_grouped_replicates",
                    category_position=position,
                    source_artifacts=tuple(sorted(artifacts[key])),
                )
            )
    return series, {
        "x_label": "Sample",
        "y_label": distinct_value_labels[0],
        "presentation_kind": "categorical_grouped_replicates",
        "category_labels": sample_order,
        "category_positions": [
            float(index) for index in range(1, len(sample_order) + 1)
        ],
        "condition_labels": condition_order,
        "raw_replicate_count": len(records),
    }
