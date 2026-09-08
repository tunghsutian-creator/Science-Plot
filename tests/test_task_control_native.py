from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.control_results import compact_result


def _cli(*args: object) -> dict:
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, args), "--json"],
                            cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.comprehensive
def test_public_task_creation_annotation_review_export_and_continuation(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance\nnm,a.u.\nE3,E3\n400,1\n425,2\n450,4\n475,2\n500,1\n")
    original = file_sha256(source)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"version": 1, "action": "create", "source": str(source)}))
    created = _cli("task", "start", "--request", request)
    assert created["status"] == "complete"
    assert created["result"]["kind"] == "sciplot_project_creation_result"
    project = Path(created["project"])
    before_lookup = {str(p): file_sha256(p) for p in project.rglob("*") if p.is_file()}
    found = _cli("task", "find", source)
    assert found["match_count"] == 1 and found["scan_complete"]
    assert found["matches"][0]["task_dir"] == created["task_dir"]
    assert found["matches"][0]["source_current"] is True
    project = Path(found["matches"][0]["project"])
    assert {str(p): file_sha256(p) for p in project.rglob("*") if p.is_file()} == before_lookup
    figure_id = created["result"]["primary_figure_id"]
    inspected = _cli("project", "inspect", project, "--figure", figure_id)
    figure = inspected["selected_figure"]
    request.write_text(json.dumps({
        "version": 1, "action": "edit", "project": str(project), "figure_id": figure_id,
        "expected_document_sha256": figure["document_sha256"], "operations": [{
            "op": "add_reference_line", "id": "reference450", "parent_path": "/page1/graph1",
            "axis": "x", "value": 450, "unit": "nm",
        }],
    }))
    review = _cli("task", "start", "--request", request, "--task-dir", tmp_path / "edit")
    assert review["status"] == "needs_review"
    assert Path(review["preview"]["image"]["path"]).is_file()
    assert file_sha256(Path(figure["document"])) == figure["document_sha256"]
    response = tmp_path / "accept.json"
    response.write_text('{"accept_preview":true}')
    applied = _cli("task", "resume", review["task_dir"], "--response", response)
    assert applied["status"] == "complete"
    assert applied["result"]["studio_run"]["ready_to_use"] is True
    current = _cli("task", "inspect", applied["task_dir"])
    assert current["current_project"]["delivery"]["current"] is True
    inventory = sorted((project / "runs").glob("studio_*"))
    again = _cli("task", "resume", review["task_dir"], "--response", response)
    assert again["status"] == "complete"
    assert sorted((project / "runs").glob("studio_*")) == inventory
    assert file_sha256(source) == original
    recovered = _cli("task", "find", source)
    assert recovered["matches"][0]["project"] == str(project)
    assert _cli("task", "inspect", recovered["matches"][0]["task_dir"])["current_project"]["qa"]["current"] is True


