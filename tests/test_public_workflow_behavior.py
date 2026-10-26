"""Generated-input counterparts of bounded fault and transaction assertions.

Shared assertion bodies are reused only through explicit source-provider seams.
Their original measured-input nodes are retained unchanged in the full suite.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from public_curve_inputs import dma_source, paired_source
from public_multitask_inputs import mechanical_source, temperature_source
from sciplot_core.dma_temperature_contract import DMA_TEMPERATURE_RECIPE
from sciplot_core.figure_plan import FigurePlanResolutionError, ResolvedFigurePlan, resolve_figure_plan
from sciplot_core.semantic import classify_source, prepare_semantic_source
from sciplot_core.semantic_sources.scientific_source import resolve_scientific_source
from sciplot_core.semantic_sources.scientific_transform import ResolvedScientificTransform
from sciplot_core.studio_core.figure_task_evidence import figure_queue_from_plan
from sciplot_core.studio_core.figure_set_prepare import _prepare_studio_figure_set
from sciplot_core.studio_core.source_bound_prepare import bind_mechanical_task_sources
from sciplot_core.studio_render.models import StudioPreparationBlocked
from sciplot_core.workflow import request_rendering
from sciplot_core.workflow.route_intent import resolve_workflow_route_intent

TEMPERATURE_CONTROLS = (
    "test_temperature_bundle_requires_exact_figure_plan_before_materialization",
    "test_temperature_bundle_rejects_source_binding_mismatch_before_renderer",
    "test_temperature_task_sources_consume_preparation_attestation_without_rediscovery",
    "test_temperature_prepared_workbook_drift_fails_before_task_materialization",
    "test_frequency_bundle_rejects_injected_private_binding_before_renderer",
    "test_temperature_bundle_rejects_pdf_only_renderer_payload",
    "test_temperature_bundle_second_renderer_failure_publishes_nothing",
)


@pytest.mark.parametrize("control", TEMPERATURE_CONTROLS)
def test_generated_temperature_transaction_control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, control: str) -> None:
    import test_temperature_workflow_repair as assertions
    source = temperature_source(tmp_path / "generated_raw")
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    monkeypatch.setattr(assertions, "_real_temperature_fixture", lambda: source)
    function = getattr(assertions, control)
    if "without_rediscovery" in control:
        function(tmp_path, monkeypatch)
    else:
        function(tmp_path)
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before


@pytest.mark.parametrize("mutation", ("added", "modified"))
def test_generated_temperature_raw_drift_blocks_before_renderer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    import test_temperature_workflow_repair as assertions
    source = temperature_source(tmp_path / "generated_raw")
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    monkeypatch.setattr(assertions, "_real_temperature_fixture", lambda: source)
    assertions.test_temperature_raw_drift_after_prepare_fails_before_renderer(tmp_path, mutation)
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before


@pytest.mark.parametrize("control", ("bounded_seam", "forged_task", "staging_cleanup", "foreign_plan"))
def test_generated_dma_named_recipe_bounded_controls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, control: str) -> None:
    import test_dma_named_recipe_plan_binding as assertions
    source = dma_source(tmp_path / "generated_raw")
    original = source.read_bytes()
    monkeypatch.setattr(assertions, "_fixture", lambda: source)
    if control == "bounded_seam":
        assertions.test_exact_dma_named_recipe_plan_reaches_only_the_bounded_seam(tmp_path, monkeypatch)
    elif control == "forged_task":
        assertions.test_dma_named_recipe_rejects_forged_task_before_writes(tmp_path, monkeypatch)
    elif control == "staging_cleanup":
        assertions.test_workflow_discards_staging_tree_on_named_recipe_conflict(tmp_path)
    else:
        assertions.test_rheology_dma_cannot_consume_an_unbounded_non_dma_plan(tmp_path, monkeypatch)
    assert source.read_bytes() == original


@pytest.mark.parametrize("conflict", ("template", "metric", "unit", "order", "forged_terminal", "axis"))
def test_generated_dma_named_recipe_conflict_never_prepares_or_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conflict: str) -> None:
    import test_dma_named_recipe_plan_binding as assertions
    source = dma_source(tmp_path / "generated_raw")
    monkeypatch.setattr(assertions, "_fixture", lambda: source)
    patch = {"template": {"template": "curve"}, "metric": {"y_metric": "loss_factor"},
             "unit": {"display_y_unit": "Pa"}, "order": {"series_order": ["Birch", "Cedar"]},
             "forged_terminal": {"series_encoding_contract": {}}, "axis": {"render_options": {"y_min": 1.}}}[conflict]
    reason = {"forged_terminal": "terminal_evidence_forged", "axis": "axis_visibility_conflict"}.get(conflict, "plan_conflict")
    assertions.test_dma_named_recipe_conflicts_fail_before_semantic_preparation(tmp_path, monkeypatch, patch, reason)


def test_generated_dma_preflight_and_changed_source_cannot_enter_renderer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sciplot_core.workflow.dma_named_recipe import bind_dma_named_recipe_request
    source = dma_source(tmp_path / "generated_raw")
    plan = resolve_figure_plan(rule_id="dma_temperature_sweep", template="point_line", input_path=source, request={}, study_model={})
    assert plan is not None
    request = {"recipe": DMA_TEMPERATURE_RECIPE, "rule_id": plan.rule_id, "resolved_figure_plan": plan.to_payload(), "exports": ["pdf", "tiff_300"]}
    bound = bind_dma_named_recipe_request(requested_recipe=DMA_TEMPERATURE_RECIPE, request=request, plan=plan,
                                          input_path=source, semantic=classify_source(source, requested_rule_id=plan.rule_id))
    assert bound.plan_sha256 == plan.plan_sha256
    source.write_text(source.read_text().replace("15,-2.5", "15,-7.5"))
    monkeypatch.setattr(request_rendering, "prepare_semantic_source", lambda *_a, **_k: pytest.fail("changed source reached preparation"))
    with pytest.raises((ValueError, FigurePlanResolutionError)):
        request_rendering.execute_request_render(request=request, route_intent=resolve_workflow_route_intent(request),
                                                semantic=classify_source(source, requested_rule_id=plan.rule_id), study_model={},
                                                input_path=source, output_dir=tmp_path / "rejected", base_dir=tmp_path, transform_steps=[])
    assert not (tmp_path / "rejected").exists()


@pytest.mark.parametrize("shape", ("partial", "all", "empty", "tuple", "non_mapping", "non_string_key", "empty_mapping"))
def test_generated_mechanical_queue_guards_before_native_writes(tmp_path: Path, shape: str) -> None:
    source = mechanical_source(tmp_path / "raw", "compression_curve")
    plan = resolve_figure_plan(rule_id="compression_curve", template="curve", input_path=source, request={}, study_model={})
    assert plan is not None
    project = tmp_path / "project"
    project.mkdir()
    request = {"input": str(source), "rule_id": plan.rule_id, "template": "curve", "resolved_figure_plan": plan.to_payload()}
    queue = figure_queue_from_plan(plan, plan.rule_id)
    if shape in {"partial", "all"}:
        for item in queue[:1] if shape == "partial" else queue:
            item["_mechanical_task_source"] = "forged source"
        with pytest.raises(StudioPreparationBlocked, match="fresh, complete mechanical task-source queue"):
            bind_mechanical_task_sources(queue, figure_plan=plan, source_attestation=None, project_dir=project, request=request)
    else:
        invalid = {"empty": [], "tuple": tuple(queue), "non_mapping": [object()],
                   "non_string_key": [{**queue[0], 1: "forged"}, *queue[1:]], "empty_mapping": [{}]}[shape]
        from sciplot_core.project_store import FileProjectStore
        from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate

        host_project = tmp_path / "host_project"
        host_project.mkdir()
        store = FileProjectStore(host_project)
        before = store.snapshot(import_legacy=True)
        with studio_preparation_candidate(store) as candidate:
            with pytest.raises(StudioPreparationBlocked, match="non-empty internal list queue|malformed internal queue"):
                _prepare_studio_figure_set(project_dir=candidate.project_dir,
                                          request_path=candidate.project_dir / "plot_request.json", request=request,
                                          primary_document=candidate.project_dir / "studio/document.vsz", preserve_existing=False,
                                          queue_override=invalid, figure_plan=plan)
            assert not any(path.is_file() for path in candidate.project_dir.rglob("*"))
        assert store.snapshot() == before
    assert not any(path.is_file() for path in project.rglob("*"))


@pytest.mark.parametrize("control", ("workflow_tga", "workflow_dsc", "studio_dsc", "without_snapshot", "archive_drift"))
def test_generated_snapshot_archive_hash_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, control: str) -> None:
    import test_scientific_source_pipeline as assertions
    sources = {rule: paired_source(tmp_path / rule, rule)[0] for rule in ("tga_curve", "dsc_curve")}
    monkeypatch.setattr(assertions, "resolve_fixture_path", lambda identifier: sources[Path(identifier).parts[3]])
    if control.startswith("workflow_"):
        assertions.test_workflow_source_binding_hashes_only_archive_for_paired_snapshot(tmp_path, monkeypatch, control.removeprefix("workflow_") + "_curve")
    elif control == "studio_dsc":
        assertions.test_studio_dsc_source_binding_uses_the_shared_source_tree_hash(tmp_path, monkeypatch)
    elif control == "without_snapshot":
        assertions.test_workflow_source_binding_without_snapshot_hashes_live_and_archive(tmp_path, monkeypatch)
    else:
        assertions.test_workflow_source_binding_rejects_drifted_archive_for_paired_snapshot(tmp_path, monkeypatch)


def test_generated_saxs_log_exclusions_are_dynamic_and_keep_original_values(tmp_path: Path) -> None:
    source = tmp_path / "generated_saxs.csv"
    source.write_text("Cedar,Cedar,Birch,Birch\nq (nm^-1),Intensity (a.u.),q (nm^-1),Intensity (a.u.)\n"
                      ".1,0,.2,-3\n.3,4,.5,2\n.7,-1,.8,6\n.9,8,,\n")
    original = source.read_bytes()
    resolved = resolve_scientific_source(source, rule_id="saxs_profile", template="curve", request={})
    assert resolved is not None
    transform = resolved.require_domain(ResolvedScientificTransform)
    assert tuple(series.points for series in transform.series) == (((.3, 4.), (.9, 8.)), ((.5, 2.), (.8, 6.)))
    prepared = prepare_semantic_source(source, output_dir=tmp_path / "prepared", semantic={"rule_id": "saxs_profile", "semantic_family": "saxs_profile"}, resolved_scientific_source=resolved)
    diagnostics = prepared["transform_steps"][0]["parameters"]["source_selections"]
    assert [row["excluded_nonpositive_log_y_count"] for row in diagnostics] == [2, 1]
    assert source.read_bytes() == original


def test_generated_swelling_snapshot_reaches_shared_terminal_without_reparse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import test_swelling_single_snapshot as assertions
    source = tmp_path / "generated_swelling.xlsx"
    pd.DataFrame([["Condition Cedar", None], ["1", None], ["Time (min)", "Swelling ratio"],
                  [0, 1.], [30, 1.4], [60, 1.9], [90, 2.1]]).to_excel(source, header=False, index=False)
    original = source.read_bytes()
    monkeypatch.setattr(assertions, "resolve_fixture_path", lambda _identifier: source)
    assertions.test_swelling_prepare_and_terminals_reuse_one_resolved_snapshot(tmp_path, monkeypatch)
    assert source.read_bytes() == original


@pytest.mark.parametrize("control", ("snapshot", "during_load_drift"))
def test_generated_temperature_domain_snapshot_controls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, control: str) -> None:
    source = temperature_source(tmp_path / "raw")
    if control == "snapshot":
        import test_scientific_source_pipeline as assertions
        monkeypatch.setattr(assertions, "resolve_fixture_path", lambda _id: source)
        assertions.test_rheology_temperature_snapshot_drives_plan_and_prepare_without_reparse(tmp_path, monkeypatch)
    else:
        import test_resolved_temperature_figure_plan as assertions
        monkeypatch.setattr(assertions, "_fixture", lambda: source)
        assertions.test_temperature_resolution_rejects_source_drift_during_load(monkeypatch)


@pytest.mark.parametrize("control", ("summary_options", "shared_route"))
def test_generated_mechanical_task_style_and_shared_preparation_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, control: str) -> None:
    source = mechanical_source(tmp_path / "raw", "compression_curve")
    if control == "summary_options":
        import test_mechanical_task_options as assertions
        monkeypatch.setattr(assertions, "resolve_fixture_path", lambda _id: source)
        assertions.test_summary_tasks_keep_style_without_curve_axis_or_series_options(tmp_path)
    else:
        import test_mechanical_workflow_route as assertions
        monkeypatch.setattr(assertions, "resolve_fixture_path", lambda _id: source)
        assertions.test_direct_mechanical_plan_uses_shared_semantic_preparation(tmp_path, monkeypatch)


@pytest.mark.parametrize("rule_id", ("uvvis_spectrum", "dma_frequency_sweep"))
def test_generated_study_model_artifacts_bind_exact_selected_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rule_id: str) -> None:
    import test_study_model_artifact_binding as assertions
    source, _ = paired_source(tmp_path / "raw", rule_id)
    monkeypatch.setattr(assertions, "resolve_fixture_path", lambda _id: source)
    if rule_id == "uvvis_spectrum":
        assertions.test_uvvis_recommendation_uses_the_resolved_plan_task_identity(tmp_path)
    else:
        assertions.test_registered_single_curve_plan_replaces_the_generic_study_queue(tmp_path)


@pytest.mark.parametrize("rule_id", ("dsc_curve", "rheology_stress_relaxation"))
def test_generated_generic_plan_uses_shared_terminal_and_studio_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rule_id: str) -> None:
    import test_generic_single_task_plan as assertions
    if rule_id == "dsc_curve":
        source, _ = paired_source(tmp_path / "raw", rule_id)
        monkeypatch.setattr(assertions, "resolve_fixture_path", lambda _id: source)
        assertions.test_dsc_rule_uses_the_shared_generic_studio_queue()
    else:
        source = tmp_path / "generated_relaxation.csv"
        source.write_text("Time,Shear Stress\ns,Pa\nCedar,Cedar\n.17,12\n.41,6\n.89,3\n")
        monkeypatch.setattr(assertions, "resolve_fixture_path", lambda _id: source)
        assertions.test_stress_plan_uses_shared_bundle_and_generic_studio_queue(tmp_path, monkeypatch)


def test_generated_dsc_metrics_never_assign_transition_identity(tmp_path: Path) -> None:
    from sciplot_core.materials_rules import compute_analysis_metrics
    source, _ = paired_source(tmp_path / "raw", "dsc_curve")
    metrics = compute_analysis_metrics(source_path=source, processed_source=None, semantic={"rule_id": "dsc_curve", "axis_plan": {}}, output_dir=tmp_path / "analysis")
    assert {item["metric"] for item in metrics} == {
        f"{metric}[{sample}]" for metric in ("maximum_absolute_heat_flow_slope_temperature_C", "maximum_absolute_heat_flow_temperature_C")
        for sample in ("Generated Cedar", "Generated Birch")}
    assert all("tg" not in item["metric"].lower() for item in metrics)


@pytest.mark.comprehensive
def test_generated_temperature_native_delivers_exact_two_metric_documents(tmp_path: Path) -> None:
    from sciplot_core import workflow
    source = temperature_source(tmp_path / "raw")
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    output = tmp_path / "output"
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"input": str(source), "output": str(output), "rule_id": "rheology_temperature_sweep",
                                   "template": "point_line", "explicit_template_selection": True,
                                   "explicit_render_option_keys": [], "exports": ["pdf", "tiff_300"]}))
    manifest = workflow.run_request(request)
    plan = ResolvedFigurePlan.from_payload(manifest["resolved_figure_plan"])
    assert plan.selected_figure_ids == ("storage_modulus_vs_temperature", "tan_delta_vs_temperature")
    assert len(manifest["result"]["veusz_documents"]) == 2
    assert len(manifest["result"]["veusz_specs"]) == 2
    assert len(manifest["result"]["exports"]) == 4
    assert all(Path(item["path"]).stat().st_size > 0 for item in manifest["result"]["exports"])
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before
