"""Real public task creation and native numerical audits on generated sources."""
import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256


def _cli(*args):
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, args), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=180, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.comprehensive
def test_public_raw_categorical_decimal_values_are_exact_in_saved_native_document(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from sciplot_core.studio_core.registry_state import _veusz_spec_path
    from sciplot_core.studio_core.document_edit_state import run_document_worker
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    tokens = ["0.12345678901234567", "1.0000000000000002", "2.3400000000000003", "0.12345678901234567"]
    expected = [float(value).hex() for value in tokens]
    source = tmp_path / "impact.csv"
    source.write_text("Impact strength\nkJ/m2\nAmber\n" + "\n".join(tokens) + "\n")
    original = file_sha256(source)
    created = _cli("task", "create", source, "--rule", "impact_metric", "--summary-statistic", "raw_only",
                   "--task-dir", tmp_path / "task")
    assert created["status"] == "complete", created
    document = Path(created["current_project"]["figures"][0]["document"])
    spec_path = _veusz_spec_path(document)
    spec = json.loads(spec_path.read_text())
    assert spec["source_numeric_encoding"] == "decimal_float64_round_trip_v1"
    assert [value.hex() for value in spec["series"][0]["y_values"]] == expected
    assert [value.hex() for value in spec["categorical"]["groups"][0]["raw_values"]] == expected
    assert spec["categorical"]["summary_calculation"] == "none"
    with loaded_native_document(document) as loaded:
        assert [float(value).hex() for value in loaded.data[spec["series"][0]["y_name"]].data] == expected
    assert run_document_worker("audit-spec-data", document, spec_path)["status"] == "passed"
    assert all(created["current_project"][key]["current"] for key in ("source", "qa", "delivery"))
    assert file_sha256(source) == original


@pytest.mark.comprehensive
def test_public_raw_categorical_points_native_has_every_duplicate_and_no_summary(tmp_path):
    from sciplot_core.studio_core.registry_state import _veusz_spec_path
    from sciplot_core.studio_core.document_edit_state import run_document_worker

    source = tmp_path / "impact.csv"
    source.write_text("Impact strength,Impact strength\nkJ/m2,kJ/m2\nB,A\n8,4\n8,\n8,7\n8,7\n8,\n")
    original = file_sha256(source)
    created = _cli("task", "create", source, "--rule", "impact_metric", "--summary-statistic", "raw_only",
                   "--task-dir", tmp_path / "task")
    assert created["status"] == "complete", created
    assert created["scientific_presentation"]["summary_statistic"] == "raw_only"
    assert created["scientific_presentation"]["statistics_contract"]["summary_calculation"] == "none"
    document = Path(created["current_project"]["figures"][0]["document"])
    spec_path = _veusz_spec_path(document)
    spec = json.loads(spec_path.read_text())
    categorical = spec["categorical"]
    assert categorical["summary_statistic"] == "raw_only"
    assert categorical["summary_calculation"] == "none"
    assert categorical["native_veusz_boxplot"] is False
    assert [group["label"] for group in categorical["groups"]] == ["B", "A"]
    assert [group["raw_values"] for group in categorical["groups"]] == [[8.] * 5, [4., 7., 7.]]
    assert all(group["raw_points_visible"] and not group["boxplot_eligible"] for group in categorical["groups"])
    assert all("descriptive_statistics" not in group for group in categorical["groups"])
    assert all(item["raw_points_visible"] for item in spec["series"])
    assert run_document_worker("audit-spec-data", document, spec_path)["status"] == "passed"
    assert all(created["current_project"][key]["current"] for key in ("source", "qa", "delivery"))
    assert all(Path(image).is_file() for image in created["next_step"]["images"])
    assert file_sha256(source) == original
    analysis_tables = list(Path(created["project"]).rglob("analysis_metrics.csv"))
    assert analysis_tables
    assert all(len(path.read_text().splitlines()) == 1 for path in analysis_tables)


@pytest.mark.comprehensive
def test_public_no_experiment_xy_creates_native_original_values_and_archives_context(tmp_path):
    import math
    from sciplot_core.plot_backends.managed_audit import scientific_audit
    from sciplot_core.plot_backends.native_primitives import dataset_name
    from sciplot_core.plot_engine.storage import load_head, read
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    source = tmp_path / "acquisition.csv"
    source.write_text("Temperature,Heat Flow\nC,W/g\nSample Z,Sample Z\n66,-0.023\n61,0.008\n61,\n53,-0.016\n")
    original = file_sha256(source)
    intent = {"x": {"quantity": "temperature"}, "y": {"quantity": "heat_flow"},
              "source_context": "Original cooling acquisition; no baseline correction, normalization or integration."}
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"version": 1, "action": "create", "sources": [str(source)], "intent": intent,
                                   "summary_statistic": "raw_only", "curve_display": "raw_overlay"}))
    created = _cli("task", "start", "--request", request, "--task-dir", tmp_path / "task")
    assert created["status"] == "complete", created
    assert created["scientific_presentation"]["rule_id"] == "ordinary_xy"
    assert created["scientific_presentation"]["summary_calculation"] == "none"
    state = json.loads((Path(created["task_dir"]) / "task.json").read_text())
    wire = state["managed_request"]
    assert wire["rule_id"] == "ordinary_xy"
    assert wire["data_binding"]["provenance"]["semantic_task"]["intent"] == intent
    assert {node["kind"] for node in wire["data_binding"]["transforms"]} <= {"select", "row_slice", "rename"}
    head = load_head(Path(created["project"]))
    ir = read(Path(head["binding"]["ir_path"]))
    layer = ir["views"][0]["layers"][0]
    assert all(scale["transform"] == "linear" for scale in ir["scales"])
    with loaded_native_document(Path(head["binding"]["document"])) as loaded:
        assert scientific_audit(ir, loaded)["status"] == "passed"
        assert loaded.data[dataset_name(layer["dataset_id"], "x")].data.tolist() == [66., 61., 61., 53.]
        actual_y = loaded.data[dataset_name(layer["dataset_id"], "y")].data.tolist()
        assert actual_y[:2] == [-.023, .008] and math.isnan(actual_y[2]) and actual_y[3] == -.016
    assert created["next_step"]["action"] == "review_exports_and_deliver"
    assert all(Path(image).is_file() for image in created["next_step"]["images"])
    assert file_sha256(source) == original
