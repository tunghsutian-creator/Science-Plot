"""Build stacked categorical component series from normalized source frames."""

from __future__ import annotations

import math
from typing import Any
import pandas as pd
from sciplot_core.policy import (
    CATEGORICAL_STACK_MAX_COMPONENTS,
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


def _categorical_component_series_from_frames(
    frames: list[StudioSourceFrame],
) -> tuple[list[StudioSeries], dict[str, Any]] | None:
    """Read an unambiguous long-form Sample/Component/value table.

    This shape represents additive components, not statistical replicates. It
    therefore remains separate from the existing three-label-row categorical
    replicate contract consumed by bar, box, and box+strip summaries.
    """

    records: list[tuple[str, str, float, tuple[str, str]]] = []
    value_labels: list[str] = []
    detected = False
    for source_frame in frames:
        frame = source_frame.frame
        sample_column = _categorical_component_column(
            frame,
            aliases={"sample", "samples", "specimen"},
        )
        component_column = _categorical_component_column(
            frame,
            aliases={"component", "components", "phase"},
        )
        if sample_column is None or component_column is None:
            if detected and not frame.empty:
                raise StudioPreparationBlocked(
                    "mixed_categorical_component_shapes",
                    "Every source in one stacked-component bar must use the same "
                    "Sample/Component/value long-form shape.",
                )
            continue
        detected = True
        numeric_candidates: list[Any] = []
        for column in frame.columns:
            if column in {sample_column, component_column}:
                continue
            nonblank = frame[column].map(_clean_studio_cell).ne("")
            numeric = pd.to_numeric(frame[column], errors="coerce")
            if nonblank.any() and numeric[nonblank].notna().all():
                numeric_candidates.append(column)
        if len(numeric_candidates) != 1:
            raise StudioPreparationBlocked(
                "ambiguous_categorical_component_value",
                "Stacked-component bar input needs exactly one numeric value "
                "column in addition to Sample and Component.",
            )
        value_column = numeric_candidates[0]
        value_labels.append(_axis_label_from_column(frame, value_column))
        for row_index in frame.index:
            sample = _clean_studio_cell(frame.at[row_index, sample_column])
            component = _clean_studio_cell(frame.at[row_index, component_column])
            value_text = _clean_studio_cell(frame.at[row_index, value_column])
            if not sample and not component and not value_text:
                continue
            if not sample or not component or not value_text:
                raise StudioPreparationBlocked(
                    "incomplete_categorical_component_row",
                    "Every stacked-component row needs Sample, Component, and value.",
                )
            numeric_value = pd.to_numeric(
                pd.Series([frame.at[row_index, value_column]]),
                errors="coerce",
            ).iloc[0]
            if pd.isna(numeric_value) or not math.isfinite(float(numeric_value)):
                raise StudioPreparationBlocked(
                    "invalid_categorical_component_value",
                    f"Stacked-component value is not finite at row {row_index + 2}.",
                )
            value = float(numeric_value)
            if value < 0.0:
                raise StudioPreparationBlocked(
                    "negative_categorical_component_value",
                    "Part-to-whole stacked bars require non-negative component values.",
                )
            records.append(
                (
                    sample,
                    component,
                    value,
                    (str(source_frame.path), source_frame.sha256),
                )
            )
    if not detected:
        return None
    if not records:
        raise StudioPreparationBlocked(
            "empty_categorical_component_data",
            "Stacked-component input contains no plottable values.",
        )
    distinct_value_labels = list(dict.fromkeys(value_labels))
    if len(distinct_value_labels) != 1:
        raise StudioPreparationBlocked(
            "mixed_categorical_component_metrics",
            "One stacked-component bar must use one value metric; found: "
            + ", ".join(distinct_value_labels),
        )

    sample_order: list[str] = []
    component_order: list[str] = []
    values_by_sample: dict[str, dict[str, float]] = {}
    artifacts_by_sample: dict[str, set[tuple[str, str]]] = {}
    for sample, component, value, artifact in records:
        if sample not in values_by_sample:
            sample_order.append(sample)
            values_by_sample[sample] = {}
            artifacts_by_sample[sample] = set()
        if component not in component_order:
            component_order.append(component)
        if component in values_by_sample[sample]:
            raise StudioPreparationBlocked(
                "duplicate_categorical_component",
                f"Sample `{sample}` repeats stacked component `{component}`.",
            )
        values_by_sample[sample][component] = value
        artifacts_by_sample[sample].add(artifact)
    if len(component_order) < 2:
        raise StudioPreparationBlocked(
            "insufficient_categorical_components",
            "A stacked-component bar requires at least two ordered components.",
        )
    if len(component_order) > CATEGORICAL_STACK_MAX_COMPONENTS:
        raise StudioPreparationBlocked(
            "too_many_categorical_components",
            "A single same-hue component stack supports at most "
            f"{CATEGORICAL_STACK_MAX_COMPONENTS} components.",
        )
    expected_components = set(component_order)
    for sample in sample_order:
        actual_components = set(values_by_sample[sample])
        if actual_components != expected_components:
            missing = [
                component
                for component in component_order
                if component not in actual_components
            ]
            extra = sorted(actual_components - expected_components)
            detail = ", ".join(
                [
                    *(f"missing {value}" for value in missing),
                    *(f"extra {value}" for value in extra),
                ]
            )
            raise StudioPreparationBlocked(
                "incomplete_categorical_component_stack",
                f"Sample `{sample}` does not match the shared component order"
                + (f": {detail}" if detail else "."),
            )

    series: list[StudioSeries] = []
    component_labels = tuple(component_order)
    for index, sample in enumerate(sample_order, start=1):
        series.append(
            StudioSeries(
                label=sample,
                x_name=f"category_component_x_{index}",
                y_name=f"category_component_y_{index}",
                x_values=tuple(float(index) for _ in component_order),
                y_values=tuple(
                    values_by_sample[sample][component] for component in component_order
                ),
                color=DEFAULT_PALETTE[(index - 1) % len(DEFAULT_PALETTE)],
                presentation_kind="categorical_components",
                category_position=float(index),
                component_labels=component_labels,
                source_artifacts=tuple(sorted(artifacts_by_sample[sample])),
            )
        )
    return series, {
        "x_label": "Sample",
        "y_label": distinct_value_labels[0],
        "presentation_kind": "categorical_components",
        "category_labels": sample_order,
        "category_positions": [
            float(index) for index in range(1, len(sample_order) + 1)
        ],
        "component_labels": list(component_order),
        "component_value_count": len(records),
    }
