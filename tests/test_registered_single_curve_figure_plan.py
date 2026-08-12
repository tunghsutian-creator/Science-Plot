from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
import pandas as pd

import sciplot_core.figure_plan.single_curve_resolution as single_curve_resolution
import sciplot_core.figure_plan.source_binding as source_binding
import sciplot_core.semantic_sources.prepare_curve_families as prepare_curve_families
import sciplot_core.workflow.auto_split as auto_split
from sciplot_core.semantic_sources import (
    ftir_sources,
    gpc_sources,
    registered_paired_curve_transform as paired_curve_transform,
)
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    REQUIRED_FIGURE_PLAN_RULE_IDS,
    ResolvedFigurePlan,
    resolve_figure_plan,
)
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources.scientific_source import (
    ScientificSourceResolutionError,
    resolve_scientific_source,
)
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.studio_core.figure_task_evidence import (
    generic_figure_queue_from_plan,
)
from sciplot_core.source_tables import slugify_canonical_label, slugify_label


RULE_IDS = (
    "dsc_curve",
    "tga_curve",
    "dtg_curve",
    "uvvis_spectrum",
    "xrd_pattern",
)
REGISTERED_METRIC_IDS = {
    "dsc_curve": ("temperature", "heat_flow"),
    "tga_curve": ("temperature", "mass"),
    "dtg_curve": ("temperature", "derivative_mass"),
    "uvvis_spectrum": ("wavelength", "absorbance"),
    "xrd_pattern": ("diffraction_angle", "intensity"),
    "saxs_profile": ("q", "intensity"),
    "dma_frequency_sweep": ("angular_frequency", "storage_modulus"),
}
REGISTERED_RULE_IDS = tuple(REGISTERED_METRIC_IDS)


@dataclass(frozen=True, slots=True)
class FixtureSeries:
    sample: str
    x_header: str
    y_header: str
    x_unit: str
    y_unit: str
    points: tuple[tuple[float, float], ...]


def _fixture(rule_id: str) -> Path:
    source = resolve_fixture_path(str(get_rule(rule_id).fixture_path or ""))
    assert source.is_file()
    return source


def _fixture_rows(rule_id: str) -> list[list[str]]:
    with _fixture(rule_id).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert len(rows) > 3
    return rows


def _fixture_series(rule_id: str) -> tuple[FixtureSeries, ...]:
    rows = _fixture_rows(rule_id)
    headers, units, samples = rows[:3]
    assert len(headers) % 2 == 0
    assert len(units) == len(headers)
    assert len(samples) == len(headers)
    return tuple(
        FixtureSeries(
            sample=samples[x_index],
            x_header=headers[x_index],
            y_header=headers[x_index + 1],
            x_unit=units[x_index],
            y_unit=units[x_index + 1],
            points=tuple(
                (float(row[x_index]), float(row[x_index + 1]))
                for row in rows[3:]
                if row[x_index] and row[x_index + 1]
            ),
        )
        for x_index in range(0, len(headers), 2)
    )


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_registered_paired_curve_single_member_directory_matches_file(
    tmp_path: Path,
    rule_id: str,
) -> None:
    rule = get_rule(rule_id)
    source_dir = tmp_path / "source"
    member = source_dir / "nested" / _fixture(rule_id).name
    member.parent.mkdir(parents=True)
    shutil.copy2(_fixture(rule_id), member)

    from_file = paired_curve_transform.resolve_registered_paired_curve_transform(
        member,
        rule=rule,
    )
    from_directory = paired_curve_transform.resolve_registered_paired_curve_transform(
        source_dir,
        rule=rule,
    )

    assert from_directory == from_file
    assert from_directory.selected_sources == (member.resolve(),)


@pytest.mark.parametrize("member_count", (0, 2))
def test_registered_paired_curve_directory_requires_exactly_one_supported_file(
    tmp_path: Path,
    member_count: int,
) -> None:
    rule = get_rule("uvvis_spectrum")
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for index in range(member_count):
        member = source_dir / str(index) / f"spectrum_{index}.csv"
        member.parent.mkdir()
        shutil.copy2(_fixture(rule.rule_id), member)

    with pytest.raises(ValueError) as error:
        paired_curve_transform.resolve_registered_paired_curve_transform(
            source_dir,
            rule=rule,
        )

    assert str(error.value) == (
        f"{rule.rule_id} paired-curve transform requires exactly one supported "
        f"source file in {source_dir.resolve()}; found {member_count}."
    )


