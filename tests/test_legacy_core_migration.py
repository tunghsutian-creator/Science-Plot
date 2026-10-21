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

    # Synthetic decimals distinguish exact binary64 input parsing from the
    # shorter decimal coercion formerly used before the native round-trip audit.
    precise_source = _write_rows(
        tmp_path / "precise_curves.csv",
        [
            ["Time", "Stress", "Time", "Stress"],
            ["s", "Pa", "s", "Pa"],
            ["First", "First", "Second", "Second"],
            ["3", "0.12345678901234567890", "2", "1.0000000000000002"],
            ["1", "0.00000000000000012345678901234567", "", ""],
            ["1", "0.12345678901234567890", "", ""],
        ],
    )
    original_bytes = precise_source.read_bytes()
    precise = load_curve_table(precise_source)
    assert precise_source.read_bytes() == original_bytes
    assert precise[0].data["x"].tolist() == [3, 1, 1]
    assert [value.hex() for value in precise[0].data["y"]] == [
        "0x1.f9add3746f65fp-4",
        "0x1.1cac067affebcp-53",
        "0x1.f9add3746f65fp-4",
    ]
    assert precise[1].data["y"].tolist() == [float.fromhex("0x1.0000000000001p+0")]

    # Studio rereads the retained source independently before building native
    # series; both the structured and plain numeric routes must keep precision.
    from sciplot_core.studio_render.table_io import _coerced_numeric_frame, _read_table
    from sciplot_core.source_tables.parsing import coerce_numeric_series

    terminal = _coerced_numeric_frame(_read_table(precise_source))
    assert [value.hex() for value in terminal.iloc[:, 1]] == [
        "0x1.f9add3746f65fp-4", "0x1.1cac067affebcp-53", "0x1.f9add3746f65fp-4",
    ]
    plain = tmp_path / "numeric.csv"
    plain.write_text("x,y\n1,0.12345678901234567890\n2,0.00000000000000012345678901234567\n")
    assert [value.hex() for value in _coerced_numeric_frame(_read_table(plain))["y"]] == [
        "0x1.f9add3746f65fp-4", "0x1.1cac067affebcp-53",
    ]
    assert coerce_numeric_series(pd.Series(["1.0\x00", "1e2\x00x"])).tolist() == [1.0, 100.0]

    # An old document must exactly reproduce the old parser's values. A new
    # spec cannot downgrade its declared source encoding to accept those values.
    from copy import deepcopy
    from sciplot_core.source_tables.parsing import (
        DECIMAL_ROUND_TRIP_ENCODING, SOURCE_NUMERIC_ENCODING_KEY,
    )
    from sciplot_core.studio_render import derive_terminal_render_data_contract
    from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
    from sciplot_core.source_coverage.file_snapshots import _stable_file_snapshot

    request = {"template": "curve", "render_options": {"size": "60x55"}}
    def source_spec(*, legacy: bool) -> dict:
        units = derive_terminal_render_data_contract(
            request=request, terminal_sources=[precise_source],
            legacy_numeric_parser=legacy,
        )["units"]
        return {
            "source_request": request, "series": units,
            "axes": units[0]["axes"],
            "categorical": units[0]["categorical_contract"],
            "reference_guides": units[0]["reference_guides"],
            "direct_labels": units[0]["direct_labels"],
        }
    current = source_spec(legacy=False)
    historical = source_spec(legacy=True)
    assert current["series"][0]["y_values"][0].hex() == "0x1.f9add3746f65fp-4"
    assert historical["series"][0]["y_values"] != current["series"][0]["y_values"]
    snapshots = [_stable_file_snapshot(precise_source, label="generated source")]
    assert _verify_prepared_data(historical, snapshots)["status"] == "passed"
    assert _verify_prepared_data(current, snapshots)["status"] == "passed"
    versioned = {**current, SOURCE_NUMERIC_ENCODING_KEY: DECIMAL_ROUND_TRIP_ENCODING}
    assert _verify_prepared_data(versioned, snapshots)["status"] == "passed"
    with pytest.raises(ValueError, match="do not reproduce"):
        _verify_prepared_data(
            {**historical, SOURCE_NUMERIC_ENCODING_KEY: DECIMAL_ROUND_TRIP_ENCODING}, snapshots
        )
    with pytest.raises(ValueError, match="Unknown managed source numeric encoding"):
        _verify_prepared_data({**current, SOURCE_NUMERIC_ENCODING_KEY: "unknown"}, snapshots)
    for field, replacement in (("y_values", [1, 2, 3]), ("label", "Other sample")):
        altered = deepcopy(historical)
        altered["series"][0][field] = replacement
        with pytest.raises(ValueError, match="do not reproduce"):
            _verify_prepared_data(altered, snapshots)
    altered = deepcopy(historical)
    altered["axes"]["y"]["label"] = "Different units"
    with pytest.raises(ValueError, match="do not reproduce"):
        _verify_prepared_data(altered, snapshots)
    assert source_spec(legacy=False) == current
    assert precise_source.read_bytes() == original_bytes


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
        "palette_preset": "control_first_bright",
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
    assert contract.version == 4
    assert contract.templates["curve"].default_size == "60x55"
