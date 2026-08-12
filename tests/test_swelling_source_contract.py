from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core._paths import resolve_fixture_path
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.swelling_sources import (
    _read_swelling_series_list,
)
from sciplot_core.semantic_sources.swelling_transform import (
    _validate_selection_closure,
    resolve_swelling_scientific_transform,
)


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
        "first_labeled_pair_run_with_isolated_blank_bridge"
    )
    assert source_block["excluded_disconnected_rows"] == 0
    assert source_block["isolated_blank_bridge_count"] == 1
    assert source_block["candidate_pair_row_count"] == len(expected)


def test_swelling_prepare_stops_at_an_explicit_following_metric_header(
    tmp_path: Path,
) -> None:
    source = tmp_path / "synthetic_swelling.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None],
            ["1", None],
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
    assert source_block["excluded_nonnumeric_pair_count"] == 1
    assert source_block["excluded_disconnected_point_count"] == 2
    assert source_block["candidate_pair_row_count"] == 5


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
        rows: list[list[object]] = [
            ["Condition A", None],
            ["1", None],
            [header, "Swelling ratio"],
        ]
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
                ["Condition A", None],
                ["1", None],
                [header, "Swelling ratio"],
                [1.0, 1.0],
                [2.0, 1.2],
            ],
        )

        with pytest.raises(ValueError, match=r"expected s, min, or h"):
            _prepare(source, output_dir)

        assert not list((output_dir / "processed").glob("*"))


def test_swelling_first_labeled_run_does_not_rejoin_a_later_numeric_block(
    tmp_path: Path,
) -> None:
    source = tmp_path / "disconnected.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None],
            ["1", None],
            ["Time (h)", "Ai/A0 (unitless)"],
            [0.0, 1.0],
            [1.0, 1.1],
            [None, None],
            [None, None],
            [50.0, 9.0],
            [51.0, 9.1],
            [52.0, 9.2],
        ],
    )

    resolved = resolve_swelling_scientific_transform(source)

    assert resolved.series[0].points == ((0.0, 1.0), (1.0, 1.1))
    block = (resolved.series[0].diagnostics or {})["source_block"]
    assert block["excluded_disconnected_point_count"] == 3
    assert block["candidate_pair_row_count"] == 5
    assert block["retained_point_count"] == 2


def test_swelling_source_rejects_ambiguous_tables_and_missing_identity(
    tmp_path: Path,
) -> None:
    ambiguous = tmp_path / "ambiguous.xlsx"
    frame = pd.DataFrame(
        [
            ["Condition A", None],
            ["1", None],
            ["Time (h)", "Swelling ratio"],
            [0.0, 1.0],
        ]
    )
    with pd.ExcelWriter(ambiguous) as writer:
        frame.to_excel(writer, sheet_name="one", header=False, index=False)
        frame.to_excel(writer, sheet_name="two", header=False, index=False)

    with pytest.raises(ValueError, match="exactly one matching labeled worksheet"):
        _read_swelling_series_list(ambiguous)

    missing_identity = tmp_path / "missing_identity.xlsx"
    _write_workbook(
        missing_identity,
        [["Time (h)", "Swelling ratio"], [0.0, 1.0], [1.0, 1.1]],
    )
    with pytest.raises(ValueError, match="lacks source-derived"):
        resolve_swelling_scientific_transform(missing_identity)


def test_swelling_directory_requires_one_supported_member_and_binds_it(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="found 0"):
        resolve_swelling_scientific_transform(empty)

    multiple = tmp_path / "multiple"
    multiple.mkdir()
    for name in ("a.xlsx", "b.xlsx"):
        _write_workbook(
            multiple / name,
            [
                ["Condition A", None],
                ["1", None],
                ["Time (h)", "Swelling ratio"],
                [0.0, 1.0],
            ],
        )
    with pytest.raises(ValueError, match="found 2"):
        resolve_swelling_scientific_transform(multiple)

    nested = tmp_path / "nested" / "source"
    nested.mkdir(parents=True)
    member = nested / "only.xlsx"
    _write_workbook(
        member,
        [
            ["Condition A", None],
            ["1", None],
            ["Time (h)", "Swelling ratio"],
            [0.0, 1.0],
        ],
    )
    resolved = resolve_swelling_scientific_transform(tmp_path / "nested")
    assert resolved.selected_sources == (member.resolve(),)
    assert resolved.contract.selected_sources == (str(member.resolve()),)


