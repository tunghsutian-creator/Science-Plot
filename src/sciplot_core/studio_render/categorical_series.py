"""Build and reindex categorical replicate series."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any
import pandas as pd
from sciplot_core.policy import (
    CATEGORICAL_BOX_FILL_FRACTION,
    DEFAULT_RAW_POINT_JITTER_FRACTION,
    categorical_raw_point_half_spread,
    normalize_raw_point_jitter_fraction,
)

from sciplot_core.studio_render.models import (
    DEFAULT_PALETTE,
    StudioPreparationBlocked,
    StudioSeries,
    StudioSourceFrame,
)

from sciplot_core.studio_render.categorical_values import (
    _clean_studio_cell,
    _categorical_metric_label,
    _categorical_axis_label,
    _deterministic_category_positions,
)

from sciplot_core.studio_render.categorical_components import (
    _categorical_component_series_from_frames,
)

from sciplot_core.studio_render.categorical_groups import (
    _categorical_grouped_series_from_frames,
)


def _categorical_series_from_frames(
    frames: list[StudioSourceFrame],
    *,
    render_options: dict[str, Any],
) -> tuple[list[StudioSeries], dict[str, Any]]:
    grouped_bars = _categorical_grouped_series_from_frames(frames)
    if grouped_bars is not None:
        return grouped_bars
    stacked_components = _categorical_component_series_from_frames(frames)
    if stacked_components is not None:
        return stacked_components
    grouped: dict[str, list[float]] = {}
    grouped_artifacts: dict[str, set[tuple[str, str]]] = {}
    metric_labels: list[str] = []
    units: list[str] = []
    for source_frame in frames:
        source_label = source_frame.label
        frame = source_frame.frame
        if frame.shape[0] < 3:
            continue
        for column in frame.columns:
            values = pd.to_numeric(frame[column].iloc[2:], errors="coerce").dropna()
            if values.empty:
                continue
            sample = (
                _clean_studio_cell(frame[column].iloc[1]) or source_label or str(column)
            )
            grouped.setdefault(sample, []).extend(
                float(value) for value in values.tolist()
            )
            grouped_artifacts.setdefault(sample, set()).add(
                (str(source_frame.path), source_frame.sha256)
            )
            metric = _categorical_metric_label(column)
            if metric:
                metric_labels.append(metric)
            unit = _clean_studio_cell(frame[column].iloc[0])
            if unit:
                units.append(unit)
    if not grouped:
        return [], {"x_label": "Sample", "y_label": "Value"}
    distinct_metrics = list(dict.fromkeys(metric_labels))
    distinct_units = list(dict.fromkeys(units))
    normalized_metrics = {metric.casefold() for metric in distinct_metrics}
    normalized_units = {
        re.sub(r"\s+", " ", unit).strip().casefold() for unit in distinct_units
    }
    if len(normalized_metrics) > 1:
        raise StudioPreparationBlocked(
            "mixed_categorical_metrics",
            "Categorical replicate rendering requires one metric; found: "
            + ", ".join(distinct_metrics),
        )
    if len(normalized_units) > 1:
        raise StudioPreparationBlocked(
            "mixed_categorical_units",
            "Categorical replicate rendering requires one unit; found: "
            + ", ".join(distinct_units),
        )
    metric = distinct_metrics[0] if distinct_metrics else "Value"
    unit = distinct_units[0] if distinct_units else ""
    jitter = normalize_raw_point_jitter_fraction(
        render_options.get(
            "raw_point_jitter_fraction", DEFAULT_RAW_POINT_JITTER_FRACTION
        )
    )
    series: list[StudioSeries] = []
    for index, (sample, values) in enumerate(grouped.items(), start=1):
        series.append(
            StudioSeries(
                label=sample,
                x_name=f"category_x_{index}",
                y_name=f"category_y_{index}",
                x_values=_deterministic_category_positions(
                    float(index),
                    len(values),
                    fraction=jitter,
                    seed_key=sample,
                ),
                y_values=tuple(values),
                color=DEFAULT_PALETTE[(index - 1) % len(DEFAULT_PALETTE)],
                presentation_kind="categorical_replicates",
                category_position=float(index),
                source_artifacts=tuple(sorted(grouped_artifacts[sample])),
            )
        )
    return series, {
        "x_label": "Sample",
        "y_label": _categorical_axis_label(metric, unit),
        "presentation_kind": "categorical_replicates",
        "category_labels": list(grouped),
        "category_positions": [float(index) for index in range(1, len(grouped) + 1)],
        "raw_replicate_count": sum(len(values) for values in grouped.values()),
    }


def _reindex_categorical_series(
    series: list[StudioSeries],
    *,
    render_options: dict[str, Any],
) -> list[StudioSeries]:
    adaptive = render_options.get("_categorical_raw_point_layout") == "adaptive"
    box_fraction = float(
        render_options.get(
            "_categorical_box_fill_fraction", CATEGORICAL_BOX_FILL_FRACTION
        )
    )
    category_slot_width_mm = float(
        render_options.get("_categorical_slot_width_mm") or 0.0
    )
    return [
        replace(
            item,
            x_values=_deterministic_category_positions(
                float(index),
                len(item.y_values),
                fraction=(
                    categorical_raw_point_half_spread(
                        box_fill_fraction=box_fraction,
                        replicate_count=len(item.y_values),
                        category_slot_width_mm=category_slot_width_mm,
                    )
                    if adaptive
                    else normalize_raw_point_jitter_fraction(
                        render_options.get(
                            "raw_point_jitter_fraction",
                            DEFAULT_RAW_POINT_JITTER_FRACTION,
                        )
                    )
                ),
                seed_key=item.label,
            ),
            category_position=float(index),
        )
        for index, item in enumerate(series, start=1)
    ]
