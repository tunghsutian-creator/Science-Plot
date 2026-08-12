from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.semantic import prepare_semantic_source


def _write_workbook(path: Path, rows: list[list[object]]) -> None:
    pd.DataFrame(rows).to_excel(path, header=False, index=False)


def _prepared_points(prepared: dict[str, object]) -> tuple[tuple[float, float], ...]:
    table = pd.read_csv(str(prepared["processed_source"]), header=None)
    return tuple(
        (float(time), float(response))
        for time, response in table.iloc[3:, :2].itertuples(index=False, name=None)
    )


def _prepare(source: Path, output_dir: Path) -> dict[str, object]:
    return prepare_semantic_source(
        source,
        output_dir=output_dir,
        semantic={"semantic_family": "swelling_curve", "rule_id": "swelling_curve"},
    )


def test_swelling_prepare_keeps_points_after_a_blank_source_row(
    tmp_path: Path,
) -> None:
    source = tmp_path / "synthetic_swelling.xlsx"
    expected = ((0.0, 1.0), (1.0, 1.1), (2.0, 1.2), (3.0, 1.3))
    _write_workbook(
        source,
        [
            ["Condition", None],
            ["1", None],
            ["Time (h)", "Swelling ratio"],
            [0.0, 1.0],
            [1.0, 1.1],
            [None, None],
            [2.0, 1.2],
            [3.0, 1.3],
        ],
    )

    prepared = _prepare(source, tmp_path / "prepared")
    parameters = prepared["transform_steps"][0]["parameters"]

    assert _prepared_points(prepared) == expected
    assert parameters["source_point_counts"] == [len(expected)]
    source_block = parameters["source_selections"][0]["source_block"]
    assert source_block["selection_policy"] == (
        "labeled_block_until_next_explicit_header"
    )
    assert source_block["excluded_disconnected_rows"] == 0


def test_swelling_prepare_stops_at_an_explicit_following_metric_header(
    tmp_path: Path,
) -> None:
    source = tmp_path / "synthetic_swelling.xlsx"
    _write_workbook(
        source,
        [
            ["Time (h)", "Swelling ratio"],
            [0.0, 1.0],
            [1.0, 1.1],
            ["Time (h)", "Gel fraction"],
            [0.0, 0.4],
            [1.0, 0.5],
        ],
    )

    prepared = _prepare(source, tmp_path / "prepared")
    parameters = prepared["transform_steps"][0]["parameters"]

    assert _prepared_points(prepared) == ((0.0, 1.0), (1.0, 1.1))
    assert parameters["source_point_counts"] == [2]
    source_block = parameters["source_selections"][0]["source_block"]
    assert source_block["excluded_disconnected_rows"] == 3


def test_swelling_prepare_converts_only_explicit_supported_time_units(
    tmp_path: Path,
) -> None:
    cases = (
        ("Time (s)", None, "s", 3600.0, 1.0 / 3600.0),
        ("Time (min)", None, "min", 60.0, 1.0 / 60.0),
        ("Time (hours)", None, "h", 1.0, 1.0),
        ("Time", "s", "s", 3600.0, 1.0 / 3600.0),
    )
    for index, (header, unit_row, source_unit, source_time, factor) in enumerate(
        cases
    ):
        source = tmp_path / f"explicit_unit_{index}.xlsx"
        rows: list[list[object]] = [[header, "Swelling ratio"]]
        if unit_row is not None:
            rows.append([unit_row, "1"])
        rows.extend(
            [
                [source_time, 1.0],
                [source_time * 2.0, 1.2],
            ]
        )
        _write_workbook(
            source,
            rows,
        )

        prepared = _prepare(source, tmp_path / f"prepared_{index}")
        parameters = prepared["transform_steps"][0]["parameters"]
        conversion = parameters["source_selections"][0]["time_conversion"]

        assert _prepared_points(prepared) == ((1.0, 1.0), (2.0, 1.2))
        assert conversion == {
            "source_unit": source_unit,
            "canonical_unit": "h",
            "factor": factor,
        }


def test_swelling_prepare_rejects_missing_or_unsupported_time_units_before_write(
    tmp_path: Path,
) -> None:
    for index, header in enumerate(("Time", "Time (days)")):
        source = tmp_path / f"invalid_unit_{index}.xlsx"
        output_dir = tmp_path / f"invalid_output_{index}"
        _write_workbook(
            source,
            [
                [header, "Swelling ratio"],
                [1.0, 1.0],
                [2.0, 1.2],
            ],
        )

        with pytest.raises(ValueError, match=r"expected s, min, or h"):
            _prepare(source, output_dir)

        assert not list((output_dir / "processed").glob("*"))
