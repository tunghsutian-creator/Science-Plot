from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.plan_preview import build_plan_preview
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.semantic_sources.scientific_source import (
    resolve_scientific_source,
)
from sciplot_core.semantic_sources.rheology_interval import (
    _read_rheology_interval_series,
)
from sciplot_core.semantic_sources.stress_relaxation_transform import (
    resolve_stress_relaxation_transform,
)


def _write_relaxation_export(path: Path) -> None:
    strains = ("", 3.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0)
    stresses = (100.0, 95.0, 90.0, 80.0, 72.0, 65.0, 59.0, 54.0, 50.0, 47.0)
    rows = [
        "Project:\tRelaxation Test",
        "Test:\tE3",
        "Result:\tStress Relaxation 1",
        "Interval and data points:\t1\t10",
        (
            "Interval data:\tPoint No.\tTime\tShear Strain\tShear Stress"
            "\tRelaxation Modulus"
        ),
        "\t\t\t\t\t",
        "\t\t[s]\t[%]\t[Pa]\t[Pa]",
    ]
    for index, (strain, stress) in enumerate(
        zip(strains, stresses, strict=True),
        start=1,
    ):
        modulus = stress / float(strain) if strain != "" else ""
        rows.append(
            f"\t{index}\t{index / 10:.1f}\t{strain}\t{stress}\t{modulus}"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-16")


def _write_two_interval_export(path: Path) -> None:
    rows = [
        "Test:\tE3",
        "Result:\tStress Relaxation 1",
        "Interval and data points:\t1\t3",
        "Interval data:\tPoint No.\tTime\tShear Strain\tShear Stress",
        "\t\t\t\t",
        "\t\t[s]\t[%]\t[Pa]",
        "\t1\t0.01\t1\t100",
        "\t2\t0.02\t2\t95",
        "\t3\t0.03\t3\t90",
        "Interval and data points:\t2\t8",
        (
            "Interval data:\tPoint No.\tTime\tShear Stress"
            "\tRelaxation Modulus\tShear Strain"
        ),
        "\t\t\t\t\t",
        "\t\t[s]\t[Pa]\t[Pa]\t[%]",
    ]
    rows.extend(
        f"\t{index}\t{index / 10:.1f}\t{90 - index * 5}\t{18 - index}\t5"
        for index in range(1, 9)
    )
    path.write_text("\n".join(rows) + "\n", encoding="utf-16")


def _write_short_drifting_final_interval_export(
    path: Path,
    *,
    first_response: float = 80.0,
) -> None:
    rows = [
        "Test:\tsynthetic_specimen",
        "Result:\tStress Relaxation 1",
        "Interval and data points:\t1\t2",
        "Interval data:\tPoint No.\tTime\tShear Strain\tShear Stress",
        "\t\t\t\t",
        "\t\t[s]\t[%]\t[Pa]",
        "\t1\t0.1\t1\t100",
        "\t2\t0.2\t2\t90",
        "Interval and data points:\t2\t4",
        "Interval data:\tPoint No.\tTime\tShear Strain\tShear Stress",
        "\t\t\t\t",
        "\t\t[s]\t[%]\t[Pa]",
    ]
    controls = (10.0, 12.0, 9.0, 11.0)
    responses = (first_response, 70.0, 60.0, 50.0)
    rows.extend(
        f"\t{index}\t{float(index):.1f}\t{control}\t{response}"
        for index, (control, response) in enumerate(
            zip(controls, responses, strict=True),
            start=1,
        )
    )
    path.write_text("\n".join(rows) + "\n", encoding="utf-16")


def _stress_test_section(sample: str, *, response_offset: float = 0.0) -> list[str]:
    rows = [
        f"Test:\t{sample}",
        "Result:\tStress Relaxation 1",
        "Interval and data points:\t1\t8",
        "Interval data:\tPoint No.\tTime\tShear Strain\tShear Stress",
        "\t\t\t\t",
        "\t\t[s]\t[%]\t[Pa]",
    ]
    rows.extend(
        f"\t{index}\t{index / 10:.1f}\t{3 if index == 1 else 5}"
        f"\t{response_offset + 100 - index * 5}"
        for index in range(1, 9)
    )
    return rows


def _write_invalid_time_export(path: Path, time_cell: str) -> None:
    rows = _stress_test_section("E3", response_offset=0.0)
    rows[2] = "Interval and data points:\t1\t11"
    rows.extend(
        f"\t{index}\t{index / 10:.1f}\t5\t{100 - index * 5}"
        for index in range(9, 11)
    )
    rows.append(f"\t11\t{time_cell}\t5\t45")
    path.write_text("\n".join(rows) + "\n", encoding="utf-16")


def _write_interval_unit_layout(path: Path, *, blank_before_units: bool) -> None:
    rows = [
        "Test:\tunit_layout",
        "Result:\tStress Relaxation 1",
        "Interval and data points:\t1\t3",
        "Interval data:\tPoint No.\tTime\tShear Strain\tShear Stress",
    ]
    if blank_before_units:
        rows.append("\t\t\t\t")
    rows.extend(
        [
            "\t\t[s]\t[%]\t[Pa]",
            "\t1\t0.01\t5\t100",
            "\t2\t0.02\t5\t90",
            "\t3\t0.03\t5\t80",
        ]
    )
    path.write_text("\n".join(rows) + "\n", encoding="utf-16")


def test_stress_transform_contract_is_shared_by_preview_and_materialization(
    tmp_path: Path,
) -> None:
    source = tmp_path / "relaxation"
    source.mkdir()
    source_file = source / "instrument_export.csv"
    _write_relaxation_export(source_file)

    resolved = resolve_stress_relaxation_transform(source)
    contract = resolved.contract.to_payload()

    assert resolved.selected_sources == (source_file.resolve(),)
    assert contract["source_columns"] == [
        {
            "sample": "E3",
            "sources": [str(source_file.resolve())],
            "result_index": 1,
            "result_label": "Stress Relaxation 1",
            "interval_index": 1,
            "response_header_row_index": 4,
            "control_header_row_index": 4,
            "x": {
                "role": "coordinate",
                "header": "Time",
                "unit": "s",
                "column_index_zero_based": 2,
            },
            "response": {
                "role": "response",
                "header": "Shear Stress",
                "unit": "Pa",
                "column_index_zero_based": 4,
            },
            "control": {
                "role": "control",
                "header": "Shear Strain",
                "unit": "%",
                "column_index_zero_based": 3,
            },
        }
    ]
    anchor = contract["anchor"]["selections"][0]
    assert anchor["selector"] == "final_common_interval_first_aligned_response"
    assert anchor["applicable"] is True
    assert anchor["source_time"] == 0.2
    assert anchor["response_value"] == 95.0
    assert anchor["retained"] is True
    assert anchor["output_point"] == [0.2, 1.0]
    assert contract["x_coordinate_policy"] == {
        "operation": "preserve_source_coordinate",
        "metric": "time",
        "unit": "s",
        "reset_applied": False,
    }
    assert contract["retain_anchor"] is True
    assert contract["axis_compatibility"]["x"] == {
        "registered_scale": "log",
        "finite_compatible": True,
        "log_compatible": True,
        "nonpositive_count": 0,
        "excluded_incompatible_point_count": 0,
    }
    response_conversion = next(
        item
        for item in contract["unit_conversions"]
        if item["role"] == "response"
    )
    assert response_conversion == {
        "sample": "E3",
        "role": "response",
        "source_unit": "Pa",
        "canonical_unit": "Pa",
        "display_unit": "Pa",
        "source_to_canonical": {"factor": 1.0, "offset": 0.0},
        "canonical_to_display": {"factor": 1.0, "offset": 0.0},
    }
    assert contract["output"]["series"][0]["first_point"] == [0.2, 1.0]
    output_evidence = contract["output"]["series"][0]
    assert output_evidence["candidate_point_counts"] == {
        "response": 10,
        "aligned": 9,
        "control": 10,
    }
    assert output_evidence["excluded_point_count"] == 1
    assert output_evidence["excluded_by_reason"] == {
        "prior_interval": 0,
        "nonfinite_or_missing_time": 0,
        "nonfinite_or_missing_response": 0,
        "unmatched_response_control": 1,
        "loading_before_anchor": 0,
        "nonpositive_log_x": 0,
        "nonfinite_log_point": 0,
        "other_parser_exclusion": 0,
    }
    assert output_evidence["control_exclusions"]["nonfinite_or_missing"] == 1
    assert output_evidence["source_point_count"] == output_evidence[
        "retained_point_count"
    ] + sum(output_evidence["excluded_by_reason"].values())

    preview = build_plan_preview(
        source,
        request={
            "rule_id": "rheology_stress_relaxation",
            "template": "curve",
        },
    )
    assert preview["status"] == "planned"
    plan = preview["resolved_figure_plan"]
    assert plan is not None
    assert plan["selection_policy"] == "registered_single_curve"
    assert len(plan["tasks"]) == 1
    assert plan["tasks"][0]["metric_binding"] == {
        "kind": "cartesian_xy",
        "x_metric": "time",
        "y_metric": "normalized_stress",
    }
    assert preview["scientific_transform"] == contract

    prepared = prepare_semantic_source(
        source,
        output_dir=tmp_path / "prepared",
        semantic={
            "semantic_family": "rheology_stress_relaxation",
            "rule_id": "rheology_stress_relaxation",
        },
    )
    step = prepared["transform_steps"][0]
    assert step["parameters"]["scientific_transform"] == contract
    table = pd.read_csv(prepared["processed_source"], header=None)
    assert [float(value) for value in table.iloc[3, :2]] == [0.2, 1.0]


def test_stress_transform_binds_columns_from_the_actual_hold_interval(
    tmp_path: Path,
) -> None:
    source = tmp_path / "two_intervals.csv"
    _write_two_interval_export(source)

    contract = resolve_stress_relaxation_transform(source).contract.to_payload()

    columns = contract["source_columns"][0]
    assert columns["interval_index"] == 2
    assert columns["response_header_row_index"] == 10
    assert columns["response"]["header"] == "Shear Stress"
    assert columns["response"]["column_index_zero_based"] == 3
    assert columns["control"]["header"] == "Shear Strain"
    assert columns["control"]["column_index_zero_based"] == 5


def test_short_drifting_final_interval_uses_source_boundary_without_thresholds(
    tmp_path: Path,
) -> None:
    source = tmp_path / "short_drifting_interval.csv"
    _write_short_drifting_final_interval_export(source)

    resolved = resolve_stress_relaxation_transform(source)
    series = resolved.series[0]
    diagnostics = dict(series.diagnostics or {})
    contract = resolved.contract.to_payload()
    output_evidence = contract["output"]["series"][0]

    assert tuple(time for time, _response in series.points) == (
        1.0,
        2.0,
        3.0,
        4.0,
    )
    assert tuple(response for _time, response in series.points) == pytest.approx(
        (1.0, 0.875, 0.75, 0.625)
    )
    assert diagnostics["hold_interval_index"] == 2
    assert diagnostics["hold_onset_source_time"] == 1.0
    assert diagnostics["hold_detection_tolerance"] is None
    assert diagnostics["hold_post_onset_maximum_deviation"] == 1.5
    assert output_evidence["source_point_count"] == output_evidence[
        "retained_point_count"
    ] + sum(output_evidence["excluded_by_reason"].values())


def test_final_interval_boundary_still_requires_a_nonzero_response(
    tmp_path: Path,
) -> None:
    source = tmp_path / "zero_boundary_response.csv"
    _write_short_drifting_final_interval_export(source, first_response=0.0)

    with pytest.raises(ValueError, match="final common interval boundary"):
        resolve_stress_relaxation_transform(source)


def test_stress_header_rows_use_raw_coordinates_across_test_blocks(
    tmp_path: Path,
) -> None:
    source = tmp_path / "two_tests.csv"
    source_rows = [
        "Project:\tRelaxation Test",
        *_stress_test_section("E3"),
        "\t\t\t\t",
        *_stress_test_section("E4", response_offset=20.0),
    ]
    source.write_text("\n".join(source_rows) + "\n", encoding="utf-16")

    contract = resolve_stress_relaxation_transform(source).contract.to_payload()

    header_rows = {
        item["sample"]: item["response_header_row_index"]
        for item in contract["source_columns"]
    }
    assert header_rows == {"E3": 4, "E4": 19}
    assert all(
        source_rows[row_index].startswith("Interval data:")
        for row_index in header_rows.values()
    )


def test_stress_transform_classifies_invalid_time_candidates(tmp_path: Path) -> None:
    for suffix, time_cell in (("missing", ""), ("nonfinite", "nan")):
        source = tmp_path / f"{suffix}_time.csv"
        _write_invalid_time_export(source, time_cell)

        resolved = resolve_stress_relaxation_transform(source)
        evidence = resolved.contract.to_payload()["output"]["series"][0]

        assert len(resolved.series[0].points) == 10
        assert evidence["candidate_point_counts"] == {
            "response": 11,
            "aligned": 10,
            "control": 11,
        }
        assert evidence["excluded_by_reason"]["nonfinite_or_missing_time"] == 1
        assert evidence["control_exclusions"]["nonfinite_or_missing_time"] == 1
        assert evidence["source_point_count"] == evidence[
            "retained_point_count"
        ] + sum(evidence["excluded_by_reason"].values())


@pytest.mark.parametrize("blank_before_units", [False, True])
def test_interval_units_follow_explicit_evidence_across_export_layouts(
    tmp_path: Path,
    blank_before_units: bool,
) -> None:
    source = tmp_path / f"unit_layout_{blank_before_units}.csv"
    _write_interval_unit_layout(source, blank_before_units=blank_before_units)

    resolved = resolve_stress_relaxation_transform(source)
    columns = resolved.contract.to_payload()["source_columns"][0]
    diagnostics = dict(resolved.series[0].diagnostics or {})
    interval = diagnostics["transform_source_columns"]["response"]

    assert columns["x"]["unit"] == "s"
    assert columns["response"]["unit"] == "Pa"
    assert columns["control"]["unit"] == "%"
    assert resolved.series[0].points[0] == (0.01, 1.0)
    assert interval["x_unit_row_index"] == (5 if blank_before_units else 4)
    assert interval["y_unit_row_index"] == (5 if blank_before_units else 4)


@pytest.mark.parametrize("unit_rows", [[], ["\t\t[min]\t[%]\t[Pa]"]])
def test_interval_units_fail_closed_when_missing_or_ambiguous(
    tmp_path: Path,
    unit_rows: list[str],
) -> None:
    source = tmp_path / f"invalid_units_{len(unit_rows)}.csv"
    rows = [
        "Test:\tinvalid_units",
        "Result:\tStress Relaxation 1",
        "Interval and data points:\t1\t3",
        "Interval data:\tPoint No.\tTime\tShear Strain\tShear Stress",
    ]
    if unit_rows:
        rows.append("\t\t[s]\t[%]\t[Pa]")
        rows.extend(unit_rows)
    rows.extend(
        [
            "\t1\t0.01\t5\t100",
            "\t2\t0.02\t5\t90",
            "\t3\t0.03\t5\t80",
        ]
    )
    source.write_text("\n".join(rows) + "\n", encoding="utf-16")

    expected = "missing" if not unit_rows else "ambiguous"
    with pytest.raises(ValueError, match=expected):
        resolve_stress_relaxation_transform(source)


@pytest.mark.parametrize(
    ("units", "unsupported", "expected"),
    [
        (("min", "%", "Pa"), "min", "s"),
        (("s", "%", "kPa"), "kPa", "Pa"),
    ],
)
def test_interval_units_reject_values_that_need_conversion(
    tmp_path: Path,
    units: tuple[str, str, str],
    unsupported: str,
    expected: str,
) -> None:
    source = tmp_path / f"unsupported_{unsupported}.csv"
    time_unit, control_unit, response_unit = units
    source.write_text(
        "\n".join(
            [
                "Test:\tunsupported_unit",
                "Result:\tStress Relaxation 1",
                "Interval and data points:\t1\t3",
                "Interval data:\tPoint No.\tTime\tShear Strain\tShear Stress",
                f"\t\t[{time_unit}]\t[{control_unit}]\t[{response_unit}]",
                "\t1\t0.01\t5\t100",
                "\t2\t0.02\t5\t90",
                "\t3\t0.03\t5\t80",
            ]
        )
        + "\n",
        encoding="utf-16",
    )

    with pytest.raises(
        ValueError,
        match=rf"{unsupported!r}.*identity-equivalent {expected!r}",
    ):
        resolve_stress_relaxation_transform(source)


def test_creep_interval_accepts_identity_equivalent_solidus_unit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "creep.csv"
    source.write_text(
        "\n".join(
            [
                "Test:\tcreep_sample",
                "Result:\tCreep 1",
                "Interval and data points:\t1\t2",
                "Interval data:\tPoint No.\tTime\tCreep Compliance",
                "\t\t[s]\t1/Pa",
                "\t1\t0.01\t0.000001",
                "\t2\t0.02\t0.000002",
            ]
        )
        + "\n",
        encoding="utf-16",
    )

    series = _read_rheology_interval_series(
        source,
        y_candidates=("creepcompliance",),
        y_label="Creep compliance",
        y_unit="1/Pa",
    )

    assert (series.x_unit, series.y_unit) == ("s", "Pa⁻¹")
    assert series.points[0] == (0.01, 0.000001)


def test_plain_wide_stress_source_retains_the_non_interval_fallback(
    tmp_path: Path,
) -> None:
    source = tmp_path / "wide_stress.csv"
    source.write_text(
        "Time,Shear Stress\ns,Pa\nwide,wide\n0.01,100\n0.02,90\n",
        encoding="utf-8",
    )

    resolved = resolve_stress_relaxation_transform(source)

    assert resolved.series[0].points == ((0.01, 1.0), (0.02, 0.9))
    assert resolved.series[0].x_unit == "s"


def test_wide_transform_finds_a_retained_anchor_beyond_the_first_point(
    tmp_path: Path,
) -> None:
    source = tmp_path / "wide.csv"
    source.write_text(
        "Time,Shear Stress\ns,Pa\nE0,E0\n0.1,0\n0.2,10\n0.3,5\n",
        encoding="utf-8",
    )

    contract = resolve_stress_relaxation_transform(source).contract.to_payload()

    anchor = contract["anchor"]["selections"][0]
    assert anchor["source_time"] == 0.2
    assert anchor["retained"] is True
    assert anchor["output_point"] == [0.2, 1.0]
    assert contract["output"]["series"][0]["first_point"] == [0.1, 0.0]


def test_already_normalized_source_marks_anchor_not_applicable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "normalized.csv"
    source.write_text(
        "Time,Normalized Stress\ns,1\nE0,E0\n0.1,1\n0.2,0.8\n0.3,0.6\n",
        encoding="utf-8",
    )

    contract = resolve_stress_relaxation_transform(source).contract.to_payload()

    assert contract["retain_anchor"] is None
    assert contract["anchor"]["selections"] == [
        {
            "sample": "normalized",
            "selector": "none_source_already_normalized",
            "applicable": False,
            "retained": None,
        }
    ]


def test_resolved_stress_snapshot_materializes_without_a_second_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "relaxation"
    source.mkdir()
    _write_relaxation_export(source / "instrument_export.csv")
    resolved = resolve_scientific_source(
        source,
        rule_id="rheology_stress_relaxation",
        request={"series_order": ["E3"]},
        template="curve",
    )
    assert resolved is not None

    import sciplot_core.semantic_sources.prepare_rheology as preparation

    monkeypatch.setattr(
        preparation,
        "resolve_stress_relaxation_transform",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("semantic preparation reparsed the source")
        ),
    )
    prepared = prepare_semantic_source(
        source,
        output_dir=tmp_path / "prepared_once",
        semantic={
            "semantic_family": "rheology_stress_relaxation",
            "rule_id": "rheology_stress_relaxation",
        },
        series_order=["E3"],
        resolved_scientific_source=resolved,
    )

    assert prepared["transform_steps"][0]["parameters"][
        "scientific_transform"
    ] == resolved.transform.contract.to_payload()