def test_registered_paired_curve_reads_real_saxs_header_metadata_and_projects_log_y() -> None:
    rule = get_rule("saxs_profile")
    assert (rule.x_axis.scale, rule.y_axis.scale) == ("linear", "log")
    source = resolve_fixture_path(str(rule.fixture_path or ""))
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    sample_row, header_row = rows[:2]
    column_pairs = tuple(range(0, len(header_row), 2))
    assert len(column_pairs) == 5
    expected_samples = tuple(sample_row[x_index] for x_index in column_pairs)
    source_points = tuple(
        tuple(
            (float(row[x_index]), float(row[x_index + 1]))
            for row in rows[2:]
            if row[x_index] and row[x_index + 1]
        )
        for x_index in column_pairs
    )
    expected_excluded_y = tuple(
        sum(y_value <= 0.0 for _x_value, y_value in points)
        for points in source_points
    )
    expected_retained = tuple(
        tuple(point for point in points if point[1] > 0.0) for points in source_points
    )

    resolved = paired_curve_transform.resolve_registered_paired_curve_transform(
        source,
        rule=rule,
    )
    contract = resolved.contract.to_payload()

    assert resolved.selected_sources == (source,)
    assert contract["selected_sources"] == [str(source)]
    assert len(resolved.series) == len(column_pairs)
    assert tuple(series.sample for series in resolved.series) == expected_samples
    assert contract["output"]["series_order"] == list(expected_samples)
    for index, (series, x_index, all_points, retained, excluded_y) in enumerate(
        zip(
            resolved.series,
            column_pairs,
            source_points,
            expected_retained,
            expected_excluded_y,
            strict=True,
        )
    ):
        diagnostics = dict(series.diagnostics or {})
        evidence = contract["output"]["series"][index]
        columns = contract["source_columns"][index]
        assert series.points == retained
        assert diagnostics["source_sample_detection"] == (
            "detected_from_preceding_sample_row"
        )
        assert diagnostics["source_sample_row_index"] == 0
        assert diagnostics["source_sample_value"] == expected_samples[index]
        assert diagnostics["source_x_unit_detection"] == "detected_from_header"
        assert diagnostics["source_y_unit_detection"] == "detected_from_header"
        assert diagnostics["source_x_unit_detection_value"] == "nm-1"
        assert diagnostics["source_y_unit_detection_value"] == "a.u."
        assert diagnostics["excluded_nonpositive_log_y_count"] == excluded_y
        assert diagnostics["retained_values_preserved_without_numeric_transform"]
        assert columns["x"]["header"] == header_row[x_index]
        assert columns["response"]["header"] == header_row[x_index + 1]
        assert columns["x"]["unit_detection"] == {
            "method": "detected_from_header",
            "row_index_zero_based": 1,
            "value": "nm-1",
        }
        assert columns["response"]["unit_detection"] == {
            "method": "detected_from_header",
            "row_index_zero_based": 1,
            "value": "a.u.",
        }
        assert evidence["candidate_row_count"] == len(all_points)
        assert evidence["retained_point_count"] == len(retained)
        assert evidence["excluded_point_count"] == excluded_y
        assert evidence["excluded_by_reason"] == {
            "empty_pair": 0,
            "partial_or_nonnumeric": 0,
            "nonfinite": 0,
            "nonpositive_log_y": excluded_y,
        }
        assert evidence["candidate_row_count"] == evidence[
            "retained_point_count"
        ] + sum(evidence["excluded_by_reason"].values())
    assert contract["normalizer"]["operation"] == "none"
    assert contract["x_coordinate_policy"]["sorting_applied"] is False
    assert contract["x_coordinate_policy"]["interpolation_applied"] is False
    assert all(
        conversion["source_to_canonical"] == {"factor": 1.0, "offset": 0.0}
        and conversion["canonical_to_display"]
        == {"factor": 1.0, "offset": 0.0}
        for conversion in contract["unit_conversions"]
    )


def test_registered_paired_curve_keeps_zero_on_a_linear_x_axis(
    tmp_path: Path,
) -> None:
    source = tmp_path / "linear_x_log_y.csv"
    source.write_text(
        "Series A,\n"
        "q (nm-1),Log intensity (a.u.)\n"
        "0,5\n"
        "1,0\n"
        "2,4\n",
        encoding="utf-8",
    )

    resolved = paired_curve_transform.resolve_registered_paired_curve_transform(
        source,
        rule=get_rule("saxs_profile"),
    )

    series = resolved.series[0]
    diagnostics = dict(series.diagnostics or {})
    assert series.points == ((0.0, 5.0), (2.0, 4.0))
    assert "excluded_nonpositive_log_x_count" not in diagnostics
    assert diagnostics["excluded_nonpositive_log_y_count"] == 1


