"""Generated grouped-summary clearance keeps the exact original scientific groups."""
from copy import deepcopy

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.current_layout_review import LEGEND_ISSUE
from sciplot_core.studio_core.review_artifacts import _current_layout_issues
from sciplot_core.studio_render.component_legend import component_legend_spec
from sciplot_core.studio_render.readability_defaults import _apply_readability_render_defaults
from sciplot_core.studio_render.replicate_distribution_contract import _replicate_distribution_contract
from sciplot_core.studio_render.segmented_legend_clearance import segmented_legend_placement
from sciplot_core.studio_render.series_domain import _resolved_domain_render_options
from sciplot_core.studio_render.style_contract import _veusz_style_contract
from test_task_ordinary_categorical import _binding, _derive

ORIGINAL = ("Sample,Condition,Strength (MPa)\nQ,dry,1.3\nP,wet,3.2\nQ,wet,2.1\nP,dry,1.8\n"
            "Q,dry,1.7\nP,wet,3.6\nQ,wet,2.5\nP,dry,2.2\nQ,dry,1.5\n")


def summary_case(tmp_path, mode="mean_sample_sd_n"):
    source = tmp_path / "readings.csv"
    source.write_text(ORIGINAL)
    binding = _binding(source, mode, category_order=["P", "Q"], condition_order=["dry", "wet"])
    request = {"template": "bar", "categorical_binding": binding, "render_options": {"legend_position": "auto"}}
    series, axis = _derive(source, binding)
    options = _resolved_domain_render_options(request, axis_info=axis, series=series)
    return source, request, series, axis, options


@pytest.mark.parametrize("mode", ["mean_sample_sd", "mean_sample_sd_n"])
def test_original_high_first_summary_uses_bounded_headroom_and_preserves_all_science(tmp_path, mode):
    from sciplot_core.studio_core.legend_specs import _categorical_component_legend_spec
    from sciplot_core.policy import MAX_LINEAR_LEGEND_RESERVE_FRACTION

    source, request, series, axis, options = summary_case(tmp_path, mode)
    assert file_sha256(source) == "0d684ec43017ff7fa28068d6ef35ac4b5b08678ada014afb5e05dbd18b51ee4c"
    before = deepcopy(series)
    contract = _replicate_distribution_contract(series, template_id="bar", render_options=options)
    initial = segmented_legend_placement(series, options, request=request, template_id="bar")
    assert initial["minimum_curve_clearance_mm"] == 0
    updated = _apply_readability_render_defaults(options, request=request, axis_info=axis,
        series=series, template_id="bar")
    placement = updated["_legend_placement_diagnostics"]
    assert placement["clearance_status"] == "safe"
    reserve = placement["axis_reserve"]
    assert reserve["side"] == "top" and updated["y_min"] == 0
    assert reserve["axis_units"] <= (initial["measurement_axes"]["y"][1]
        - initial["measurement_axes"]["y"][0]) * MAX_LINEAR_LEGEND_RESERVE_FRACTION + 1e-6
    assert series == before
    assert _replicate_distribution_contract(series, template_id="bar", render_options=updated) == contract
    assert _categorical_component_legend_spec is component_legend_spec
    assert file_sha256(source) == request["categorical_binding"]["source_sha256"]


def test_explicit_summary_upper_bound_is_not_changed_to_hide_overlap(tmp_path):
    _, request, series, axis, options = summary_case(tmp_path)
    options["y_max"] = 3.7
    request["render_options"]["y_max"] = 3.7
    updated = _apply_readability_render_defaults(options, request=request, axis_info=axis,
        series=series, template_id="bar")
    assert updated["y_max"] == 3.7
    assert updated["_legend_placement_diagnostics"]["minimum_curve_clearance_mm"] == 0
    assert "axis_reserve" not in updated["_legend_placement_diagnostics"]


@pytest.mark.parametrize("mutation", ["clear", "overlap", "stale", "missing_label", "missing_bar", "unknown", "outside"])
def test_actual_summary_qa_requires_matching_bytes_complete_marks_and_no_overlap(tmp_path, mutation):
    from sciplot_core.studio_core.guide_contracts import categorical_line_contracts
    from sciplot_core.studio_core.legend_contracts import (
        categorical_component_legend_label_contracts, categorical_component_legend_rect_contracts,
        categorical_grouped_bar_fill_rect_contracts,
    )

    _, request, series, _, options = summary_case(tmp_path)
    categorical = _replicate_distribution_contract(series, template_id="bar", render_options=options)
    legend = component_legend_spec(categorical, style=_veusz_style_contract(options))
    spec = {"template": "bar", "source_request": request, "legend": {"show": True, **legend},
        "categorical": categorical, "style": {"axis_linewidth_pt": .8},
        "axes": {"x": {"min": .5, "max": 2.5}, "y": {"min": 0, "max": 5}}}
    paths = ["/page1/graph1/" + item["name"] for item in
        categorical_component_legend_label_contracts(spec) + categorical_component_legend_rect_contracts(spec)]
    data = ["/page1/graph1/" + item["name"] for item in
        categorical_grouped_bar_fill_rect_contracts(spec) + categorical_line_contracts(spec)]
    document = tmp_path / "bound-native-bytes.bin"
    document.write_bytes(b"generated byte-binding control; no native execution claimed")
    geometry = {"coverage_complete": True, "data_paths": data,
        "legends": [{"path": path, "graph_path": "/page1/graph1", "minimum_curve_clearance_mm":
                     0.0 if mutation == "overlap" else 3.0} for path in paths]}
    audit = {"path": str(document), "sha256": file_sha256(document), "segmented_legend_geometry": geometry}
    if mutation == "stale":
        audit["sha256"] = "0" * 64
    elif mutation == "missing_label":
        geometry["legends"].pop()
    elif mutation == "missing_bar":
        geometry["data_paths"].pop()
    elif mutation == "unknown":
        geometry["coverage_complete"] = False
    elif mutation == "outside":
        geometry["outside_plot_paths"] = [paths[0]]
    issues = _current_layout_issues(spec, document_path=document, native_audit=audit)
    assert any(item["severity"] == "critical" for item in issues) is (mutation != "clear")
    if mutation in {"clear", "overlap"}:
        assert issues[0]["id"] == LEGEND_ISSUE
        assert issues[0]["measurement_scope"] == "exact_current_native"


