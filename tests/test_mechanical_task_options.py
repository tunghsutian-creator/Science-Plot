from __future__ import annotations

from pathlib import Path

from sciplot_core._paths import resolve_fixture_path
from sciplot_core.figure_plan import resolve_figure_plan
from sciplot_core.materials_rules import get_rule, semantic_payload_from_rule
from sciplot_core.mechanical_task_sources import build_mechanical_task_sources
from sciplot_core.policy import DEFAULT_PALETTE_PRESET
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.study_model import experiment_recommendation_payload


def test_summary_tasks_keep_style_without_curve_axis_or_series_options(
    tmp_path: Path,
) -> None:
    rule_id = "compression_curve"
    source = resolve_fixture_path(str(get_rule(rule_id).fixture_path or ""))
    request = {
        "rule_id": rule_id,
        "template": "curve",
        "explicit_render_option_keys": [
            "marker_alpha",
            "palette_preset",
            "raw_point_jitter_fraction",
            "size",
            "x_min",
        ],
    }
    plan = resolve_figure_plan(
        rule_id=rule_id,
        template="curve",
        study_model=experiment_recommendation_payload(rule_id=rule_id),
        input_path=source,
        request=request,
    )
    assert plan is not None
    prepared = prepare_semantic_source(
        source,
        output_dir=tmp_path / "prepared",
        semantic=semantic_payload_from_rule(get_rule(rule_id), confidence=1.0),
    )
    attestation = prepared["source_attestation"]
    assert isinstance(attestation, PreparationSourceAttestation)
    hostile = {
        "size": "120x55",
        "visual_theme_id": "clean_light",
        "style_preset": "nature",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "marker_alpha": 0.42,
        "x_min": 100.0,
        "x_max": 101.0,
        "y_min": 100.0,
        "y_max": 101.0,
        "xscale": "log",
        "yscale": "log",
        "series_include": ["not-a-summary-sample"],
        "reference_lines": [{"axis": "x", "value": 100.5}],
    }
    records = build_mechanical_task_sources(
        Path(str(prepared["source"])),
        raw_source=source,
        source_attestation=attestation,
        figure_plan=plan,
        output_dir=tmp_path / "terminal_sources",
        request=request,
        options=hostile,
    )

    curve, summary = records
    assert curve.render_options["x_min"] == 100.0
    assert summary.render_options["size"] == "120x55"
    assert summary.render_options["palette_preset"] == DEFAULT_PALETTE_PRESET
    assert summary.render_options["marker_alpha"] == 0.42
    assert summary.render_options["summary_statistic"] == "median_iqr"
    assert summary.render_options["x_metric"] == "sample"
    assert summary.explicit_render_option_keys == (
        "marker_alpha",
        "palette_preset",
        "size",
    )
    for key in (
        "x_min",
        "x_max",
        "y_min",
        "y_max",
        "xscale",
        "yscale",
        "series_include",
        "reference_lines",
    ):
        assert key not in summary.render_options
