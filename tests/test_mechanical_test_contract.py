from __future__ import annotations

from pathlib import Path

import pandas as pd

from sciplot_core.materials_rules import get_rule, semantic_payload_from_rule
from sciplot_core.policy import mechanical_axis_labels
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.studio import _apply_domain_render_defaults
from sciplot_core.study_model import experiment_recommendation_payload
from sciplot_core.workflow import _mechanical_summary_sources


def _write_curve(path: Path, *, stress_label: str, values: list[float]) -> None:
    pd.DataFrame(
        [
            ["Strain", stress_label],
            ["%", "MPa"],
            [path.stem, path.stem],
            *[[strain, stress] for strain, stress in enumerate(values)],
        ]
    ).to_csv(path, header=False, index=False)


def test_mechanical_rules_use_test_specific_stress_axis_labels() -> None:
    expected = {
        "tensile_curve": ("Strain (%)", "Tensile stress (MPa)"),
        "compression_curve": ("Strain (%)", "Compressive stress (MPa)"),
        "flexural_curve": ("Strain (%)", "Flexural stress (MPa)"),
    }

    for rule_id, labels in expected.items():
        rule = get_rule(rule_id)
        assert mechanical_axis_labels(rule_id) == labels
        assert (rule.x_axis.display_label, rule.y_axis.display_label) == labels


def test_mechanical_recommendations_distinguish_stress_and_strength() -> None:
    expected = {
        "tensile_curve": (
            "Tensile stress vs strain",
            "Tensile strength by sample",
        ),
        "compression_curve": (
            "Compressive stress vs strain",
            "Compressive strength by sample",
        ),
        "flexural_curve": (
            "Flexural stress vs strain",
            "Flexural strength by sample",
        ),
    }

    for rule_id, titles in expected.items():
        recommendation = experiment_recommendation_payload(rule_id=rule_id)
        assert tuple(item["title"] for item in recommendation["figure_queue"][:2]) == titles

    tensile = experiment_recommendation_payload(rule_id="tensile_curve")
    assert any(
        item["title"] == "Elongation at break by sample"
        for item in tensile["figure_queue"]
    )
    for rule_id in ("compression_curve", "flexural_curve"):
        recommendation = experiment_recommendation_payload(rule_id=rule_id)
        assert all(
            "elongation" not in item["metric"]
            for item in recommendation["figure_queue"]
        )


def test_flexural_child_render_request_keeps_flexural_stress_label() -> None:
    options = _apply_domain_render_defaults(
        {},
        request={
            "template": "curve",
            "y_metric": "flexural_stress",
            "render_options": {},
        },
        axis_info={
            "x_label": "Strain (%)",
            "y_label": "Flexural stress (MPa)",
        },
    )

    assert options["x_label_override"] == "Strain (%)"
    assert options["y_label_override"] == "Flexural stress (MPa)"


def test_compression_and_flexural_prepare_curve_and_strength_summary(
    tmp_path: Path,
) -> None:
    contracts = (
        (
            "compression_curve",
            "Compressive stress",
            [-1.0, -4.0, -2.0],
            "compressive_strength_MPa",
            4.0,
        ),
        (
            "flexural_curve",
            "Flexural stress",
            [1.0, 5.0, 3.0],
            "flexural_strength_MPa",
            5.0,
        ),
    )
    for rule_id, stress_label, values, strength_metric, expected_strength in contracts:
        source = tmp_path / f"{rule_id}.csv"
        _write_curve(source, stress_label=stress_label, values=values)
        output_dir = tmp_path / f"{rule_id}_out"
        prepared = prepare_semantic_source(
            source,
            output_dir=output_dir,
            semantic=semantic_payload_from_rule(
                get_rule(rule_id),
                confidence=1.0,
            ),
        )

        processed = Path(prepared["processed_source"])
        curve = pd.read_csv(processed, header=None)
        assert curve.iat[0, 0] == "Strain"
        assert curve.iat[0, 1] == stress_label
        summary_path = processed.with_name(f"{processed.stem}_summary.csv")
        summary = pd.read_csv(summary_path)
        assert summary[strength_metric].tolist() == [expected_strength]

        sources = _mechanical_summary_sources(
            processed,
            request={"rule_id": rule_id},
            output_dir=output_dir,
            options={},
        )
        assert len(sources) == 1
        _figure_id, _metric_source, render_options = sources[0]
        assert render_options["y_label_override"] == (
            "Compressive strength (MPa)"
            if rule_id == "compression_curve"
            else "Flexural strength (MPa)"
        )


def test_flexural_workbook_directory_uses_all_specimen_strengths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "flexural"
    source.mkdir()
    workbook = source / "sample_a.xlsx"
    with pd.ExcelWriter(workbook) as writer:
        pd.DataFrame(
            [
                ["Strain", "Stress"],
                ["%", "MPa"],
                ["representative", "representative"],
                [0.0, 0.0],
                [1.0, 8.0],
            ]
        ).to_excel(
            writer,
            sheet_name="Representative_Curve",
            header=False,
            index=False,
        )
        pd.DataFrame(
            [
                ["a_1.csv", 10.0],
                ["a_2.csv", 12.0],
            ],
            columns=["Filename", "Strength (MPa)"],
        ).to_excel(
            writer,
            sheet_name="All_Specimens",
            index=False,
        )
        pd.DataFrame([["label", "A"]]).to_excel(
            writer,
            sheet_name="DataStudio_Metadata",
            header=False,
            index=False,
        )

    prepared = prepare_semantic_source(
        source,
        output_dir=tmp_path / "out",
        semantic=semantic_payload_from_rule(
            get_rule("flexural_curve"),
            confidence=1.0,
        ),
    )

    processed = Path(prepared["processed_source"])
    curve = pd.read_csv(processed, header=None)
    summary = pd.read_csv(
        processed.with_name(f"{processed.stem}_summary.csv")
    )
    assert curve.iat[2, 0] == "A"
    assert summary["sample"].tolist() == ["A", "A"]
    assert summary["flexural_strength_MPa"].tolist() == [10.0, 12.0]
    assert set(summary["strength_source"]) == {"instrument_report"}