def test_swelling_identity_preserves_source_text_and_projects_cell_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "identity.xlsx"
    _write_workbook(
        source,
        [
            ["Fig 8 (a): A_B  C", None],
            ["rep_01", None],
            ["Time (h)", "Swelling ratio"],
            [0.0, 1.0],
            [1.0, 1.1],
        ],
    )

    resolved = resolve_swelling_scientific_transform(source)
    series = resolved.series[0]
    identity = (series.diagnostics or {})["source_identity"]

    assert series.sample == "Fig 8 (a): A_B  C replicate rep_01"
    assert identity == {
        "kind": "parallel_condition_and_replicate_cells",
        "condition": {
            "value": "Fig 8 (a): A_B  C",
            "raw_cell": "Fig 8 (a): A_B  C",
            "row_index_zero_based": 0,
            "column_index_zero_based": 0,
            "extraction": "preserve_clean_source_text",
            "structural_prefix": "Fig 8 (a):",
        },
        "replicate": {
            "value": "rep_01",
            "raw_cell": "rep_01",
            "row_index_zero_based": 1,
            "column_index_zero_based": 0,
            "extraction": "preserve_clean_source_text",
        },
    }
    assert resolved.contract.source_columns[0]["identity"] == identity


def test_swelling_long_form_identity_records_sample_column_and_source_rows(
    tmp_path: Path,
) -> None:
    source = tmp_path / "long_form.xlsx"
    _write_workbook(
        source,
        [
            ["Sample", "Time (h)", "Swelling ratio"],
            ["A_1", 0.0, 1.0],
            ["B_2", 0.0, 1.0],
            ["A_1", 1.0, 1.2],
            ["B_2", 1.0, 1.3],
        ],
    )

    resolved = resolve_swelling_scientific_transform(source)

    assert [series.sample for series in resolved.series] == ["A_1", "B_2"]
    identities = [
        (series.diagnostics or {})["source_identity"]["sample"]
        for series in resolved.series
    ]
    assert identities[0]["column_index_zero_based"] == 0
    assert identities[0]["row_indices_zero_based"] == [1, 3]
    assert identities[0]["row_span_zero_based"] == [1, 3]
    assert identities[1]["row_indices_zero_based"] == [2, 4]
    assert [
        column["identity"]["sample"]
        for column in resolved.contract.source_columns
    ] == identities
    for series in resolved.series:
        block = (series.diagnostics or {})["source_block"]
        assert block["retained_point_count"] == len(series.points)
        assert block["candidate_pair_row_count"] == len(series.points)


def test_swelling_long_form_closes_disconnected_evidence_per_sample(
    tmp_path: Path,
) -> None:
    source = tmp_path / "long_disconnected.xlsx"
    _write_workbook(
        source,
        [
            ["Sample", "Time (h)", "Swelling ratio"],
            ["A", 0.0, 1.0],
            ["B", 0.0, 1.1],
            [None, None, None],
            [None, None, None],
            ["A", 2.0, 9.0],
            ["B", 2.0, 9.1],
        ],
    )

    resolved = resolve_swelling_scientific_transform(source)

    assert [series.points for series in resolved.series] == [
        ((0.0, 1.0),),
        ((0.0, 1.1),),
    ]
    for series in resolved.series:
        block = (series.diagnostics or {})["source_block"]
        assert block["retained_point_count"] == len(series.points) == 1
        assert block["excluded_disconnected_point_count"] == 1
        assert block["candidate_pair_row_count"] == 2


@pytest.mark.parametrize("first_pair", [([0.0, None]), (["bad", "bad"])])
def test_swelling_rejects_invalid_rows_before_the_first_finite_pair(
    tmp_path: Path,
    first_pair: list[object],
) -> None:
    source = tmp_path / "invalid_start.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None],
            ["1", None],
            ["Time (h)", "Swelling ratio"],
            first_pair,
            [1.0, 1.1],
        ],
    )

    with pytest.raises(ValueError, match="starts the selected measurement pair"):
        resolve_swelling_scientific_transform(source)


def test_swelling_selected_columns_parse_small_decimal_comma_without_scaling(
    tmp_path: Path,
) -> None:
    source = tmp_path / "decimal_comma.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None],
            ["1", None],
            ["Time (h)", "Swelling ratio"],
            ["0,25", "1,25"],
            ["1,50", "1,50"],
        ],
    )

    resolved = resolve_swelling_scientific_transform(source)

    assert resolved.series[0].points == ((0.25, 1.25), (1.5, 1.5))
    assert (resolved.series[0].diagnostics or {})["numeric_separator_evidence"][
        "decimal_separator"
    ] == ","


