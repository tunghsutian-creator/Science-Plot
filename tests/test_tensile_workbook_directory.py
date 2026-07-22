from __future__ import annotations

import pandas as pd

from sciplot_core.materials_rules import tensile_curve_metric_values
from sciplot_core.semantic import _read_tensile_workbook_directory
from sciplot_core.study_model import experiment_recommendation_payload


def test_tensile_workbook_directory_uses_representative_and_specimen_sheets(tmp_path) -> None:
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
    assert len(summary_rows) == 2
    assert {row["sample"] for row in summary_rows} == {"E0"}
    assert {row["strength_MPa"] for row in summary_rows} == {10.0, 12.0}
    assert {row["elongation_at_break_percent"] for row in summary_rows} == {20.0, 22.0}
    assert all("strain_at_break_percent" not in row for row in summary_rows)


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
