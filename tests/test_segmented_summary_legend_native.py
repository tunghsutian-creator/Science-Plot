"""Public original-data summaries and exact-current native component clearance."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.mapping_contract.source_identity import source_view_id
from sciplot_core.qa.audit_support import _run_veusz_audit
from sciplot_core.studio_core.document_edit_state import run_document_worker
from sciplot_core.studio_core.review_artifacts import _current_layout_issues
from test_segmented_summary_legend import ORIGINAL
from test_task_ordinary_categorical_native import _binding, _cli, _cold_export, _document, _request


def _native_cells(loaded):
    return {name: ((data.data.dtype.str, data.data.shape, data.data.tobytes())
                  if hasattr(data.data, "tobytes") else tuple(data.data))
            for name, data in loaded.data.items()}


@pytest.mark.comprehensive
@pytest.mark.parametrize("mode", ["mean_sample_sd", "mean_sample_sd_n"])
def test_public_original_high_first_summary_exports_clear_native_component_legend(tmp_path, mode, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    source = tmp_path / "readings.csv"
    source.write_text(ORIGINAL)
    original = file_sha256(source)
    assert original == "0d684ec43017ff7fa28068d6ef35ac4b5b08678ada014afb5e05dbd18b51ee4c"
    binding = _binding(source, mode, category_order=["P", "Q"], condition_order=["dry", "wet"],
        category_aliases={"P": "Control", "Q": "Treated"},
        series_styles=[{"label": "dry", "color": "#215977"}, {"label": "wet", "color": "#B65B43"}])
    created = _cli("task", "start", "--request", _request(tmp_path, source, binding),
        "--task-dir", tmp_path / "task")
    assert created["status"] == "complete", created
    document, spec_path, spec = _document(created)
    groups = spec["categorical"]["groups"]
    assert [group["raw_values"] for group in groups] == [[1.8, 2.2], [3.2, 3.6], [1.3, 1.7, 1.5], [2.1, 2.5]]
    assert [group["bar_mean"] for group in groups] == pytest.approx([2., 3.4, 1.5, 2.3])
    assert [group["bar_error"] for group in groups] == pytest.approx([.2 * 2**.5, .2 * 2**.5, .2, .2 * 2**.5])
    assert [group["replicate_count"] for group in groups] == [2, 2, 3, 2]
    # Creation labels become ID-bound styles; physical factors remain P/Q and dry/wet.
    namespace = str(source.resolve())
    expected_groups = [{"version": 1, "source_namespace": namespace,
        "source_id": source_view_id(namespace, binding["table_selection"], [0, 1, 2],
            selector={"sample": sample, "condition": condition}),
        "sample": sample, "category": sample, "condition": condition}
        for sample in ("P", "Q") for condition in ("dry", "wet")]
    assert len({group["source_id"] for group in expected_groups}) == 4
    assert [item["source_binding"] for item in spec["series"]] == expected_groups
    assert [group["source_binding"] for group in groups] == expected_groups
    assert [item["name"] for item in spec["series"]] == [group["source_id"] for group in expected_groups]
    assert [item["label"] for item in spec["series"]] == [
        "Control || dry", "Control || wet", "Treated || dry", "Treated || wet"]
    assert [item["color"] for item in spec["series"]] == ["#215977", "#B65B43", "#215977", "#B65B43"]
    saved_binding = spec["source_request"]["categorical_binding"]
    assert type(saved_binding["source_identity_version"]) is int
    assert saved_binding == {**binding, "source_identity_version": 1, "source_namespace": namespace,
        # Styles retain the request's condition-major order, independently of draw order.
        "series_styles": [
            {"label": "Control || dry", "color": "#215977", "series_id": expected_groups[0]["source_id"]},
            {"label": "Treated || dry", "color": "#215977", "series_id": expected_groups[2]["source_id"]},
            {"label": "Control || wet", "color": "#B65B43", "series_id": expected_groups[1]["source_id"]},
            {"label": "Treated || wet", "color": "#B65B43", "series_id": expected_groups[3]["source_id"]}]}
    assert spec["axes"]["x"]["category_labels"] == ["Control", "Treated"]
    placement = spec["legend"]["placement_diagnostics"]
    assert placement["axis_reserve"]["side"] == "top" and spec["axes"]["y"]["min"] == 0
    audit, error = _run_veusz_audit([document])
    assert error is None
    actual = audit["documents"][0]
    geometry = actual["segmented_legend_geometry"]
    assert geometry["coverage_complete"] and len(geometry["legends"]) == 6, geometry
    assert min(item["minimum_curve_clearance_mm"] for item in geometry["legends"]) >= placement["required_curve_clearance_mm"]
    issues = _current_layout_issues(spec, document_path=document, native_audit=actual)
    assert not any(item["severity"] == "critical" for item in issues)
    journal = json.loads((Path(created["task_dir"]) / "task.json").read_text())
    manifest = json.loads(Path(journal["result"]["studio_run"]["manifest"]).read_text())
    assert manifest["qa"]["studio_layout"]["status"] == "passed"
    assert manifest["qa"]["publication"]["veusz_document_audit"]["documents"][0]["segmented_legend_geometry"]["coverage_complete"]
    assert run_document_worker("audit-spec-data", document, spec_path)["status"] == "passed"
    cold = _cold_export(tmp_path, created["project"])
    assert cold["status"] == "complete" and all(Path(path).is_file() for path in cold["next_step"]["images"])

    # Recreate the prior colliding viewport through the native API. Raw dataset
    # cells and the complete mean/SD/n source contract remain untouched.
    bad = tmp_path / "colliding_native.vsz"
    with loaded_native_document(document) as loaded:
        from veusz.document import CommandInterface

        before = _native_cells(loaded)
        ci = CommandInterface(loaded)
        ci.Set("/page1/graph1/y/max", 3.7)
        for index, group in enumerate(groups, 1):
            ci.Set(f"/page1/graph1/categorical_bar_fill_{index}/height", [group["bar_mean"] / 3.7])
        ci.Save(str(bad))
        assert _native_cells(loaded) == before
    bad_spec = deepcopy(spec)
    bad_spec["axes"]["y"]["max"] = 3.7
    bad_audit, error = _run_veusz_audit([bad])
    assert error is None
    bad_actual = bad_audit["documents"][0]
    assert bad_actual["segmented_legend_geometry"]["coverage_complete"]
    assert any(item["minimum_curve_clearance_mm"] == 0 for item in bad_actual["segmented_legend_geometry"]["legends"])
    bad_issues = _current_layout_issues(bad_spec, document_path=bad, native_audit=bad_actual)
    assert any(item["id"] == "legend_curve_clearance_below_target" and item["severity"] == "critical" for item in bad_issues)
    assert bad_spec["categorical"] == spec["categorical"] and file_sha256(source) == original
    (tmp_path / "geometry_evidence.json").write_text(json.dumps({"original_source_sha256": original,
        "complete_groups": groups, "final_native_audit": actual, "colliding_native_audit": bad_actual,
        "current_issues": issues, "colliding_issues": bad_issues}, ensure_ascii=False, indent=2))


@pytest.mark.comprehensive
def test_public_dense_component_labels_remain_blocked_in_fixed_frame(tmp_path):
    source = tmp_path / "dense.csv"
    condition = "Very long measurement condition " * 4
    source.write_text("Sample,Condition,Strength (MPa)\n" + "".join(
        f"{sample},{condition}{condition_index},{value}\n"
        for sample in ("P", "Q") for condition_index in (1, 2) for value in (2, 3)))
    original = file_sha256(source)
    binding = _binding(source, "mean_sample_sd", category_order=["P", "Q"])
    result = _cli("task", "start", "--request", _request(tmp_path, source, binding),
        "--task-dir", tmp_path / "task", success=False)
    assert result["status"] == "blocked", result
    assert not (tmp_path / "dense_SciPlot").exists() and file_sha256(source) == original