def test_swelling_disconnected_block_cannot_choose_the_retained_run_locale(
    tmp_path: Path,
) -> None:
    source = tmp_path / "locale_scope.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None],
            ["1", None],
            ["Time (h)", "Swelling ratio"],
            ["12,345", "13"],
            [None, None],
            [None, None],
            [0.1, 1.1],
        ],
    )

    with pytest.raises(ValueError, match="ambiguous `12,345`-shaped values"):
        resolve_swelling_scientific_transform(source)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            [["0,25", "1,25"], ["1.5", "1.5"]],
            "mix point-decimal and comma-decimal",
        ),
        (
            [["12,345", "13"]],
            "ambiguous `12,345`-shaped values",
        ),
    ],
)
def test_swelling_selected_columns_reject_mixed_or_ambiguous_separators(
    tmp_path: Path,
    rows: list[list[object]],
    message: str,
) -> None:
    source = tmp_path / "invalid_separator.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None],
            ["1", None],
            ["Time (h)", "Swelling ratio"],
            *rows,
        ],
    )

    with pytest.raises(ValueError, match=message):
        resolve_swelling_scientific_transform(source)


@pytest.mark.parametrize(
    "response_header",
    (
        "Swelling ratio",
        "Ai/A0 (unitless)",
        "Normalized projected area [1]",
    ),
)
def test_swelling_response_header_accepts_only_registered_ratio_quantities(
    tmp_path: Path,
    response_header: str,
) -> None:
    source = tmp_path / "supported_response.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None],
            ["1", None],
            ["Time (h)", response_header],
            [0.0, 1.0],
            [1.0, 1.1],
        ],
    )

    resolved = resolve_swelling_scientific_transform(source)

    assert resolved.series[0].y_unit == "1"


@pytest.mark.parametrize(
    ("header", "unit_row"),
    (
        ("Time (days)", "s"),
        ("Time (s/min)", "s"),
        ("Time days", "s"),
        ("Time d", "s"),
    ),
)
def test_swelling_time_unit_conflict_or_unsupported_header_cannot_be_masked(
    tmp_path: Path,
    header: str,
    unit_row: str,
) -> None:
    source = tmp_path / "invalid_time_unit.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None],
            ["1", None],
            [header, "Swelling ratio"],
            [unit_row, "1"],
            [1.0, 1.1],
        ],
    )

    with pytest.raises(ValueError, match="ambiguous|unsupported"):
        resolve_swelling_scientific_transform(source)


def test_swelling_measurement_text_is_not_consumed_as_an_adjacent_unit_row(
    tmp_path: Path,
) -> None:
    source = tmp_path / "measurement_text.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None],
            ["1", None],
            ["Time", "Swelling ratio"],
            ["1 s", "1"],
            [2.0, 1.1],
        ],
    )

    with pytest.raises(ValueError, match="missing or unsupported"):
        resolve_swelling_scientific_transform(source)


@pytest.mark.parametrize(
    "response_header",
    (
        "Swelling ratio (Pa)",
        "Swelling ratio Pa",
        "Swelling ratio (%)",
        "Swelling ratio SD",
        "Swelling ratio (SD)",
        "Standard deviation of swelling ratio",
    ),
)
def test_swelling_response_header_rejects_units_and_uncertainty_qualifiers(
    tmp_path: Path,
    response_header: str,
) -> None:
    source = tmp_path / "invalid_response.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None],
            ["1", None],
            ["Time (h)", response_header],
            [0.0, 1.0],
            [1.0, 1.1],
        ],
    )

    with pytest.raises(ValueError, match="exactly one matching labeled worksheet"):
        resolve_swelling_scientific_transform(source)


def test_swelling_structural_content_prevents_blank_row_bridge(
    tmp_path: Path,
) -> None:
    source = tmp_path / "structural_break.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None, None],
            ["1", None, None],
            ["Time (h)", "Swelling ratio", None],
            [0.0, 1.0, None],
            [1.0, 1.1, None],
            [None, None, "Next section"],
            [2.0, 1.2, None],
        ],
    )

    resolved = resolve_swelling_scientific_transform(source)

    assert resolved.series[0].points == ((0.0, 1.0), (1.0, 1.1))
    block = (resolved.series[0].diagnostics or {})["source_block"]
    assert block["isolated_blank_bridge_count"] == 0
    assert block["termination_reason"] == "structural_content_row"
    assert block["excluded_disconnected_point_count"] == 1


def test_swelling_pair_blank_can_bridge_while_sibling_pair_has_numeric_data(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sibling_numeric.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None, "Condition B", None],
            ["1", None, "1", None],
            [
                "Time (h)",
                "Swelling ratio",
                "Time (h)",
                "Swelling ratio",
            ],
            [0.0, 1.0, 0.0, 1.0],
            [None, None, 1.0, 1.1],
            [2.0, 1.2, 2.0, 1.2],
        ],
    )

    resolved = resolve_swelling_scientific_transform(source)

    assert resolved.series[0].points == ((0.0, 1.0), (2.0, 1.2))
    assert (resolved.series[0].diagnostics or {})["source_block"][
        "isolated_blank_bridge_count"
    ] == 1


