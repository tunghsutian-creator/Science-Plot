"""Validate mechanical median/IQR and raw-point terminal geometry."""

from __future__ import annotations

import math
from typing import Any, NoReturn

from sciplot_core.mechanical_task_sources import MechanicalTaskSource
from sciplot_core.policy import (
    MIN_BOX_REPLICATES,
    categorical_fill_color,
    categorical_keyline_color,
    categorical_raw_point_half_spread,
    categorical_slot_width_mm,
    normalize_raw_point_jitter_fraction,
)
from sciplot_core.studio_render.categorical_values import (
    _deterministic_category_positions,
)


_TERMINAL_MISMATCH = "mechanical_terminal_evidence_mismatch"


def validate_mechanical_summary_spec(
    spec: dict[str, Any],
    *,
    series: list[dict[str, Any]],
    record: MechanicalTaskSource,
) -> None:
    """Require exact raw values, descriptive statistics, and category positions."""

    categorical = _object(spec.get("categorical"), label="categorical")
    if (
        categorical.get("kind") != "sciplot_categorical_replicate_contract"
        or categorical.get("presentation_kind") != "box_strip"
        or categorical.get("summary_statistic") != "median_iqr"
        or categorical.get("quartile_method")
        != "linear_interpolation_at_(n_minus_1)_times_p"
        or categorical.get("box_whisker_mode") != "1.5IQR"
        or categorical.get("mean_marker_visible") is not False
        or categorical.get("raw_values_preserved") is not True
        or categorical.get("minimum_box_replicates") != MIN_BOX_REPLICATES
        or categorical.get("raw_replicate_count")
        != sum(len(group.values) for group in record.groups)
    ):
        _fail("median/IQR/raw-point categorical contract")
    groups = categorical.get("groups")
    if not isinstance(groups, list) or len(groups) != len(record.groups):
        _fail("categorical group coverage")
    layout, fraction_options = _point_layout(spec, categorical=categorical)
    axes = _object(spec.get("axes"), label="axes")
    x_axis = _object(axes.get("x"), label="axes.x")
    expected_positions = [float(index) for index in range(1, len(record.groups) + 1)]
    if (
        x_axis.get("mode") != "labels"
        or x_axis.get("category_labels") != [group.sample for group in record.groups]
        or x_axis.get("category_positions") != expected_positions
    ):
        _fail("categorical axis identities")
    if categorical.get("native_veusz_boxplot") is not any(
        len(group.values) >= MIN_BOX_REPLICATES for group in record.groups
    ):
        _fail("boxplot eligibility")
    for index, (expected, group, item) in enumerate(
        zip(record.groups, groups, series, strict=True),
        start=1,
    ):
        if not isinstance(group, dict):
            _fail("categorical group record")
        statistics = _object(
            group.get("descriptive_statistics"),
            label="descriptive_statistics",
        )
        quartiles = _quartiles(expected.values)
        expected_status = (
            "boxplot"
            if len(expected.values) >= MIN_BOX_REPLICATES
            else "insufficient_replicates"
        )
        x_values = item.get("x_values")
        encoding = _object(item.get("encoding"), label="series encoding")
        marker = _object(encoding.get("marker"), label="encoding.marker")
        expected_x, expected_half_spread = _expected_positions(
            expected.sample,
            index=index,
            count=len(expected.values),
            layout=layout,
            options=fraction_options,
        )
        root_color = str(encoding["line"]["color"])
        if (
            group.get("label") != expected.sample
            or group.get("sample_label") != expected.sample
            or group.get("position") != float(index)
            or group.get("y_name") != f"category_y_{index}"
            or group.get("color") != root_color
            or group.get("fill_color") != categorical_fill_color(root_color)
            or group.get("keyline_color") != categorical_keyline_color(root_color)
            or group.get("replicate_count") != len(expected.values)
            or group.get("summary_status") != expected_status
            or group.get("boxplot_eligible")
            is not (len(expected.values) >= MIN_BOX_REPLICATES)
            or group.get("raw_points_visible") is not True
            or item.get("raw_points_visible") is not True
            or marker.get("fill_visible") is not True
            or item.get("name") != f"series_{index}"
            or item.get("x_name") != f"category_x_{index}"
            or item.get("y_name") != f"category_y_{index}"
            or item.get("category_position") != float(index)
            or not _same_values(group.get("raw_values"), expected.values)
            or not _same_values(item.get("y_values"), expected.values)
            or not _same_values(x_values, expected_x)
            or not all(
                _close(statistics.get(key), value) for key, value in quartiles.items()
            )
        ):
            _fail(f"raw values, positions, or statistics for {expected.sample!r}")
        band_fraction = 2.0 * expected_half_spread
        band_width = band_fraction * fraction_options["category_slot_width_mm"]
        box_ratio = (
            band_fraction / fraction_options["box_fill_fraction"]
            if fraction_options["box_fill_fraction"] > 0.0
            else 0.0
        )
        if (
            not _close(group.get("raw_point_half_spread"), expected_half_spread)
            or not _close(group.get("raw_point_band_fraction"), band_fraction)
            or not _close(group.get("raw_point_band_width_mm"), band_width)
            or not _close(group.get("raw_point_box_width_ratio"), box_ratio)
            or group.get("raw_points_within_box_width") is not True
            or group.get("raw_marker_glyphs_within_box_width") is not True
        ):
            _fail(f"raw-point geometry for {expected.sample!r}")