def test_registered_paired_curve_rejects_a_disconnected_later_numeric_block(
    tmp_path: Path,
) -> None:
    source = tmp_path / "disconnected.csv"
    source.write_text(
        "Wavelength (nm),Absorbance (a.u.)\n"
        "400,1\n"
        "\n"
        "500,2\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as error:
        paired_curve_transform.resolve_registered_paired_curve_transform(
            source,
            rule=get_rule("uvvis_spectrum"),
        )

    assert str(error.value) == "Selected paired-curve data block is disconnected."


def test_registered_paired_curve_uses_only_main_block_for_decimal_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "comma_block.csv"
    source.write_text(
        "Wavelength (nm);Absorbance (a.u.)\n"
        "400,0;1,2\n"
        "500,0;2,4\n"
        ";\n"
        "footer;1.2\n"
        "footer;1,2,3\n",
        encoding="utf-8",
    )

    resolved = paired_curve_transform.resolve_registered_paired_curve_transform(
        source,
        rule=get_rule("uvvis_spectrum"),
    )

    assert resolved.series[0].points == ((400.0, 1.2), (500.0, 2.4))
    evidence = resolved.contract.to_payload()["output"]["series"][0]
    assert evidence["candidate_row_count"] == 2
    assert evidence["excluded_by_reason"] == {
        "empty_pair": 0,
        "partial_or_nonnumeric": 0,
        "nonfinite": 0,
    }


def test_registered_paired_curve_keeps_in_block_nonfinite_evidence_for_validation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "nonfinite.csv"
    source.write_text(
        "Wavelength (nm),Absorbance (a.u.)\n"
        "400,1\n"
        "500,nan\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source contains nonfinite values"):
        paired_curve_transform.resolve_registered_paired_curve_transform(
            source,
            rule=get_rule("uvvis_spectrum"),
        )


def test_registered_paired_curve_keeps_scanning_when_another_pair_is_active(
    tmp_path: Path,
) -> None:
    source = tmp_path / "shorter_pair.csv"
    source.write_text(
        "Wavelength (nm),Absorbance (a.u.),Wavelength (nm),Absorbance (a.u.)\n"
        "400,1,400,10\n"
        "500,2,500,11\n"
        ",,600,12\n",
        encoding="utf-8",
    )

    resolved = paired_curve_transform.resolve_registered_paired_curve_transform(
        source,
        rule=get_rule("uvvis_spectrum"),
    )

    assert tuple(series.points for series in resolved.series) == (
        ((400.0, 1.0), (500.0, 2.0)),
        ((400.0, 10.0), (500.0, 11.0), (600.0, 12.0)),
    )
    first_evidence = resolved.contract.to_payload()["output"]["series"][0]
    assert first_evidence["candidate_row_count"] == 3
    assert first_evidence["excluded_by_reason"]["empty_pair"] == 1


def test_registered_paired_curve_log_projection_uses_mutually_exclusive_axis_reasons(
    tmp_path: Path,
) -> None:
    source = tmp_path / "two_log_axes.csv"
    source.write_text(
        "Declared sample,\n"
        "q (nm-1),Intensity (a.u.)\n"
        "-1,-2\n"
        "1,-3\n"
        "-2,4\n"
        "2,5\n"
        "0,6\n"
        "3,0\n"
        "4,7\n",
        encoding="utf-8",
    )
    registered_rule = get_rule("saxs_profile")
    rule = replace(
        registered_rule,
        x_axis=replace(registered_rule.x_axis, scale="log"),
        y_axis=replace(registered_rule.y_axis, scale="log"),
    )

    resolved = paired_curve_transform.resolve_registered_paired_curve_transform(
        source,
        rule=rule,
    )
    series = resolved.series[0]
    evidence = resolved.contract.to_payload()["output"]["series"][0]

    assert resolved.selected_sources == (source,)
    assert series.points == ((2.0, 5.0), (4.0, 7.0))
    assert evidence["candidate_row_count"] == 7
    assert evidence["retained_point_count"] == 2
    assert evidence["excluded_by_reason"] == {
        "empty_pair": 0,
        "partial_or_nonnumeric": 0,
        "nonfinite": 0,
        "nonpositive_log_x": 3,
        "nonpositive_log_y": 2,
    }
    assert evidence["candidate_row_count"] == evidence[
        "retained_point_count"
    ] + sum(evidence["excluded_by_reason"].values())


def test_uvvis_response_identity_is_bound_to_source_evidence() -> None:
    rule = get_rule("uvvis_spectrum")
    provenance = json.loads(
        (_fixture(rule.rule_id).parent / "source_provenance.json").read_text(
            encoding="utf-8"
        )
    )
    response_identity = provenance["response_identity"]

    assert response_identity["quantity"] == rule.y_axis.canonical_label
    assert response_identity["source_header"] == provenance["source_columns"]["y"][
        "header"
    ]
    assert response_identity["not_inferred_from_unit"] is True
    assert {item["kind"] for item in response_identity["evidence"]} == {
        "associated_publication_figure_axis",
    }
    assert all(item["source"] for item in response_identity["evidence"])
    assert provenance["source_units"]["y"] is None
    assert provenance["unit_identity"]["y"]["source_unit_explicit"] is False
    assert provenance["unit_identity"]["y"]["output_unit"] == (
        rule.y_axis.canonical_unit
    )


def test_xrd_rule_uses_the_official_si_axis_identity_and_valid_metric() -> None:
    rule = get_rule("xrd_pattern")

    assert rule.x_axis.canonical_label == "Diffraction angle"
    assert rule.x_axis.display_label == "Diffraction angle (°)"
    assert rule.y_axis.canonical_unit == "a.u."
    assert rule.y_axis.display_label == "Intensity (a.u.)"
    assert rule.analysis[0].required_inputs == (
        "diffraction_angle",
        "intensity",
    )


def test_xrd_output_identity_is_bound_to_the_official_si_axes() -> None:
    rule = get_rule("xrd_pattern")
    provenance = json.loads(
        (_fixture(rule.rule_id).parent / "source_provenance.json").read_text(
            encoding="utf-8"
        )
    )

    assert provenance["source_units"] == {"x": None, "y": None}
    assert provenance["coordinate_identity"]["quantity"] == (
        rule.x_axis.canonical_label
    )
    assert provenance["response_identity"]["quantity"] == (
        rule.y_axis.canonical_label
    )
    assert provenance["unit_identity"]["x"]["evidence"]["axis_label"] == (
        rule.x_axis.display_label
    )
    assert provenance["unit_identity"]["y"]["evidence"]["axis_label"] == (
        rule.y_axis.display_label
    )
    assert provenance["output_units"] == {
        "x": rule.x_axis.canonical_unit,
        "y": rule.y_axis.canonical_unit,
    }


def _write_panalytical_xrd_export(
    path: Path,
    *,
    declared_point_count: int = 3,
) -> Path:
    path.write_text(
        "[Measurement conditions]\n"
        "Sample identification,\n"
        'Comment - 2,"Goniometer=Theta/Theta; Minimum step size '
        '2Theta:0.0001, detector=PIXcel"\n'
        "Scan axis,Gonio\n"
        "Scan range,5.0,6.0\n"
        "Scan step size,0.5\n"
        f"No. of points,{declared_point_count}\n"
        "Scan type,CONTINUOUS\n"
        "[Scan points]\n"
        "Angle, TimePerStep, Intensity, ESD\n"
        "5.0, 35.190, 4.0, 2.0\n"
        "5.5, 35.190, 9.0, 3.0\n"
        "6.0, 35.190, 1.0, 1.0\n",
        encoding="utf-8",
    )
    return path


def test_xrd_reads_panalytical_scan_points_with_schema_units_and_counts(
    tmp_path: Path,
) -> None:
    source = _write_panalytical_xrd_export(tmp_path / "PEBA__PEBA.csv")
    rule = get_rule("xrd_pattern")

    resolved = paired_curve_transform.resolve_registered_paired_curve_transform(
        source,
        rule=rule,
    )
    series = resolved.series[0]
    diagnostics = dict(series.diagnostics or {})
    contract = resolved.contract.to_payload()

    assert series.sample == "PEBA"
    assert series.points == ((5.0, 4.0), (5.5, 9.0), (6.0, 1.0))
    assert (series.x_unit, series.y_unit) == ("degree", "a.u.")
    assert diagnostics["source_instrument_format"] == (
        "panalytical_data_collector_scan_points"
    )
    assert diagnostics["source_declared_point_count"] == 3
    assert diagnostics["source_point_count_match"] is True
    assert diagnostics["source_x_unit_detection"] == (
        "detected_from_instrument_export_schema"
    )
    assert diagnostics["source_y_unit_detection_value"] == "counts"
    assert diagnostics["source_y_display_policy"] == (
        "raw_detector_counts_presented_as_arbitrary_intensity"
    )
    assert diagnostics["source_y_numeric_scaling_applied"] is False
    assert diagnostics["source_y_values_preserved"] is True
    assert contract["output"]["x_unit"] == "degree"
    assert contract["output"]["y_unit"] == "a.u."
    assert contract["normalizer"] == {
        "scope": "none",
        "operation": "none",
        "output_metric": "intensity",
        "output_unit": "a.u.",
    }
    assert contract["unit_conversions"][1]["source_unit"] == "counts"
    assert contract["unit_conversions"][1]["canonical_unit"] == "a.u."

    scientific_source = resolve_scientific_source(
        source,
        rule_id=rule.rule_id,
        request={"template": "curve"},
        template="curve",
    )
    assert scientific_source is not None
    assert scientific_source.transform is not None
    assert scientific_source.transform.contract.output["y_unit"] == "a.u."


def test_xrd_rejects_panalytical_scan_point_count_mismatch(tmp_path: Path) -> None:
    source = _write_panalytical_xrd_export(
        tmp_path / "mismatch.csv",
        declared_point_count=4,
    )

    with pytest.raises(ValueError, match="declared 4, found 3 rows and 3 finite pairs"):
        paired_curve_transform.resolve_registered_paired_curve_transform(
            source,
            rule=get_rule("xrd_pattern"),
        )


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_registered_paired_curve_transform_and_plan_share_one_source_snapshot(
    rule_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_rule = get_rule(rule_id)
    fixture = _fixture(rule_id)
    expected_series = _fixture_series(rule_id)
    transform_calls: list[tuple[Path, str]] = []
    hash_calls: list[Path] = []
    plan_snapshots: list[ResolvedScientificTransform] = []
    real_transform = paired_curve_transform.resolve_registered_paired_curve_transform
    real_hash = source_binding.source_tree_sha256
    real_plan = single_curve_resolution.resolve_registered_single_curve_plan

    def counted_transform(
        source: Path,
        *,
        rule: Any,
        series_order: object = None,
    ) -> ResolvedScientificTransform:
        transform_calls.append((source, rule.rule_id))
        return real_transform(source, rule=rule, series_order=series_order)

    def counted_hash(source: Path | None) -> str | None:
        assert source is not None
        hash_calls.append(source)
        return real_hash(source)

    def captured_plan(
        *,
        rule_id: str,
        request: dict[str, Any],
        source_resolution: ResolvedScientificTransform,
        source_sha256: str,
    ) -> ResolvedFigurePlan:
        plan_snapshots.append(source_resolution)
        return real_plan(
            rule_id=rule_id,
            request=request,
            source_resolution=source_resolution,
            source_sha256=source_sha256,
        )

    monkeypatch.setattr(
        paired_curve_transform,
        "resolve_registered_paired_curve_transform",
        counted_transform,
    )
    monkeypatch.setattr(source_binding, "source_tree_sha256", counted_hash)
    monkeypatch.setattr(
        single_curve_resolution,
        "resolve_registered_single_curve_plan",
        captured_plan,
    )

    resolved = resolve_scientific_source(
        fixture,
        rule_id=rule_id,
        request={},
        template=selected_rule.template,
    )

    assert resolved is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    assert transform_calls == [(fixture, rule_id)]
    assert hash_calls == [fixture, fixture]
    assert len(plan_snapshots) == 1
    assert plan_snapshots[0] is transform
    assert transform.selected_sources == (fixture,)
    assert len(transform.series) == len(expected_series)
    for series, expected in zip(transform.series, expected_series, strict=True):
        assert series.sample == expected.sample
        assert (series.x_label, series.y_label) == (
            selected_rule.x_axis.canonical_label,
            selected_rule.y_axis.canonical_label,
        )
        assert (series.x_unit, series.y_unit) == (
            selected_rule.x_axis.canonical_unit,
            selected_rule.y_axis.canonical_unit,
        )
        diagnostics = dict(series.diagnostics or {})
        assert diagnostics["source_x_unit_detection_value"] == expected.x_unit
        assert diagnostics["source_y_unit_detection_value"] == expected.y_unit
        assert series.points == expected.points

    plan = resolved.figure_plan
    assert plan is not None
    assert plan.source_sha256 == resolved.source_sha256
    x_metric = str(transform.contract.output["x_metric"])
    y_metric = str(transform.contract.output["y_metric"])
    figure_id = f"{rule_id.removesuffix('_curve')}_{y_metric}_vs_{x_metric}"
    assert plan.selected_figure_ids == (figure_id,)
    assert plan.tasks[0].sample_order == tuple(
        expected.sample for expected in expected_series
    )
    assert plan.tasks[0].metric_binding == CartesianMetricBinding(
        x_metric=x_metric,
        y_metric=y_metric,
    )


@pytest.mark.parametrize("rule_id", REGISTERED_RULE_IDS)
def test_registered_paired_curve_uses_the_shared_plan_adapter(rule_id: str) -> None:
    rule = get_rule(rule_id)

    assert rule_id in REQUIRED_FIGURE_PLAN_RULE_IDS
    assert rule.scientific_source_adapter == "registered_paired_curve"
    assert rule.figure_plan_adapter == "registered_single_curve"
    plan = resolve_figure_plan(
        rule_id=rule_id,
        template=rule.template,
        study_model={},
        input_path=_fixture(rule_id),
        request={"template": rule.template},
    )
    assert plan is not None
    assert plan.rule_id == rule_id
    assert len(plan.tasks) == 1
    x_metric, y_metric = REGISTERED_METRIC_IDS[rule_id]
    task = plan.tasks[0]
    assert task.metric_binding == CartesianMetricBinding(
        x_metric=x_metric,
        y_metric=y_metric,
    )
    family_stem = rule_id.removesuffix("_curve")
    assert task.figure_id == f"{family_stem}_{y_metric}_vs_{x_metric}"


def test_canonical_metric_ids_do_not_change_presentation_slug_aliases() -> None:
    assert slugify_label("Angular frequency") == "omega"
    assert slugify_label("Storage modulus") == "g"
    assert slugify_canonical_label("Angular frequency") == "angular_frequency"
    assert slugify_canonical_label("Storage modulus") == "storage_modulus"


def test_dma_frequency_real_source_reuses_one_generic_single_curve_spine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = get_rule("dma_frequency_sweep")
    fixture = _fixture(rule.rule_id)
    expected_series = _fixture_series(rule.rule_id)
    assert expected_series

    resolved = resolve_scientific_source(
        fixture,
        rule_id=rule.rule_id,
        request={},
        template=rule.template,
    )

    assert resolved is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    assert rule.scientific_source_adapter == "registered_paired_curve"
    assert rule.figure_plan_adapter == "registered_single_curve"
    assert rule.preparation_adapter == "curve_family"
    assert rule.render_adapter == "generic"
    assert transform.selected_sources == (fixture,)
    assert transform.contract.output["x_metric"] == "angular_frequency"
    assert transform.contract.output["y_metric"] == "storage_modulus"
    assert transform.contract.output["series_order"] == [
        series.sample for series in expected_series
    ]
    assert tuple(series.points for series in transform.series) == tuple(
        series.points for series in expected_series
    )

    plan = resolved.figure_plan
    assert plan is not None
    assert plan.source_sha256 == resolved.source_sha256
    assert plan.selection_policy == "registered_single_curve"
    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.figure_id == (
        "dma_frequency_sweep_storage_modulus_vs_angular_frequency"
    )
    assert task.metric_binding == CartesianMetricBinding(
        x_metric="angular_frequency",
        y_metric="storage_modulus",
    )
    assert task.sample_order == tuple(
        series.sample for series in expected_series
    )

    monkeypatch.setattr(
        prepare_curve_families,
        "resolve_single_curve_transform",
        lambda *_args, **_kwargs: pytest.fail(
            "DMA frequency preparation resolved its source snapshot twice"
        ),
    )
    prepared = prepare_semantic_source(
        fixture,
        output_dir=tmp_path / "prepared",
        semantic={"rule_id": rule.rule_id, "semantic_family": rule.semantic_family},
        resolved_scientific_source=resolved,
    )
    step = prepared["transform_steps"][0]
    assert step["operation"] == (
        "extract_angular_frequency_storage_modulus_curve"
    )
    assert step["parameters"]["scientific_transform"] == (
        transform.contract.to_payload()
    )

    bundle_calls: list[dict[str, Any]] = []

    def render_bundle(input_path: Path, **kwargs: Any) -> dict[str, Any]:
        bundle_calls.append({"input_path": input_path, **kwargs})
        return {"kind": "generic_single_task_result"}

    monkeypatch.setattr(
        auto_split,
        "render_selected_single_task_bundle",
        render_bundle,
    )
    monkeypatch.setattr(
        auto_split,
        "render_to_dir",
        lambda *_args, **_kwargs: pytest.fail(
            "DMA frequency FigurePlan fell back to unplanned rendering"
        ),
    )
    prepared_source = Path(str(prepared["source"]))
    result = auto_split._render_with_auto_split(
        prepared_source,
        template=rule.template,
        output_dir=tmp_path / "workflow",
        options={},
        export_formats=("pdf",),
        request={"rule_id": rule.rule_id},
        _terminal_source_prepared=True,
        _resolved_scientific_source=resolved,
        _resolved_figure_plan=plan,
    )
    assert result == {"kind": "generic_single_task_result"}
    assert len(bundle_calls) == 1
    assert bundle_calls[0]["input_path"] == prepared_source
    assert bundle_calls[0]["plan"] is plan
    assert bundle_calls[0]["task"] is task
    assert bundle_calls[0]["terminal_source_prepared"] is True

    queue = generic_figure_queue_from_plan(
        plan,
        render_adapter=rule.render_adapter,
    )
    assert [item["id"] for item in queue] == [task.figure_id]
    assert queue[0]["resolved_figure_task"] == task.to_payload()


@pytest.mark.parametrize("file_kind", ("csv", "xlsx"))
def test_dsc_registered_source_accepts_arbitrary_paired_tables_without_provenance(
    tmp_path: Path,
    file_kind: str,
) -> None:
    rule = get_rule("dsc_curve")
    rows: list[list[object]] = [
        ["Temperature", "Heat flow", "Temperature", "Heat flow"],
        ["°C", "W/g", "°C", "W/g"],
        ["Later source series", "Later source series", "First", "First"],
        [20.0, 0.2, 30.0, -0.1],
        [21.0, 0.1, 31.0, -0.2],
        [22.0, 0.0, None, None],
    ]
    source = tmp_path / f"arbitrary_dsc.{file_kind}"
    if file_kind == "csv":
        with source.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(rows)
    else:
        pd.DataFrame(rows).to_excel(source, header=False, index=False)

    resolved = resolve_scientific_source(
        source,
        rule_id=rule.rule_id,
        request={"series_order": ["First", "Later source series"]},
        template=rule.template,
    )

    assert resolved is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    assert transform.selected_sources == (source.resolve(),)
    assert tuple(series.sample for series in transform.series) == (
        "First",
        "Later source series",
    )
    assert tuple(len(series.points) for series in transform.series) == (2, 3)
    assert transform.contract.output["explicit_series_order_applied"] is True
    assert resolved.figure_plan is not None
    assert resolved.figure_plan.tasks[0].sample_order == (
        "First",
        "Later source series",
    )


@pytest.mark.parametrize("sample", ("A", "Pa", "s"))
@pytest.mark.parametrize("metadata_order", ("unit_then_sample", "sample_then_unit"))
def test_registered_pair_roles_preserve_unit_shaped_adjacent_sample_identity(
    tmp_path: Path,
    sample: str,
    metadata_order: str,
) -> None:
    source = tmp_path / f"{metadata_order}_{sample}.csv"
    unit_row = ["°C", "W/g"]
    sample_row = [sample, sample]
    metadata_rows = (
        [unit_row, sample_row]
        if metadata_order == "unit_then_sample"
        else [sample_row, unit_row]
    )
    with source.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(
            [
                ["Temperature", "Heat flow"],
                *metadata_rows,
                [20.0, 0.1],
                [21.0, 0.2],
            ]
        )

    resolved = resolve_scientific_source(
        source,
        rule_id="dsc_curve",
        request={},
        template="curve",
    )

    assert resolved is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    assert tuple(series.sample for series in transform.series) == (sample,)
    assert transform.series[0].diagnostics["source_sample_detection"] == (
        "detected_from_adjacent_sample_row"
    )
    assert resolved.figure_plan is not None
    assert resolved.figure_plan.tasks[0].sample_order == (sample,)


def test_registered_pair_roles_preserve_unit_shaped_preceding_sample_identity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "preceding_sample.csv"
    source.write_text(
        "Pa,\n"
        "Temperature (°C),Heat flow (W/g)\n"
        "20,0.1\n"
        "21,0.2\n",
        encoding="utf-8",
    )

    resolved = resolve_scientific_source(
        source,
        rule_id="dsc_curve",
        request={},
        template="curve",
    )

    assert resolved is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    assert tuple(series.sample for series in transform.series) == ("Pa",)
    assert transform.series[0].diagnostics["source_sample_detection"] == (
        "detected_from_preceding_sample_row"
    )
    assert resolved.figure_plan is not None
    assert resolved.figure_plan.tasks[0].sample_order == ("Pa",)


def test_registered_pair_roles_fall_back_only_without_structural_sample_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "no_declared_sample.csv"
    source.write_text(
        "Temperature,Heat flow\n"
        "°C,W/g\n"
        "20,0.1\n"
        "21,0.2\n",
        encoding="utf-8",
    )

    resolved = resolve_scientific_source(
        source,
        rule_id="dsc_curve",
        request={},
        template="curve",
    )

    assert resolved is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    assert tuple(series.sample for series in transform.series) == (source.stem,)
    assert transform.series[0].diagnostics["source_sample_detection"] == (
        "fallback_from_source_table"
    )
    assert resolved.figure_plan is not None
    assert resolved.figure_plan.tasks[0].sample_order == (source.stem,)


def test_registered_pair_roles_reject_ambiguous_unit_shaped_rows(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ambiguous_roles.csv"
    source.write_text(
        "Temperature,Heat flow\n"
        "A,A\n"
        "Pa,Pa\n"
        "20,0.1\n"
        "21,0.2\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Ambiguous adjacent paired-curve unit/sample row roles",
    ):
        paired_curve_transform.resolve_registered_paired_curve_transform(
            source,
            rule=get_rule("dsc_curve"),
        )


def test_dsc_registered_source_rejects_ambiguous_workbook_sheets(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ambiguous_cycle.xlsx"
    rows = [
        ["Temperature", "Heat flow"],
        ["°C", "W/g"],
        ["Source series", "Source series"],
        [20.0, 0.1],
        [21.0, 0.2],
    ]
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame(rows).to_excel(
            writer,
            sheet_name="Cooling",
            header=False,
            index=False,
        )
        pd.DataFrame(rows).to_excel(
            writer,
            sheet_name="Heating",
            header=False,
            index=False,
        )

    with pytest.raises(ScientificSourceResolutionError) as error:
        resolve_scientific_source(
            source,
            rule_id="dsc_curve",
            request={},
            template="curve",
        )

    assert error.value.reason_code == "dsc_curve_transform_invalid"
    assert "More than one source table" in str(error.value)


def test_ftir_headerless_source_shares_one_neutral_snapshot_for_plan_and_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = get_rule("ftir_spectrum")
    source = _fixture(rule.rule_id)
    transform_calls: list[tuple[Path, object]] = []
    plan_snapshots: list[ResolvedScientificTransform] = []
    real_transform = ftir_sources.resolve_ftir_scientific_transform
    real_plan = single_curve_resolution.resolve_registered_single_curve_plan

    def counted_transform(
        selected: Path,
        *,
        series_order: object = None,
    ) -> ResolvedScientificTransform:
        transform_calls.append((selected, series_order))
        return real_transform(selected, series_order=series_order)

    def captured_plan(
        *,
        rule_id: str,
        request: dict[str, Any],
        source_resolution: ResolvedScientificTransform,
        source_sha256: str,
    ) -> ResolvedFigurePlan:
        plan_snapshots.append(source_resolution)
        return real_plan(
            rule_id=rule_id,
            request=request,
            source_resolution=source_resolution,
            source_sha256=source_sha256,
        )

    monkeypatch.setattr(
        ftir_sources,
        "resolve_ftir_scientific_transform",
        counted_transform,
    )
    monkeypatch.setattr(
        single_curve_resolution,
        "resolve_registered_single_curve_plan",
        captured_plan,
    )

    resolved = resolve_scientific_source(
        source,
        rule_id=rule.rule_id,
        request={"series_order": ["A40-20"]},
        template=rule.template,
    )

    assert resolved is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    assert transform_calls == [(source, ["A40-20"])]
    assert len(plan_snapshots) == 1
    assert plan_snapshots[0] is transform
    assert transform.selected_sources == (source,)
    assert tuple(series.sample for series in transform.series) == ("A40-20",)
    assert {
        (series.x_label, series.x_unit, series.y_label, series.y_unit)
        for series in transform.series
    } == {("Wavenumber", "cm^-1", "Spectral response", "")}
    assert {
        str((series.diagnostics or {}).get("ftir_response_mode"))
        for series in transform.series
    } == {"unknown"}
    output = transform.contract.output
    assert {
        key: output[key]
        for key in (
            "x_metric",
            "y_metric",
            "x_label",
            "x_unit",
            "y_label",
            "y_unit",
            "response_mode",
        )
    } == {
        "x_metric": "wavenumber",
        "y_metric": "spectral_response",
        "x_label": "Wavenumber",
        "x_unit": "cm^-1",
        "y_label": "Spectral response",
        "y_unit": "",
        "response_mode": "unknown",
    }

    assert rule.scientific_source_adapter == "ftir"
    assert rule.figure_plan_adapter == "registered_single_curve"
    assert rule.render_adapter == "generic"
    assert rule.y_axis.canonical_label == "Spectral response"
    assert rule.y_axis.canonical_unit == ""
    assert rule.analysis[0].metric == "observed_response_extremum_wavenumber_cm-1"
    plan = resolved.figure_plan
    assert plan is not None
    task = plan.tasks[0]
    assert task.figure_id == "ftir_spectrum_spectral_response_vs_wavenumber"
    assert task.title == "Spectral response vs Wavenumber"
    assert task.metric_binding == CartesianMetricBinding(
        x_metric="wavenumber",
        y_metric="spectral_response",
    )
    assert task.sample_order == ("A40-20",)
    assert task.replicate_counts == (("A40-20", 1),)
    queue = generic_figure_queue_from_plan(
        plan,
        render_adapter=rule.render_adapter,
    )
    assert [item["id"] for item in queue] == [task.figure_id]
    assert queue[0]["resolved_figure_task"] == task.to_payload()

    monkeypatch.setattr(
        prepare_curve_families,
        "resolve_single_curve_transform",
        lambda *_args, **_kwargs: pytest.fail(
            "FTIR preparation resolved the source snapshot twice"
        ),
    )
    prepared = prepare_semantic_source(
        source,
        output_dir=tmp_path / "prepared",
        semantic={"rule_id": rule.rule_id, "semantic_family": rule.semantic_family},
        resolved_scientific_source=resolved,
    )

    step = prepared["transform_steps"][0]
    assert step["operation"] == "extract_wavenumber_spectral_response_curve"
    assert step["parameters"]["selected_axis_columns"] == {
        "x": output["x_label"],
        "y": output["y_label"],
    }
    assert step["parameters"]["scientific_transform"] == (
        transform.contract.to_payload()
    )
    with Path(str(prepared["source"])).open(newline="", encoding="utf-8") as handle:
        prepared_rows = list(csv.reader(handle))
    assert prepared_rows[:3] == [
        ["Wavenumber", "Spectral response"],
        ["cm^-1", ""],
        ["A40-20", "A40-20"],
    ]


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_registered_paired_curve_preparation_materializes_resolved_snapshot_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rule_id: str,
) -> None:
    rule = get_rule(rule_id)
    fixture = _fixture(rule_id)
    expected_series = _fixture_series(rule_id)
    resolved = resolve_scientific_source(
        fixture,
        rule_id=rule_id,
        request={},
        template=rule.template,
    )
    assert resolved is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    monkeypatch.setattr(
        prepare_curve_families,
        "resolve_single_curve_transform",
        lambda *_args, **_kwargs: pytest.fail(
            "paired-curve preparation resolved the source snapshot twice"
        ),
    )
    prepared = prepare_semantic_source(
        fixture,
        output_dir=tmp_path / "prepared",
        semantic={"rule_id": rule_id, "semantic_family": rule.semantic_family},
        resolved_scientific_source=resolved,
    )

    assert prepared["processed"] is True
    step = prepared["transform_steps"][0]
    assert step["operation"] == (
        f"extract_{transform.contract.output['x_metric']}_"
        f"{transform.contract.output['y_metric']}_curve"
    )
    assert step["parameters"]["selected_axis_columns"] == {
        "x": rule.x_axis.canonical_label,
        "y": rule.y_axis.canonical_label,
    }
    assert step["parameters"]["scientific_transform"] == (
        transform.contract.to_payload()
    )
    assert step["parameters"]["series_order"] == [
        expected.sample for expected in expected_series
    ]
    with Path(str(prepared["source"])).open(newline="", encoding="utf-8") as handle:
        prepared_rows = list(csv.reader(handle))
    assert prepared_rows[0] == [
        header
        for _expected in expected_series
        for header in (rule.x_axis.canonical_label, rule.y_axis.canonical_label)
    ]
    assert prepared_rows[1] == [
        unit
        for _expected in expected_series
        for unit in (
            rule.x_axis.canonical_unit,
            rule.y_axis.canonical_unit,
        )
    ]
    assert prepared_rows[2] == [
        sample
        for expected in expected_series
        for sample in (expected.sample, expected.sample)
    ]
    assert all(len(row) == len(expected_series) * 2 for row in prepared_rows)
    for series_index, expected in enumerate(expected_series):
        x_index = series_index * 2
        y_index = x_index + 1
        assert tuple(
            (float(row[x_index]), float(row[y_index]))
            for row in prepared_rows[3:]
            if row[x_index] and row[y_index]
        ) == expected.points


def test_saxs_plan_and_preparation_share_the_same_source_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = get_rule("saxs_profile")
    fixture = _fixture(rule.rule_id)
    rows = _fixture_rows(rule.rule_id)
    sample_row, header_row = rows[:2]
    x_indices = tuple(range(0, len(header_row), 2))
    expected_samples = tuple(sample_row[index] for index in x_indices)
    expected_points = tuple(
        tuple(
            (float(row[index]), float(row[index + 1]))
            for row in rows[2:]
            if row[index]
            and row[index + 1]
            and float(row[index + 1]) > 0.0
        )
        for index in x_indices
    )
    resolved = resolve_scientific_source(
        fixture,
        rule_id=rule.rule_id,
        request={},
        template=rule.template,
    )
    assert resolved is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    assert tuple(series.sample for series in transform.series) == expected_samples
    assert tuple(series.points for series in transform.series) == expected_points
    assert resolved.figure_plan is not None
    assert resolved.figure_plan.tasks[0].sample_order == expected_samples
    assert resolved.figure_plan.source_sha256 == resolved.source_sha256

    monkeypatch.setattr(
        prepare_curve_families,
        "resolve_single_curve_transform",
        lambda *_args, **_kwargs: pytest.fail(
            "SAXS preparation resolved its paired source twice"
        ),
    )
    prepared = prepare_semantic_source(
        fixture,
        output_dir=tmp_path / "prepared",
        semantic={"rule_id": rule.rule_id, "semantic_family": rule.semantic_family},
        resolved_scientific_source=resolved,
    )

    step = prepared["transform_steps"][0]
    assert step["parameters"]["scientific_transform"] == (
        transform.contract.to_payload()
    )
    with Path(str(prepared["source"])).open(
        newline="", encoding="utf-8"
    ) as handle:
        prepared_rows = list(csv.reader(handle))
    assert prepared_rows[0] == [
        value
        for _sample in expected_samples
        for value in (rule.x_axis.canonical_label, rule.y_axis.canonical_label)
    ]
    assert prepared_rows[1] == [
        value
        for _sample in expected_samples
        for value in (rule.x_axis.canonical_unit, rule.y_axis.canonical_unit)
    ]
    assert prepared_rows[2] == [
        sample for sample in expected_samples for _axis in range(2)
    ]
    for series_index, points in enumerate(expected_points):
        x_index = series_index * 2
        assert tuple(
            (float(row[x_index]), float(row[x_index + 1]))
            for row in prepared_rows[3:]
            if row[x_index] and row[x_index + 1]
        ) == points


def test_gpc_plan_and_preparation_share_source_identity_and_one_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = get_rule("gpc_sec_chromatogram")
    source = resolve_fixture_path(str(rule.fixture_path or ""))
    provenance = json.loads(
        (source / "source_provenance.json").read_text(encoding="utf-8")
    )
    expected_records = provenance["source_files"]
    expected_sources = tuple(
        (source / str(record["fixture_file"])).resolve()
        for record in expected_records
    )
    expected_samples = tuple(str(record["sample"]) for record in expected_records)
    expected_counts = tuple(
        int(record["retained_point_count"]) for record in expected_records
    )
    read_calls: list[Path] = []
    real_read = gpc_sources._read_candidate_tables

    def counted_read(path: Path) -> list[tuple[str, Any]]:
        read_calls.append(path.resolve())
        return real_read(path)

    monkeypatch.setattr(gpc_sources, "_read_candidate_tables", counted_read)
    resolved = resolve_scientific_source(
        source,
        rule_id=rule.rule_id,
        request={},
        template=rule.template,
    )

    assert resolved is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    assert read_calls == list(expected_sources)
    assert transform.selected_sources == expected_sources
    assert tuple(series.sample for series in transform.series) == expected_samples
    assert tuple(len(series.points) for series in transform.series) == expected_counts
    assert all(
        (series.x_unit, series.y_unit)
        == (
            provenance["output_units"]["elution_time"],
            provenance["output_units"]["detector_response"],
        )
        for series in transform.series
    )
    contract = transform.contract.to_payload()
    assert contract["selected_sources"] == [str(path) for path in expected_sources]
    assert contract["output"]["series_order"] == list(expected_samples)
    assert all(
        columns["source_table"].endswith(":Slice Table")
        and columns["x"]["header"] == record["selected_columns"][0]
        and columns["response"]["header"] == record["selected_columns"][1]
        and columns["response"]["unit_detection"]["method"]
        == "detected_from_detector_metadata"
        for columns, record in zip(
            contract["source_columns"], expected_records, strict=True
        )
    )
    assert resolved.figure_plan is not None
    assert resolved.figure_plan.tasks[0].sample_order == expected_samples
    assert resolved.figure_plan.source_sha256 == resolved.source_sha256

    monkeypatch.setattr(
        gpc_sources,
        "_read_candidate_tables",
        lambda _path: pytest.fail("GPC preparation parsed its source twice"),
    )
    prepared = prepare_semantic_source(
        source,
        output_dir=tmp_path / "prepared",
        semantic={"rule_id": rule.rule_id, "semantic_family": rule.semantic_family},
        resolved_scientific_source=resolved,
    )
    step = prepared["transform_steps"][0]
    assert step["parameters"]["scientific_transform"] == contract
    assert step["parameters"]["series_order"] == list(expected_samples)


def test_gpc_source_requires_an_explicit_detector_unit(tmp_path: Path) -> None:
    source = tmp_path / "gpc.csv"
    source.write_text(
        "Elution time,Detector response\n"
        "min,\n"
        "Series A,Series A\n"
        "1,2\n",
        encoding="utf-8",
    )
    rule = get_rule("gpc_sec_chromatogram")

    with pytest.raises(ScientificSourceResolutionError) as error:
        resolve_scientific_source(
            source,
            rule_id=rule.rule_id,
            request={},
            template=rule.template,
        )

    assert error.value.reason_code == "gpc_sec_chromatogram_transform_invalid"
    assert "GPC y unit must be explicit" in str(error.value)