def test_swelling_transform_selection_closure_is_an_internal_invariant() -> None:
    series = CurveSeriesPayload(
        sample="source identity",
        x_label="Time",
        x_unit="h",
        y_label="Swelling ratio",
        y_unit="1",
        points=((0.0, 1.0),),
        diagnostics={
            "source_block": {
                "retained_point_count": 2,
                "candidate_pair_row_count": 2,
            }
        },
    )

    with pytest.raises(RuntimeError, match="retained-row evidence"):
        _validate_selection_closure(series)


def test_swelling_preserves_na_lexemes_as_breaks_not_blank_formatting(
    tmp_path: Path,
) -> None:
    source = tmp_path / "na_break.csv"
    source.write_text(
        "Condition A,\n"
        "1,\n"
        "Time (h),Swelling ratio\n"
        "0,1\n"
        "NA,NA\n"
        "2,1.2\n",
        encoding="utf-8",
    )

    resolved = resolve_swelling_scientific_transform(source)

    assert resolved.series[0].points == ((0.0, 1.0),)
    block = (resolved.series[0].diagnostics or {})["source_block"]
    assert block["isolated_blank_bridge_count"] == 0
    assert block["excluded_nonnumeric_pair_count"] == 1
    assert block["excluded_disconnected_point_count"] == 1


def test_swelling_rejects_preserved_nan_lexemes_as_nonfinite(
    tmp_path: Path,
) -> None:
    source = tmp_path / "nan_break.csv"
    source.write_text(
        "Condition A,\n"
        "1,\n"
        "Time (h),Swelling ratio\n"
        "0,1\n"
        "NaN,NaN\n"
        "2,1.2\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="nonfinite"):
        resolve_swelling_scientific_transform(source)


def test_swelling_excel_snapshot_preserves_nan_lexeme_as_nonfinite(
    tmp_path: Path,
) -> None:
    source = tmp_path / "nan_break.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None],
            ["1", None],
            ["Time (h)", "Swelling ratio"],
            [0.0, 1.0],
            ["NaN", "NaN"],
            [2.0, 1.2],
        ],
    )

    with pytest.raises(ValueError, match="nonfinite"):
        resolve_swelling_scientific_transform(source)


