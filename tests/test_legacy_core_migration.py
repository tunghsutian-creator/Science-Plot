from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.contract import CONTRACT_PATH, load_plot_contract
from sciplot_core.render.series_selection import (
    filter_curve_series,
    reorder_curve_series,
    unknown_series_order_labels,
)
from sciplot_core.source_inspection import inspect_input_file
from sciplot_core.source_tables import (
    load_curve_table,
    load_heatmap_table_from_frame,
    load_replicate_table_from_frame,
    normalize_unit,
)
from sciplot_core.studio_render.axis_limits import compute_axis_limits
from sciplot_core.style_contract import VEUSZ_IMPLEMENTED_TEMPLATE_IDS


@dataclass(frozen=True)
class _NamedCurve:
    sample: str


def _write_rows(path: Path, rows: list[list[object]]) -> Path:
    pd.DataFrame(rows).to_csv(path, index=False, header=False)
    return path


def test_curve_table_parser_preserves_labels_units_and_numeric_pairs(
    tmp_path: Path,
) -> None:
    source = _write_rows(
        tmp_path / "curves.csv",
        [
            ["Strain", "Stress", "Strain", "Stress"],
            ["%", "MPa", "%", "MPa"],
            ["Control", "Control", "Foam", "Foam"],
            [0, 0, 0, 0],
            [1, 10, 1, 7],
        ],
    )

    curves = load_curve_table(source)

    assert [curve.sample for curve in curves] == ["Control", "Foam"]
    assert curves[0].x_label == "Strain"
    assert curves[0].y_label == "σ"
    assert curves[0].x_unit == "%"
    assert curves[0].y_unit == "MPa"
    assert curves[1].data.to_dict(orient="list") == {
        "x": [0, 1],
        "y": [0, 7],
    }


def test_replicate_and_heatmap_parsers_keep_their_distinct_models() -> None:
    groups = load_replicate_table_from_frame(
        pd.DataFrame(
            [
                ["Strength", None],
                ["Control", "Foam"],
                ["MPa", "MPa"],
                [10, 7],
                [11, 8],
            ]
        )
    )
    heatmap = load_heatmap_table_from_frame(
        pd.DataFrame(
            [
                ["X", "Y", "Z"],
                ["Time", "Temperature", "Intensity"],
                ["s", "°C", "a.u."],
                [0, 20, 1],
                [1, 30, 2],
            ]
        )
    )

    assert [group.group for group in groups] == ["Control", "Foam"]
    assert groups[0].value_label == "Strength"
    assert heatmap.data.columns.tolist() == ["x", "y", "z"]
    assert heatmap.z_label == "Intensity"


@pytest.mark.parametrize(
    ("unit", "normalized"),
    [
        ("rad/s", r"rad$\cdot$s$^{-1}$"),
        ("cm^-1", r"cm$^{-1}$"),
        ("N m", "N·m"),
        ("[MPa]", "MPa"),
    ],
)
def test_source_unit_normalization_preserves_compatibility_forms(
    unit: str,
    normalized: str,
) -> None:
    assert normalize_unit(unit) == normalized


def test_source_inspection_recommends_only_implemented_veusz_templates(
    tmp_path: Path,
) -> None:
    source = _write_rows(
        tmp_path / "frequency.csv",
        [
            ["Angular Frequency", "Storage Modulus"],
            ["rad/s", "Pa"],
            ["Sample A", "Sample A"],
            [0.1, 10],
            [1.0, 100],
        ],
    )

    inspection = inspect_input_file(source)
    recommendation_ids = {
        recommendation.template_id for recommendation in inspection.recommendations
    }

    assert inspection.model == "frequency_metric_sheet"
    assert inspection.recommendations[0].template_id == "point_line"
    assert inspection.recommendations[0].default_render_overrides == {
        "size": "60x55",
        "xscale": "log",
        "yscale": "log",
        "reverse_x": False,
        "legend_position": "auto",
        "series_label_mode": "legend",
        "style_preset": "nature",
        "palette_preset": "jama_editorial",
        "visual_theme_id": "clean_light",
    }
    assert recommendation_ids <= VEUSZ_IMPLEMENTED_TEMPLATE_IDS


def test_series_selection_is_case_insensitive_and_stable() -> None:
    curves = [_NamedCurve("A"), _NamedCurve("B"), _NamedCurve("C")]

    assert filter_curve_series(curves, ["b", "A"]) == curves[:2]
    assert reorder_curve_series(curves, ["c", "a"]) == [
        curves[2],
        curves[0],
        curves[1],
    ]
    assert unknown_series_order_labels(["A", "B"], ["b", "missing"]) == ("missing",)


def test_axis_limit_policy_preserves_zero_based_bar_and_curve_padding() -> None:
    bar = compute_axis_limits([[2.0, 6.0]], kind="bar", axis_mode="auto")
    curve = compute_axis_limits(
        [[1.0, 10.0]],
        kind="line",
        x_values=[[0.0, 5.0]],
    )

    assert bar.ylim[0] == 0.0
    assert bar.y_tick_policy is not None
    assert bar.y_tick_policy.major_ticks[0] == 0.0
    assert curve.raw_xlim == (0.0, 5.0)
    assert curve.raw_ylim == (1.0, 10.0)
    assert curve.xlim[0] < curve.raw_xlim[0]
    assert curve.ylim[1] > curve.raw_ylim[1]


def test_plot_contract_is_loaded_from_the_first_party_policy_asset() -> None:
    contract = load_plot_contract()

    assert CONTRACT_PATH.name == "plot_contract.json"
    assert CONTRACT_PATH.parent.name == "policy"
    assert "_vendor" not in CONTRACT_PATH.parts
    assert contract.version == 3
    assert contract.templates["curve"].default_size == "60x55"