def _point_layout(
    spec: dict[str, Any],
    *,
    categorical: dict[str, Any],
) -> tuple[str, dict[str, float]]:
    render_options = _object(spec.get("render_options"), label="render_options")
    source_request = _object(spec.get("source_request"), label="source_request")
    explicit_keys = source_request.get("explicit_render_option_keys")
    if not isinstance(explicit_keys, list):
        _fail("terminal explicit render-option provenance")
    expected_layout = (
        "fixed" if "raw_point_jitter_fraction" in explicit_keys else "adaptive"
    )
    visual_style = _object(
        categorical.get("visual_style"),
        label="categorical.visual_style",
    )
    layout = str(render_options.get("_categorical_raw_point_layout") or "")
    if (
        layout != expected_layout
        or visual_style.get("raw_point_layout") != layout
        or visual_style.get("raw_point_position_policy")
        != "stable_hash_shuffled_even_slots"
    ):
        _fail("categorical raw-point layout policy")
    size_mm = spec.get("size_mm")
    if not isinstance(size_mm, list) or len(size_mm) != 2:
        _fail("figure size")
    category_count = len(categorical.get("groups", []))
    expected_slot_width = categorical_slot_width_mm(
        category_count=category_count,
        figure_width_mm=_number(size_mm[0], label="figure width"),
    )
    box_fill_fraction = _number(
        render_options.get("_categorical_box_fill_fraction"),
        label="categorical box fill fraction",
    )
    category_slot_width = _number(
        render_options.get("_categorical_slot_width_mm"),
        label="categorical slot width",
    )
    box_width = _number(
        render_options.get("_categorical_box_width_mm"),
        label="categorical box width",
    )
    if (
        not _close(category_slot_width, expected_slot_width)
        or not _close(box_width, box_fill_fraction * category_slot_width)
        or not _close(visual_style.get("box_fill_fraction"), box_fill_fraction)
        or not _close(visual_style.get("category_slot_width_mm"), category_slot_width)
        or not _close(visual_style.get("box_width_mm"), box_width)
        or visual_style.get("category_count") != category_count
    ):
        _fail("categorical box and slot geometry")
    return layout, {
        "box_fill_fraction": box_fill_fraction,
        "category_slot_width_mm": category_slot_width,
        "marker_size": _number(
            render_options.get("marker_size"),
            label="marker size",
        ),
        "raw_point_jitter_fraction": _number(
            render_options.get("raw_point_jitter_fraction"),
            label="raw-point jitter fraction",
        ),
    }


def _expected_positions(
    sample: str,
    *,
    index: int,
    count: int,
    layout: str,
    options: dict[str, float],
) -> tuple[tuple[float, ...], float]:
    fraction = (
        categorical_raw_point_half_spread(
            box_fill_fraction=options["box_fill_fraction"],
            replicate_count=count,
            category_slot_width_mm=options["category_slot_width_mm"],
            marker_size_pt=options["marker_size"],
        )
        if layout == "adaptive"
        else normalize_raw_point_jitter_fraction(options["raw_point_jitter_fraction"])
    )
    return (
        _deterministic_category_positions(
            float(index),
            count,
            fraction=fraction,
            seed_key=sample,
        ),
        fraction,
    )


def _quartiles(values: tuple[float, ...]) -> dict[str, float]:
    ordered = sorted(values)

    def quantile(p: float) -> float:
        position = (len(ordered) - 1) * p
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = position - lower
        return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction

    return {
        "minimum": ordered[0],
        "q1": quantile(0.25),
        "median": quantile(0.5),
        "q3": quantile(0.75),
        "maximum": ordered[-1],
    }


def _same_values(actual: object, expected: tuple[float, ...]) -> bool:
    return (
        isinstance(actual, list)
        and len(actual) == len(expected)
        and all(
            _close(value, reference)
            for value, reference in zip(actual, expected, strict=True)
        )
    )


def _number(value: object, *, label: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        _fail(label)
    result = float(value)
    if not math.isfinite(result):
        _fail(label)
    return result


def _close(value: object, expected: float) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isclose(float(value), expected, rel_tol=1e-12, abs_tol=1e-12)
    )


def _object(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(label)
    return value


def _fail(field: str) -> NoReturn:
    raise ValueError(
        f"{_TERMINAL_MISMATCH}: terminal {field} conflicts with the selected "
        "mechanical FigurePlan."
    )


__all__ = ["validate_mechanical_summary_spec"]
