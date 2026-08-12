from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import pytest

from sciplot_core._paths import resolve_fixture_path
from sciplot_core.materials_rules import get_rule
from sciplot_core.materials_rules.models import AxisSpec
from sciplot_core.semantic_sources.registered_paired_curve_transform import (
    resolve_registered_paired_curve_transform,
)
from sciplot_core.semantic_sources.table_scanning import (
    _scan_curve_series_source,
)
from sciplot_core.semantic_sources.tga_transform import resolve_tga_transform


RULE_ID = "tga_curve"


def _fixture() -> Path:
    source = resolve_fixture_path(str(get_rule(RULE_ID).fixture_path or ""))
    assert source.is_file()
    return source


def _fixture_rows() -> list[list[str]]:
    with _fixture().open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def test_real_tga_transform_binds_source_columns_units_sample_and_points() -> None:
    rows = _fixture_rows()
    source_headers, source_units, source_samples = rows[:3]
    source_points = tuple(
        (float(row[0]), float(row[1])) for row in rows[3:] if row[0] and row[1]
    )

    resolved = resolve_tga_transform(_fixture())
    contract = resolved.contract.to_payload()

    assert len(resolved.series) == 1
    series = resolved.series[0]
    assert resolved.selected_sources == (_fixture().resolve(),)
    assert series.sample == source_samples[0]
    assert (series.x_label, series.y_label) == tuple(source_headers)
    assert (series.x_unit, series.y_unit) == ("C", "%")
    assert series.points == source_points
    assert contract["selected_sources"] == [str(_fixture().resolve())]
    assert contract["source_columns"] == [
        {
            "sample": source_samples[0],
            "sources": [str(_fixture().resolve())],
            "source_table": _fixture().stem,
            "header_row_index": 0,
            "x": {
                "role": "coordinate",
                "header": source_headers[0],
                "unit": source_units[0],
                "column_index_zero_based": 0,
                "unit_detection": {
                    "method": "detected_from_adjacent_unit_row",
                    "row_index_zero_based": 1,
                    "value": source_units[0],
                },
            },
            "response": {
                "role": "response",
                "header": source_headers[1],
                "unit": source_units[1],
                "column_index_zero_based": 1,
                "unit_detection": {
                    "method": "detected_from_adjacent_unit_row",
                    "row_index_zero_based": 1,
                    "value": source_units[1],
                },
            },
        }
    ]
    assert contract["x_coordinate_policy"] == {
        "operation": "preserve_source_coordinate_and_order",
        "metric": "temperature",
        "unit": "C",
        "source_row_order_preserved": True,
        "sorting_applied": False,
        "interpolation_applied": False,
    }
    assert contract["output"]["x_metric"] == "temperature"
    assert contract["output"]["y_metric"] == "mass"
    assert contract["output"]["series_order"] == [source_samples[0]]
    assert contract["output"]["series"] == [
        {
            "sample": source_samples[0],
            "candidate_row_count": len(source_points),
            "point_count": len(source_points),
            "retained_point_count": len(source_points),
            "excluded_point_count": 0,
            "excluded_by_reason": {
                "empty_pair": 0,
                "partial_or_nonnumeric": 0,
                "nonfinite": 0,
            },
            "first_point": list(source_points[0]),
            "last_point": list(source_points[-1]),
        }
    ]


def test_registered_paired_curve_detects_xrd_units_and_preserves_each_grid() -> None:
    rule = get_rule("xrd_pattern")
    source = resolve_fixture_path(str(rule.fixture_path or ""))
    with source.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    headers, units, samples = rows[:3]
    column_pairs = tuple(range(0, len(headers), 2))
    expected_points = tuple(
        tuple(
            (float(row[x_index]), float(row[x_index + 1]))
            for row in rows[3:]
            if row[x_index] and row[x_index + 1]
        )
        for x_index in column_pairs
    )
    expected_x_grids = tuple(
        tuple(x_value for x_value, _y_value in points)
        for points in expected_points
    )
    assert len(expected_points) == 2
    assert expected_x_grids[0] != expected_x_grids[1]

    resolved = resolve_registered_paired_curve_transform(source, rule=rule)

    assert len(resolved.series) == len(expected_points)
    for series, x_index, points in zip(
        resolved.series,
        column_pairs,
        expected_points,
        strict=True,
    ):
        diagnostics = dict(series.diagnostics or {})
        assert series.sample == samples[x_index]
        assert series.points == points
        assert diagnostics["source_x_header"] == headers[x_index]
        assert diagnostics["source_y_header"] == headers[x_index + 1]
        assert diagnostics["source_x_unit_detection"] == (
            "detected_from_adjacent_unit_row"
        )
        assert diagnostics["source_y_unit_detection"] == (
            "detected_from_adjacent_unit_row"
        )
        assert diagnostics["source_x_unit_detection_value"] == units[x_index]
        assert diagnostics["source_y_unit_detection_value"] == units[x_index + 1]


