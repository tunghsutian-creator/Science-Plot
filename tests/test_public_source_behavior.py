"""Public behavior controls with generated values, distinct from real science."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from public_curve_inputs import PAIR_AXES, dma_source, gpc_source, neutral_ftir_source, paired_source
from public_multitask_inputs import mechanical_source, temperature_source
from sciplot_core.figure_plan import FigurePlanResolutionError, resolve_current_figure_plan, resolve_figure_plan
from sciplot_core.figure_plan.temperature_resolution import resolve_temperature_plan
from sciplot_core.materials_rules import compute_analysis_metrics, get_rule, semantic_payload_from_rule
from sciplot_core.plan_preview import build_plan_preview
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.semantic_sources.mechanical_fact_models import MechanicalSourceFactsError
from sciplot_core.semantic_sources.mechanical_facts import load_mechanical_source_facts
from sciplot_core.semantic_sources.scientific_source import resolve_scientific_source
from sciplot_core.semantic_sources.scientific_transform import ResolvedScientificTransform
from sciplot_core.studio_core.figure_task_evidence import generic_figure_queue_from_plan


@pytest.mark.parametrize("rule_id", sorted(PAIR_AXES))
def test_generated_pairs_share_exact_snapshot_plan_prepare_and_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rule_id: str) -> None:
    source, expected = paired_source(tmp_path / "raw", rule_id)
    original = source.read_bytes()
    rule = get_rule(rule_id)
    resolved = resolve_scientific_source(source, rule_id=rule_id, template=rule.template, request={})
    assert resolved is not None and resolved.figure_plan is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    assert tuple(item.points for item in transform.series) == expected
    assert tuple(item.sample for item in transform.series) == ("Generated Cedar", "Generated Birch")
    assert resolved.figure_plan.source_sha256 == resolved.source_sha256
    assert len(resolved.figure_plan.tasks) == 1
    task = resolved.figure_plan.tasks[0]
    assert task.sample_order == tuple(item.sample for item in transform.series)
    assert generic_figure_queue_from_plan(resolved.figure_plan, render_adapter="generic")[0]["id"] == task.figure_id
    import sciplot_core.semantic_sources.prepare_curve_families as preparation
    monkeypatch.setattr(preparation, "resolve_single_curve_transform", lambda *_a, **_k: pytest.fail("resolved snapshot was reparsed"))
    prepared = prepare_semantic_source(source, output_dir=tmp_path / "prepared", semantic={"rule_id": rule_id, "semantic_family": rule.semantic_family}, resolved_scientific_source=resolved)
    assert prepared["transform_steps"][0]["parameters"]["scientific_transform"] == transform.contract.to_payload()
    assert source.read_bytes() == original


@pytest.mark.parametrize("rule_id", sorted(PAIR_AXES))
def test_generated_pair_directory_selection_and_byte_drift_fail_closed(tmp_path: Path, rule_id: str) -> None:
    source, _ = paired_source(tmp_path / "raw", rule_id)
    rule = get_rule(rule_id)
    resolved = resolve_scientific_source(source, rule_id=rule_id, template=rule.template, request={})
    directory = resolve_scientific_source(source.parent, rule_id=rule_id, template=rule.template, request={})
    assert resolved is not None and directory is not None
    assert directory.require_domain(ResolvedScientificTransform) == resolved.require_domain(ResolvedScientificTransform)
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(FigurePlanResolutionError) as drift:
        resolve_current_figure_plan(persisted=resolved.figure_plan.to_payload(), rule_id=rule_id, template=rule.template,
                                    study_model={}, input_path=source, request={})
    assert drift.value.reason_code == "stale_resolved_figure_plan"
    (source.parent / "second.csv").write_bytes(source.read_bytes())
    with pytest.raises((ValueError, FigurePlanResolutionError)):
        resolve_scientific_source(source.parent, rule_id=rule_id, template=rule.template, request={})


@pytest.mark.parametrize("rule_id", ("dtg_curve", "xrd_pattern", "tga_curve"))
def test_generated_descriptive_metrics_use_each_original_grid(tmp_path: Path, rule_id: str) -> None:
    source, points = paired_source(tmp_path / "raw", rule_id)
    metrics = compute_analysis_metrics(source_path=source, processed_source=None,
                                      semantic=semantic_payload_from_rule(get_rule(rule_id), confidence=1.), output_dir=tmp_path / "analysis")
    if rule_id == "tga_curve":
        assert [row["value"] for row in metrics if row["metric"].startswith("residual_mass")] == [p[-1][1] for p in points]
    else:
        assert [row["value"] for row in metrics] == [max(p, key=lambda item: item[1])[0] for p in points]
    assert all(row["status"] == "ok" for row in metrics if not row["metric"].startswith(("t5_", "t10_")))


def test_generated_dma_conversion_ragged_negative_and_stale_identity(tmp_path: Path) -> None:
    source = dma_source(tmp_path / "raw")
    resolved = resolve_scientific_source(source, rule_id="dma_temperature_sweep", template="point_line", request={})
    assert resolved is not None and resolved.figure_plan is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    assert tuple(len(series.points) for series in transform.series) == (4, 2)
    assert transform.series[0].points[2] == (15., -2.5)
    contract = transform.contract.to_payload()
    assert contract["output"]["series_order"] == ["Cedar", "Birch"]
    assert [row["excluded_point_count"] for row in contract["output"]["series"]] == [0, 2]
    assert all(row["canonical_unit"] == "Pa" for row in contract["unit_conversions"] if row["role"] == "response")
    prepared = prepare_semantic_source(source, output_dir=tmp_path / "prepared", semantic={"rule_id": "dma_temperature_sweep", "semantic_family": "dma_temperature_sweep"}, resolved_scientific_source=resolved)
    prepared["source_attestation"].verify_current(source_root=source, prepared_source=Path(str(prepared["processed_source"])))
    source.write_text(source.read_text().replace("15,-2.5", "15,-3.5"))
    with pytest.raises(FigurePlanResolutionError) as drift:
        resolve_current_figure_plan(persisted=resolved.figure_plan.to_payload(), rule_id="dma_temperature_sweep", template="point_line", study_model={}, input_path=source, request={})
    assert drift.value.reason_code == "stale_resolved_figure_plan"


@pytest.mark.parametrize("rule_id", ("tensile_curve", "compression_curve", "flexural_curve"))
def test_generated_mechanical_replicates_plan_attestation_and_mean_rejection(tmp_path: Path, rule_id: str) -> None:
    source = mechanical_source(tmp_path / "raw", rule_id)
    facts = load_mechanical_source_facts(source, rule_id=rule_id)
    assert facts.sample_order == ("Cedar",)
    assert facts.replicate_counts == (("Cedar", 3),)
    metric = {"tensile_curve": "strength_MPa", "compression_curve": "compressive_strength_MPa", "flexural_curve": "flexural_strength_MPa"}[rule_id]
    assert [row.metric_value(metric) for row in facts.summary_rows] == [10., 20., 40.]
    assert (facts.representative_curve_series[0].diagnostics or {})["replicate_label"] == "repeat 2"
    plan = resolve_figure_plan(rule_id=rule_id, template="curve", input_path=source, request={}, study_model={})
    assert plan is not None and len(plan.tasks) == (5 if rule_id == "tensile_curve" else 2)
    assert all(task.replicate_counts == (("Cedar", 3),) for task in plan.tasks)
    prepared = prepare_semantic_source(source, output_dir=tmp_path / "prepared", semantic=semantic_payload_from_rule(get_rule(rule_id), confidence=1.), replicate_mode="individual")
    frame = pd.read_csv(Path(str(prepared["processed_source"])), header=None)
    assert len(frame.iloc[2, ::2]) == 3
    prepared["source_attestation"].verify_current(source_root=source, prepared_source=Path(str(prepared["processed_source"])))
    rejected = tmp_path / "mean"
    with pytest.raises(MechanicalSourceFactsError) as mean:
        prepare_semantic_source(source, output_dir=rejected, semantic=semantic_payload_from_rule(get_rule(rule_id), confidence=1.), replicate_mode="mean")
    assert mean.value.reason_code == "mechanical_curve_mean_unsupported"
    assert not any(path.is_file() for path in rejected.rglob("*"))


def test_generated_temperature_plan_order_and_preview_preserve_source(tmp_path: Path) -> None:
    source = temperature_source(tmp_path / "raw")
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    plan = resolve_temperature_plan(input_path=source, request={})
    assert plan.selected_figure_ids == ("storage_modulus_vs_temperature", "tan_delta_vs_temperature")
    assert all(task.sample_order == ("Cedar", "Birch", "Maple") for task in plan.tasks)
    reordered = resolve_temperature_plan(input_path=source, request={"series_order": ["Maple", "Cedar", "Birch"]})
    assert all(task.sample_order == ("Maple", "Cedar", "Birch") for task in reordered.tasks)
    preview = build_plan_preview(source, request={"rule_id": "rheology_temperature_sweep", "template": "point_line"})
    assert preview["status"] == "planned"
    assert preview["scientific_transform"] is None
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before


@pytest.mark.parametrize("rule_id", ("ftir_spectrum", "gpc_sec_chromatogram"))
def test_generated_spectroscopy_keeps_neutral_or_calibrated_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rule_id: str) -> None:
    source = neutral_ftir_source(tmp_path / "raw") if rule_id == "ftir_spectrum" else gpc_source(tmp_path / "raw")
    rule = get_rule(rule_id)
    reads = []
    if rule_id == "gpc_sec_chromatogram":
        import sciplot_core.semantic_sources.gpc_sources as reader
        original_read = reader._read_candidate_tables
        def counted(path):
            reads.append(path.resolve())
            return original_read(path)
        monkeypatch.setattr(reader, "_read_candidate_tables", counted)
    resolved = resolve_scientific_source(source, rule_id=rule_id, template=rule.template, request={})
    assert resolved is not None and resolved.figure_plan is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    assert transform.contract.to_payload()["normalizer"]["operation"] == "none"
    import sciplot_core.semantic_sources.prepare_curve_families as preparation
    monkeypatch.setattr(preparation, "resolve_single_curve_transform", lambda *_a, **_k: pytest.fail("second spectral preparation parse"))
    prepared = prepare_semantic_source(source, output_dir=tmp_path / "prepared", semantic={"rule_id": rule_id, "semantic_family": rule.semantic_family}, resolved_scientific_source=resolved)
    assert prepared["transform_steps"][0]["parameters"]["scientific_transform"] == transform.contract.to_payload()
    if rule_id == "ftir_spectrum":
        assert transform.series[0].points == ((4000., 0.), (3500., -1.), (3000., 2.))
    else:
        expected_sources = tuple(source / name for name in ("Birch.xlsx", "Cedar.xlsx"))
        assert reads == list(expected_sources)
        assert transform.selected_sources == expected_sources
        assert tuple(series.points for series in transform.series) == (((150., .2), (1500., .8)), ((100., .2), (1000., .8)))
        assert all(series.x_unit == "g/mol" for series in transform.series)


def test_generated_dma_snapshot_is_parsed_once_and_execution_rejects_foreign_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sciplot_core.figure_plan.dma_temperature_resolution as resolution
    import sciplot_core.semantic_sources.prepare_curve_families as preparation
    import sciplot_core.workflow.dma_temperature_plan as execution
    source = dma_source(tmp_path / "raw")
    calls = []
    original = resolution.resolve_dma_temperature_transform
    def counted(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(resolution, "resolve_dma_temperature_transform", counted)
    resolved = resolve_scientific_source(source, rule_id="dma_temperature_sweep", template="point_line", request={})
    assert resolved is not None and resolved.figure_plan is not None
    monkeypatch.setattr(preparation, "resolve_dma_temperature_transform", lambda *_a, **_k: pytest.fail("second DMA preparation parse"))
    prepared = prepare_semantic_source(source, output_dir=tmp_path / "prepared", semantic={"rule_id": resolved.rule_id, "semantic_family": resolved.rule_id}, resolved_scientific_source=resolved)
    monkeypatch.setattr(execution, "load_dma_temperature_source_facts", lambda *_a, **_k: pytest.fail("second DMA execution parse"))
    facts = execution.require_dma_temperature_execution_plan(resolved.figure_plan, source=source, resolved_scientific_source=resolved)
    assert calls == [source.resolve()]
    assert facts.sample_order == ("Cedar", "Birch") and facts.point_counts == (4, 2)
    assert prepared["transform_steps"][0]["parameters"]["scientific_transform"] == resolved.require_domain(ResolvedScientificTransform).contract.to_payload()
    with pytest.raises(ValueError, match="scientific_source_mismatch"):
        execution.require_dma_temperature_execution_plan(resolved.figure_plan, source=tmp_path / "foreign.csv", resolved_scientific_source=resolved)
    with pytest.raises(FigurePlanResolutionError) as wrong:
        resolve_figure_plan(rule_id=resolved.rule_id, template="curve", input_path=source, request={}, study_model={})
    assert wrong.value.reason_code == "dma_temperature_template_invalid"


def test_generated_mechanical_individual_plan_and_summary_template_contract(tmp_path: Path) -> None:
    source = mechanical_source(tmp_path / "raw", "compression_curve")
    plan = resolve_figure_plan(rule_id="compression_curve", template="curve", input_path=source, request={"replicate_mode": "individual"}, study_model={})
    assert plan is not None
    curve, summary = plan.tasks
    assert curve.sample_order == ("Cedar__repeat 1", "Cedar__repeat 2", "Cedar__repeat 3")
    assert curve.replicate_counts == tuple((sample, 1) for sample in curve.sample_order)
    assert summary.sample_order == ("Cedar",) and summary.replicate_counts == (("Cedar", 3),)
    assert (curve.template, summary.template) == ("curve", "box_strip")
    with pytest.raises(FigurePlanResolutionError) as wrong:
        resolve_figure_plan(rule_id="compression_curve", template="box_strip", input_path=source, request={"template": "box_strip"}, study_model={})
    assert wrong.value.reason_code == "mechanical_template_invalid"


def test_generated_tensile_preview_is_complete_pending_and_source_only_equivalent(tmp_path: Path) -> None:
    source = mechanical_source(tmp_path / "raw", "tensile_curve")
    explicit = build_plan_preview(source, request={"rule_id": "tensile_curve", "template": "curve"})
    implicit = build_plan_preview(source, request={})
    assert explicit["status"] == implicit["status"] == "planned"
    assert explicit["resolved_figure_plan"] == implicit["resolved_figure_plan"]
    plan = explicit["resolved_figure_plan"]
    assert len(plan["tasks"]) == 5
    assert all(task["sample_order"] == ["Cedar"] for task in plan["tasks"])
    assert plan["complete"] is False
    assert all(outcome["status"] == "pending" and not outcome["artifacts"] for outcome in plan["outcomes"])
