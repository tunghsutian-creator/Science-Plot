from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.materials_rules import tensile_curve_metric_values
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plan_preview import build_plan_preview
from sciplot_core.semantic import _read_tensile_workbook_directory
from sciplot_core.study_model import experiment_recommendation_payload


def test_tensile_workbook_directory_uses_representative_and_specimen_sheets(
    tmp_path,
) -> None:
    workbook = tmp_path / "E0.xlsx"
    with pd.ExcelWriter(workbook) as writer:
        pd.DataFrame(
            [
                ["Strain", "Stress"],
                ["%", "MPa"],
                ["E0 representative", "E0 representative"],
                [0.0, 0.1],
                [1.0, 10.0],
            ]
        ).to_excel(writer, sheet_name="Representative_Curve", header=False, index=False)
        pd.DataFrame(
            [
                ["Filename", "Strength (MPa)", "Modulus (MPa)", "Elongation (%)"],
                ["E0_1.csv", 10.0, 100.0, 20.0],
                ["E0_2.csv", 12.0, 110.0, 22.0],
            ]
        ).to_excel(writer, sheet_name="All_Specimens", header=False, index=False)
        pd.DataFrame([["label", "E0"]]).to_excel(
            writer, sheet_name="DataStudio_Metadata", header=False, index=False
        )

    curves, summary_rows = _read_tensile_workbook_directory(tmp_path)

    assert [(curve.sample, len(curve.points)) for curve in curves] == [("E0", 2)]
    assert (curves[0].x_label, curves[0].y_label) == ("Tensile strain", "Tensile stress")
    assert curves[0].points == ((0.0, 0.1), (1.0, 10.0))
    assert curves[0].diagnostics["source_x_label"] == "Strain"
    assert curves[0].diagnostics["source_y_label"] == "Stress"
    assert curves[0].diagnostics["source_x_unit"] == "%"
    assert curves[0].diagnostics["source_y_unit"] == "MPa"
    assert len(summary_rows) == 2
    assert {row["sample"] for row in summary_rows} == {"E0"}
    assert {row["strength_MPa"] for row in summary_rows} == {10.0, 12.0}
    assert {row["elongation_at_break_percent"] for row in summary_rows} == {20.0, 22.0}
    assert all("strain_at_break_percent" not in row for row in summary_rows)


def _curated_workbook(path, *, labels=("Strain", "Stress"), units=("%", "MPa")):
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([labels, units, (path.stem, path.stem), (0.0, 0.0), (1.0, 10.0)]).to_excel(
            writer, sheet_name="Representative_Curve", header=False, index=False
        )
        pd.DataFrame(
            [["specimen", 10.0, 100.0, 20.0]],
            columns=["Filename", "Strength (MPa)", "Modulus (MPa)", "Elongation (%)"],
        ).to_excel(writer, sheet_name="All_Specimens", index=False)


@pytest.mark.parametrize("labels", [
    ("Tensile strain", "Tensile stress"), ("STRAIN", "stress"),
    ("拉伸应变", "拉伸应力"), ("strain", "σ"),
])
def test_curated_tensile_aliases_preserve_source_metadata_and_values(tmp_path, labels):
    _curated_workbook(tmp_path / "A.xlsx", labels=labels)
    curves, _ = _read_tensile_workbook_directory(tmp_path)
    curve = curves[0]
    assert (curve.x_label, curve.y_label) == ("Tensile strain", "Tensile stress")
    assert (curve.x_unit, curve.y_unit) == ("%", "MPa")
    assert curve.points == ((0.0, 0.0), (1.0, 10.0))
    assert (curve.diagnostics["source_x_label"], curve.diagnostics["source_y_label"]) == labels


@pytest.mark.parametrize("labels,units,reason", [
    (("Shear strain", "Stress"), ("%", "MPa"), "mechanical_source_contract_invalid"),
    (("Strain", "Compressive stress"), ("%", "MPa"), "mechanical_source_contract_invalid"),
    (("strain rate", "Stress"), ("%", "MPa"), "mechanical_source_contract_invalid"),
    (("Strain", "Stress"), ("1", "MPa"), "mechanical_curve_unit_or_points_invalid"),
    (("Strain", "Stress"), ("%", "kPa"), "mechanical_curve_unit_or_points_invalid"),
])
def test_curated_tensile_second_workbook_cannot_bypass_label_or_unit_guards(
    tmp_path, labels, units, reason,
):
    _curated_workbook(tmp_path / "A.xlsx")
    _curated_workbook(tmp_path / "B.xlsx", labels=labels, units=units)
    result = build_plan_preview(tmp_path, request={"rule_id": "tensile_curve"})
    assert result["status"] == "blocked"
    assert result["blocker"]["reason_code"] == reason


def test_real_curated_tensile_source_reaches_metric_gate_without_changing_data():
    source = Path(__file__).parent / "fixtures/rendering_profiles/mechanical-v1/raw"
    before = {path: file_sha256(path) for path in source.glob("*.xlsx")}
    assert len(before) == 4
    curves, summary = _read_tensile_workbook_directory(source)
    assert [curve.sample for curve in curves] == ["E0", "E2", "E3", "E4"]
    assert len(summary) == 20
    for curve in curves:
        raw = pd.read_excel(curve.diagnostics["source_file"], sheet_name="Representative_Curve", header=None)
        assert curve.points == tuple(tuple(map(float, row)) for row in raw.iloc[3:].itertuples(index=False, name=None))
        assert (curve.x_label, curve.y_label, curve.x_unit, curve.y_unit) == (
            "Tensile strain", "Tensile stress", "%", "MPa"
        )
    result = build_plan_preview(source, request={"rule_id": "tensile_curve"})
    # The historical curated export has no specimen toughness measurements.
    # Recognizing its headers must not manufacture them to pass the complete plan.
    assert result["status"] == "blocked"
    assert result["blocker"]["reason_code"] == "mechanical_summary_metric_missing"
    assert "toughness_MJ_m3" in result["blocker"]["message"]
    assert all(file_sha256(path) == sha for path, sha in before.items())