def test_swelling_transform_applies_only_known_explicit_source_order(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ordered.xlsx"
    _write_workbook(
        source,
        [
            ["Condition A", None, "Condition B", None],
            ["1", None, "1", None],
            [
                "Time (h)",
                "Swelling ratio",
                "Time (h)",
                "Swelling ratio",
            ],
            [0.0, 1.0, 0.0, 1.0],
            [1.0, 1.1, 1.0, 1.2],
        ],
    )
    source_order = resolve_swelling_scientific_transform(source)
    reversed_order = list(reversed(source_order.contract.output["series_order"]))

    reordered = resolve_swelling_scientific_transform(
        source,
        series_order=reversed_order,
    )

    assert reordered.contract.output["series_order"] == reversed_order
    assert reordered.contract.output["explicit_series_order_applied"] is True
    with pytest.raises(ValueError, match="unknown source identities"):
        resolve_swelling_scientific_transform(source, series_order=["not present"])


def test_real_swelling_fixture_matches_its_authorized_labeled_block_dynamically() -> None:
    rule = get_rule("swelling_curve")
    source = resolve_fixture_path(str(rule.fixture_path or ""))
    if not source.exists():
        pytest.skip("local authorized real-world swelling fixture is unavailable")
    provenance_path = source.parent / "source_provenance.json"
    if not provenance_path.exists():
        pytest.skip("authorized swelling provenance is unavailable beside fixture")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    resolved = resolve_swelling_scientific_transform(source)
    selected_sheet = str(provenance["selected_sheet"])
    header_index = int(provenance["selected_source_rows"]["header_excel_row"]) - 1
    data_start, data_end = (
        int(value) - 1
        for value in provenance["selected_source_rows"]["data_excel_rows"]
    )
    with pd.ExcelFile(source) as workbook:
        raw = workbook.parse(selected_sheet, header=None)
    headers = [str(value).strip() for value in raw.iloc[header_index].tolist()]
    x_header = str(provenance["source_axes"]["x"])
    y_header = str(provenance["source_axes"]["y"])
    x_columns = [index for index, value in enumerate(headers) if value == x_header]
    pairs: list[tuple[int, int]] = []
    for position, x_index in enumerate(x_columns):
        stop = x_columns[position + 1] if position + 1 < len(x_columns) else len(headers)
        y_columns = [
            index
            for index in range(x_index + 1, stop)
            if headers[index] == y_header
        ]
        assert len(y_columns) == 1
        pairs.append((x_index, y_columns[0]))
    factor = float(provenance["time_conversion"]["factor"])
    expected_points: list[tuple[tuple[float, float], ...]] = []
    for x_index, y_index in pairs:
        pair_points = []
        for row_index in range(data_start, data_end + 1):
            x_value = pd.to_numeric(raw.iat[row_index, x_index], errors="coerce")
            y_value = pd.to_numeric(raw.iat[row_index, y_index], errors="coerce")
            if pd.notna(x_value) and pd.notna(y_value):
                assert math.isfinite(float(x_value))
                assert math.isfinite(float(y_value))
                pair_points.append((float(x_value) * factor, float(y_value)))
        expected_points.append(tuple(pair_points))
    expected_counts = [int(value) for value in provenance["source_point_counts"]]
    assert [len(points) for points in expected_points] == expected_counts
    conditions = [str(value) for value in provenance["conditions"]]
    replicate_count = int(provenance["replicate_count_per_condition"])
    assert len(pairs) == len(conditions) * replicate_count
    expected_samples = []
    expected_condition_cells = []
    for pair_index, (x_index, _y_index) in enumerate(pairs):
        provenance_condition = conditions[pair_index // replicate_count]
        condition_column = x_index
        while pd.isna(raw.iat[header_index - 2, condition_column]) or not str(
            raw.iat[header_index - 2, condition_column]
        ).strip():
            condition_column -= 1
        condition = str(raw.iat[header_index - 2, condition_column]).strip()
        assert provenance_condition in condition
        replicate_cell = raw.iat[header_index - 1, x_index]
        replicate = (
            str(int(float(replicate_cell)))
            if float(replicate_cell).is_integer()
            else str(replicate_cell).strip()
        )
        expected_samples.append(f"{condition} replicate {replicate}")
        expected_condition_cells.append(
            (condition, header_index - 2, condition_column)
        )
    assert [series.sample for series in resolved.series] == expected_samples
    assert resolved.selected_sources == (source.resolve(),)
    assert resolved.contract.selected_sources == (str(source.resolve()),)
    assert resolved.contract.output["x_unit"] == provenance["output_units"]["time"]
    assert resolved.contract.output["y_unit"] == provenance["output_units"][
        "swelling_ratio"
    ]
    assert resolved.contract.x_coordinate_policy["operation"] == (
        "convert_explicit_time_unit_and_preserve_source_row_order"
    )
    expected_table = f"{source.stem}:{selected_sheet}"
    for series, expected, x_pair, expected_condition_cell in zip(
        resolved.series,
        expected_points,
        pairs,
        expected_condition_cells,
        strict=True,
    ):
        assert len(series.points) == len(expected)
        for actual_point, expected_point in zip(series.points, expected, strict=True):
            assert actual_point[0] == pytest.approx(expected_point[0])
            assert actual_point[1] == pytest.approx(expected_point[1])
        diagnostics = series.diagnostics or {}
        assert diagnostics["source_file"] == str(source.resolve())
        assert diagnostics["source_table"] == expected_table
        assert diagnostics["source_column_indices"] == {
            "x": x_pair[0],
            "y": x_pair[1],
        }
        assert diagnostics["source_columns"] == {"x": x_header, "y": y_header}
        assert diagnostics["time_conversion"] == provenance["time_conversion"]
        identity = diagnostics["source_identity"]
        condition_cell = identity["condition"]
        replicate_cell = identity["replicate"]
        assert (
            condition_cell["value"],
            condition_cell["row_index_zero_based"],
            condition_cell["column_index_zero_based"],
        ) == expected_condition_cell
        assert condition_cell["raw_cell"] == str(
            raw.iat[
                condition_cell["row_index_zero_based"],
                condition_cell["column_index_zero_based"],
            ]
        ).strip()
        assert replicate_cell["raw_cell"] == str(
            int(
                raw.iat[
                    replicate_cell["row_index_zero_based"],
                    replicate_cell["column_index_zero_based"],
                ]
            )
        )
    assert [column["identity"] for column in resolved.contract.source_columns] == [
        (series.diagnostics or {})["source_identity"] for series in resolved.series
    ]
    assert all(
        column["source_table"] == expected_table
        for column in resolved.contract.source_columns
    )