@pytest.mark.parametrize(
    ("unit_row", "message"),
    [
        (None, "Missing explicit tga_curve temperature unit"),
        (("K", "%"), "Unsupported tga_curve x unit"),
    ],
)
def test_tga_transform_rejects_missing_or_kelvin_units(
    tmp_path: Path,
    unit_row: tuple[str, str] | None,
    message: str,
) -> None:
    source = tmp_path / "tga.csv"
    sample = source.stem
    rows = [["Temperature", "Mass"]]
    if unit_row is not None:
        rows.append(list(unit_row))
    rows.extend([[sample, sample], ["25", "100"], ["50", "95"]])
    source.write_text(
        "\n".join(",".join(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        resolve_tga_transform(source)


def test_tga_scan_accounts_for_partial_and_nonfinite_rows(
    tmp_path: Path,
) -> None:
    source = tmp_path / "row_evidence.csv"
    sample = source.stem
    source.write_text(
        "Temperature,Mass\n"
        "C,%\n"
        f"{sample},{sample}\n"
        "25,100\n"
        ",90\n"
        "bad,80\n"
        "40,70\n"
        "50,Inf\n",
        encoding="utf-8",
    )

    series = _scan_curve_series_source(
        source,
        x_aliases=("temperature", "temp"),
        y_aliases=("weight", "mass"),
        x_label="Temperature",
        y_label="Mass",
        default_x_unit="C",
        default_y_unit="%",
        sample_prefix=source.stem,
    )[0]
    diagnostics = dict(series.diagnostics or {})

    assert diagnostics["candidate_row_count"] == 5
    assert diagnostics["retained_point_count"] == 2
    assert diagnostics["excluded_empty_pair_count"] == 0
    assert diagnostics["excluded_partial_or_nonnumeric_pair_count"] == 2
    assert diagnostics["excluded_nonfinite_pair_count"] == 1
    with pytest.raises(ValueError, match="nonfinite"):
        resolve_tga_transform(source)


def test_tga_scan_distinguishes_sample_row_from_first_numeric_point(
    tmp_path: Path,
) -> None:
    source = tmp_path / "without_sample.csv"
    numeric_rows = [["25", "100"], ["50", "95"]]
    source.write_text(
        "\n".join(
            ",".join(row)
            for row in [["Temperature", "Mass"], ["C", "%"], *numeric_rows]
        )
        + "\n",
        encoding="utf-8",
    )

    fallback_series = resolve_tga_transform(source).series[0]
    fallback_diagnostics = dict(fallback_series.diagnostics or {})
    assert fallback_series.sample == source.stem
    assert fallback_series.points == tuple(
        (float(row[0]), float(row[1])) for row in numeric_rows
    )
    assert fallback_diagnostics["source_sample_detection"] == (
        "fallback_from_source_table"
    )
    assert fallback_diagnostics["source_sample_row_index"] is None
    assert fallback_diagnostics["source_sample_value"] == source.stem

    declared_source = tmp_path / "with_sample.csv"
    declared_sample = f"{declared_source.stem}_declared"
    declared_source.write_text(
        "\n".join(
            ",".join(row)
            for row in [
                ["Temperature", "Mass"],
                ["C", "%"],
                [declared_sample, declared_sample],
                *numeric_rows,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    declared_series = resolve_tga_transform(declared_source).series[0]
    declared_diagnostics = dict(declared_series.diagnostics or {})
    assert declared_series.sample == declared_sample
    assert declared_series.points == fallback_series.points
    assert declared_diagnostics["source_sample_detection"] == (
        "detected_from_adjacent_sample_row"
    )
    assert declared_diagnostics["source_sample_row_index"] == 2
    assert declared_diagnostics["source_sample_value"] == declared_sample

    partial_source = tmp_path / "without_sample_partial_first_row.csv"
    partial_source.write_text(
        "Temperature,Mass\nC,%\n25,\n50,95\n",
        encoding="utf-8",
    )
    partial_series = resolve_tga_transform(partial_source).series[0]
    partial_diagnostics = dict(partial_series.diagnostics or {})
    assert partial_series.sample == partial_source.stem
    assert partial_series.points == ((50.0, 95.0),)
    assert partial_diagnostics["candidate_row_count"] == 2
    assert partial_diagnostics["excluded_partial_or_nonnumeric_pair_count"] == 1


@pytest.mark.parametrize("source_temperature_unit", ["℃", "ºC", "˚C"])
def test_registered_paired_curve_uses_rule_axes_metrics_and_identity_units(
    tmp_path: Path,
    source_temperature_unit: str,
) -> None:
    source = tmp_path / "registered_curve.csv"
    sample = f"{source.stem}_declared"
    source_rows = [["50", "-2"], ["25", "3"]]
    source.write_text(
        "Probe temp,Residual signal\n"
        f"{source_temperature_unit},%\n"
        f"{sample},{sample}\n"
        + "\n".join(",".join(row) for row in source_rows)
        + "\n",
        encoding="utf-8",
    )
    rule = replace(
        get_rule(RULE_ID),
        x_axis=AxisSpec(
            "Furnace coordinate",
            "C",
            "Furnace coordinate (°C)",
            aliases=("probe temp",),
        ),
        y_axis=AxisSpec(
            "Remaining mass",
            "%",
            "Remaining mass (%)",
            aliases=("residual signal",),
        ),
    )

    resolved = resolve_registered_paired_curve_transform(source, rule=rule)
    series = resolved.series[0]
    contract = resolved.contract.to_payload()

    assert (series.x_label, series.x_unit) == ("Furnace coordinate", "C")
    assert (series.y_label, series.y_unit) == ("Remaining mass", "%")
    assert series.sample == sample
    assert series.points == tuple(
        (float(row[0]), float(row[1])) for row in source_rows
    )
    assert contract["source_columns"][0]["x"]["header"] == "Probe temp"
    assert contract["source_columns"][0]["response"]["header"] == (
        "Residual signal"
    )
    assert contract["output"]["x_metric"] == "furnace_coordinate"
    assert contract["output"]["y_metric"] == "remaining_mass"
    assert contract["normalizer"]["operation"] == "none"
    assert contract["x_coordinate_policy"]["sorting_applied"] is False
    assert contract["x_coordinate_policy"]["interpolation_applied"] is False
    assert contract["unit_conversions"][0]["source_unit"] == (
        source_temperature_unit
    )