@pytest.mark.comprehensive
def test_three_sample_style_rounds_save_without_export_then_publish_current_data(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
                      "E0,E0,E3,E3\n400,1,400,2\n425,2,425,3\n450,4,450,5\n475,2,475,3\n500,1,500,2\n")
    original = source.read_bytes()
    request = tmp_path / "request.json"
    response = tmp_path / "response.json"
    response.write_text('{"accept_preview":true}')
    request.write_text(json.dumps({"version": 1, "action": "create", "source": str(source)}))
    created = _cli("task", "start", "--request", request, "--task-dir", tmp_path / "create")
    assert created["status"] == "complete"
    project = Path(created["project"])
    figure_id = created["result"]["primary_figure_id"]
    initial = _cli("project", "inspect", project, "--figure", figure_id)
    full = _cli("project", "inspect", project, "--figure", figure_id, "--full")
    assert initial == compact_result(full)
    def size(payload):
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    assert size(initial) < size(full) * 0.4
    assert [item["sample"] for item in initial["selected_figure"]["sample_styles"]] == ["E0", "E3"]
    selected = initial["selected_figure"]
    document = Path(selected["document"])
    revision = selected["document_sha256"]
    delivery = Path(created["result"]["studio_run"]["delivery_package"]["path"])
    before_delivery = {str(p.relative_to(delivery)): file_sha256(p) for p in delivery.rglob("*") if p.is_file()}
    before_runs = sorted((project / "runs").glob("studio_*"))
    rounds = [
        [{"op": "set_sample_style", "samples": ["E0", "E3"], "style": {"width": "1.5pt"}}],
        [{"op": "set_sample_style", "samples": ["E3"], "style": {"color": "#C83E4D"}}],
        [{"op": "set_sample_style", "samples": ["E0"], "style": {"color": "#2A9D8F"}},
         {"op": "set_sample_style", "samples": ["E3"], "style": {"color": "#3568C0"}},
         {"op": "set_sample_style", "samples": ["E0", "E3"], "style": {"width": "2pt"}}],
    ]
    for index, operations in enumerate(rounds):
        request.write_text(json.dumps({"version": 1, "action": "edit", "project": str(project),
                                      "figure_id": figure_id, "expected_document_sha256": revision,
                                      "operations": operations, "export": False}))
        review = _cli("task", "start", "--request", request, "--task-dir", tmp_path / f"round_{index}")
        assert review["status"] == "needs_review"
        if index == 0:
            first_id = review["operation_id"]
            previous_image = Path(review["preview"]["image"]["path"])
            previous_bytes = previous_image.read_bytes()
            response.write_text(json.dumps({"expected_operation_id": first_id,
                "revise_operations": [{"op": "set_sample_style", "samples": ["E0", "E3"], "style": {"width": "1.75pt"}}]}))
            review = _cli("task", "resume", review["task_dir"], "--response", response)
            assert review["preview_revision"] == 2 and review["operation_id"] != first_id
            assert previous_image.read_bytes() == previous_bytes
            assert _cli("task", "resume", review["task_dir"], "--response", response) == review
            assert len(list(Path(review["task_dir"]).glob("preview_*"))) == 2
        response.write_text(json.dumps({"accept_preview": True, "expected_operation_id": review["operation_id"]}))
        assert review["preview"]["scientific_audit"]["status"] == "passed"
        assert file_sha256(document) == revision
        signed = json.loads(Path(review["preview"]["review_path"]).read_text())
        assert all(op["op"] == "set_style" for op in signed["operations"])
        saved = _cli("task", "resume", review["task_dir"], "--response", response)
        assert saved["status"] == "complete" and saved["result"]["status"] == "saved"
        assert saved["result"]["ready_to_use"] is False and saved["result"]["export_performed"] is False
        assert "preview" not in saved
        revision = saved["result"]["document_sha256"]
        assert file_sha256(document) == revision
        assert sorted((project / "runs").glob("studio_*")) == before_runs
        assert {str(p.relative_to(delivery)): file_sha256(p) for p in delivery.rglob("*") if p.is_file()} == before_delivery
        assert _cli("task", "resume", review["task_dir"], "--response", response) == saved
    current = _cli("task", "inspect", saved["task_dir"])
    assert current["current_project"]["delivery"]["current"] is False
    request.write_text(json.dumps({"version": 1, "action": "export", "project": str(project)}))
    exported = _cli("task", "start", "--request", request, "--task-dir", tmp_path / "export")
    assert exported["result"]["studio_run"]["ready_to_use"] is True
    assert len(list((project / "runs").glob("studio_*"))) == len(before_runs) + 1
    assert file_sha256(document) == revision
    final = _cli("project", "inspect", project, "--figure", figure_id)
    assert final["qa"]["current"] is True and final["delivery"]["current"] is True
    for path, color in (("/page1/graph1/series_1", "#2A9D8F"), ("/page1/graph1/series_2", "#3568C0")):
        fields = {f["setting_path"]: f["current_value"] for f in final["selected_figure"]["objects"][path]["editable_fields"]}
        assert fields[path + "/PlotLine/color"] == color
        assert fields[path + "/PlotLine/width"] == "2pt"
    stable_document = document.read_bytes()
    stable_spec = Path(final["selected_figure"]["spec"]).read_bytes()
    stable_runs = sorted((project / "runs").glob("studio_*"))
    stable_delivery = {str(p.relative_to(delivery)): file_sha256(p) for p in delivery.rglob("*") if p.is_file()}
    request.write_text(json.dumps({"version": 1, "action": "edit", "project": str(project),
        "figure_id": figure_id, "expected_document_sha256": revision, "export": False,
        "operations": [{"op": "set_sample_style", "samples": ["E0", "E3"], "style": {"width": "2pt"}}]}))
    unchanged = _cli("task", "start", "--request", request, "--task-dir", tmp_path / "unchanged")
    assert unchanged["status"] == "complete" and unchanged["result"]["status"] == "unchanged"
    assert "preview" not in unchanged and unchanged["result"]["document_sha256"] == revision
    assert _cli("task", "start", "--request", request, "--task-dir", tmp_path / "unchanged") == unchanged
    assert document.read_bytes() == stable_document and Path(final["selected_figure"]["spec"]).read_bytes() == stable_spec
    assert sorted((project / "runs").glob("studio_*")) == stable_runs
    assert {str(p.relative_to(delivery)): file_sha256(p) for p in delivery.rglob("*") if p.is_file()} == stable_delivery
    assert source.read_bytes() == original