@pytest.mark.parametrize("case", ["clear", "outside", "overlap", "missing", "stale", "other-critical",
                                  "science-only", "non-summary", "unchanged-native"])
def test_generated_summary_layout_is_admitted_before_preparation_publication(tmp_path, monkeypatch, case):
    import json
    import subprocess

    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.source_coverage import document_audit
    from sciplot_core.studio_core import preparation_commands
    from sciplot_core.studio_core.guide_contracts import categorical_line_contracts
    from sciplot_core.studio_core.legend_contracts import (
        categorical_component_legend_label_contracts, categorical_component_legend_rect_contracts,
        categorical_grouped_bar_fill_rect_contracts,
    )
    from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
    from sciplot_core.studio_render.models import StudioPreparationBlocked

    def no_native_process(*_args, **_kwargs):
        pytest.fail("This controlled host-admission counter must not start a native process.")

    monkeypatch.setattr(subprocess, "Popen", no_native_process)
    source, request, series, _, options = summary_case(tmp_path)
    original = source.read_bytes()
    categorical = _replicate_distribution_contract(series, template_id="bar", render_options=options)
    legend = component_legend_spec(categorical, style=_veusz_style_contract(options))
    spec = {"template": "bar", "source_request": request, "legend": {"show": True, **legend},
        "categorical": categorical, "style": {"axis_linewidth_pt": .8},
        "axes": {"x": {"min": .5, "max": 2.5}, "y": {"min": 0, "max": 5}},
        "series": [{"source_artifacts": [{"path": str(source), "sha256": file_sha256(source)}]}]}
    paths = ["/page1/graph1/" + item["name"] for item in
        categorical_component_legend_label_contracts(spec) + categorical_component_legend_rect_contracts(spec)]
    data = ["/page1/graph1/" + item["name"] for item in
        categorical_grouped_bar_fill_rect_contracts(spec) + categorical_line_contracts(spec)]
    geometry = {"coverage_complete": True, "data_paths": data, "outside_plot_paths": [],
        "legends": [{"path": path, "graph_path": "/page1/graph1",
                     "minimum_curve_clearance_mm": 0.0 if case == "overlap" else 3.0} for path in paths]}
    if case in {"outside", "science-only", "non-summary", "unchanged-native"}:
        geometry["outside_plot_paths"] = [paths[0]]
    if case == "other-critical":
        spec["layout_issues"] = [{"id": "visual_extent_outside_explicit_axis", "axis": "y",
                                  "severity": "critical", "message": "Controlled generated axis conflict."}]
    elif case == "non-summary":
        spec["source_request"]["categorical_binding"]["mode"] = "given_values"
    project, delivery = tmp_path / "project", tmp_path / "visible"
    (project / "studio").mkdir(parents=True)
    (project / "plot_request.json").write_text(json.dumps({"input": str(source), "delivery_output": str(delivery)}))
    (project / "studio/spec.json").write_text(json.dumps(spec))
    (project / "studio/document.vsz").write_bytes(b"Controlled native input; its scientific audit is replaced in this pure host counter.")
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    members = {name: store.read_bytes(name) for name in before["files"]}
    calls = []

    def scientific_audit(*, document_path, spec_path, check_presentation):
        calls.append(check_presentation)
        value = {"status": "passed", "document": {"path": str(document_path),
            "sha256": "0" * 64 if case == "stale" else file_sha256(document_path)}}
        if case != "missing":
            value["segmented_legend_geometry"] = geometry
        return value, json.loads(spec_path.read_bytes())

    monkeypatch.setattr(document_audit, "_audit_exact_document_data", scientific_audit)
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        payload = {"document": str(candidate.project_dir / "studio/document.vsz")}
        if case == "unchanged-native":
            payload["preserved_existing_document"] = True
        expected_block = case in {"outside", "overlap", "missing", "stale", "other-critical"}
        if expected_block:
            with pytest.raises(StudioPreparationBlocked):
                preparation_commands.audit_studio_candidate(candidate, payload)
        else:
            preparation_commands.audit_studio_candidate(candidate, payload,
                **({"check_presentation": False} if case == "science-only" else {}))
    assert calls == ([] if case == "unchanged-native" else [case != "science-only"])
    assert not candidate.project_dir.exists() and not delivery.exists()
    assert source.read_bytes() == original
    assert store.snapshot()["generation"] == before["generation"] and not store.commands()
    assert {name: (project / name).read_bytes() for name in before["files"]} == members