@pytest.mark.parametrize(
    ("workbook_stem", "metadata_mode"),
    (("e7", "blank"), ("m-rPA-7", "missing")),
)
def test_tensile_workbook_directory_falls_back_to_exact_workbook_stem(
    tmp_path,
    workbook_stem: str,
    metadata_mode: str,
) -> None:
    workbook = tmp_path / f"{workbook_stem}.xlsx"
    with pd.ExcelWriter(workbook) as writer:
        pd.DataFrame(
            [
                ["Strain", "Stress"],
                ["%", "MPa"],
                ["representative", "representative"],
                [0.0, 0.1],
                [1.0, 10.0],
            ]
        ).to_excel(writer, sheet_name="Representative_Curve", header=False, index=False)
        pd.DataFrame(
            [
                ["Filename", "Strength (MPa)"],
                ["specimen-1.csv", 10.0],
                ["specimen-2.csv", 12.0],
            ]
        ).to_excel(writer, sheet_name="All_Specimens", header=False, index=False)
        if metadata_mode == "blank":
            pd.DataFrame([["label", ""]]).to_excel(
                writer,
                sheet_name="DataStudio_Metadata",
                header=False,
                index=False,
            )

    curves, summary_rows = _read_tensile_workbook_directory(tmp_path)

    assert [curve.sample for curve in curves] == [workbook_stem]
    assert {row["sample"] for row in summary_rows} == {workbook_stem}


def test_tensile_break_metric_is_publicly_elongation_with_legacy_input_alias() -> None:
    metrics = tensile_curve_metric_values(
        [(0.0, 0.0), (10.0, 10.0), (20.0, 15.0)],
        reported={"strain_at_break_percent": 12.0},
    )

    assert metrics["elongation_at_break_percent"] == 12.0
    assert metrics["elongation_at_break_source"] == "instrument_report"
    assert "strain_at_break_percent" not in metrics

    recommendation = experiment_recommendation_payload(rule_id="tensile_curve")
    break_figure = next(
        figure
        for figure in recommendation["figure_queue"]
        if figure["id"] == "elongation_at_break_by_sample"
    )
    assert break_figure["title"] == "Elongation at break by sample"
    assert break_figure["metric"] == "elongation_at_break_percent"


def test_high_strain_excerpt_does_not_invent_modulus_fracture_or_toughness() -> None:
    metrics = tensile_curve_metric_values([(10.0, 1.0), (20.0, 2.0), (30.0, 3.0)])

    for metric in ("modulus_MPa", "elongation_at_break_percent", "toughness_MJ_m3"):
        assert math.isnan(float(metrics[metric]))
    assert metrics["strength_MPa"] == 3.0
    assert metrics["curve_terminal_strain_percent"] == 30.0
    assert metrics["available_curve_integral_MJ_m3"] == pytest.approx(0.4)
    assert "0.05--0.25" in str(metrics["modulus_reason"])
    assert "does not prove fracture" in str(metrics["elongation_at_break_reason"])


@pytest.mark.parametrize("x_unit,factor", [("%", 1.0), ("1", 0.01)])
def test_tensile_covered_low_strain_fit_preserves_units_without_inventing_break(
    x_unit: str,
    factor: float,
) -> None:
    metrics = tensile_curve_metric_values(
        [(x * factor, x * 10.0) for x in (0.0, 0.05, 0.15, 0.25, 0.5)],
        x_unit=x_unit,
    )

    assert metrics["modulus_MPa"] == pytest.approx(1000.0)
    assert math.isnan(float(metrics["elongation_at_break_percent"]))
    assert metrics["curve_terminal_strain_percent"] == 0.5


def test_tensile_finite_reports_win_but_excerpt_integral_stays_descriptive() -> None:
    metrics = tensile_curve_metric_values(
        [(10.0, 1.0), (20.0, 2.0), (30.0, 3.0)],
        reported={"modulus_MPa": 800.0, "elongation_at_break_percent": 40.0},
    )

    assert metrics["modulus_MPa"] == 800.0
    assert metrics["elongation_at_break_percent"] == 40.0
    assert math.isnan(float(metrics["toughness_MJ_m3"]))
    assert metrics["toughness_source"] == "unavailable"


def test_nonfinite_instrument_reports_do_not_claim_instrument_provenance() -> None:
    metrics = tensile_curve_metric_values(
        [(10.0, 1.0), (20.0, 2.0)],
        reported={
            "strength_MPa": float("nan"),
            "modulus_MPa": float("inf"),
            "elongation_at_break_percent": float("nan"),
        },
    )

    assert metrics["strength_MPa"] == 2.0
    assert metrics["strength_source"] == "curve_maximum"
    assert metrics["modulus_source"] == "unavailable"
    assert metrics["elongation_at_break_source"] == "unavailable"
