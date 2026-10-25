"""The real workflow/store composition publishes once after private preparation."""

import json

import pytest

from sciplot_core.project_store import FileProjectStore, ResourceRoot
from sciplot_core.studio_core import preparation_commands
from sciplot_core.workflow.project_requests import run_project_request


def prepared(tmp_path):
    project, delivery = tmp_path / "project", tmp_path / "delivery"
    project.mkdir()
    delivery.mkdir()
    (project / "source.csv").write_bytes(b"x,y\n1,2\n")
    request = {"input": "source.csv", "output": str(project / "runs/run_001"), "delivery_output": str(delivery)}
    (project / "plot_request.json").write_text(json.dumps(request))
    (project / "intake_manifest.json").write_text(json.dumps({"kind": "sciplot_intake_project", "version": 1, "project_slug": "project"}))
    store = FileProjectStore(project, locations={"delivery": delivery, "snapshot": ResourceRoot(tmp_path, ("project.zip",))})
    before = store.snapshot(import_legacy=True)
    return project, request, store, before


def execution(events, project, original):
    def execute(**kwargs):
        assert (project / "plot_request.json").read_bytes() == original
        assert not (project / "runs/run_001").exists()
        output = kwargs["output_dir"]
        (output / "run-evidence.txt").write_bytes(b"prepared analysis")
        private, _logical = kwargs["staged_delivery"]
        private.mkdir(parents=True, exist_ok=True)
        (private / "incomplete.txt").write_bytes(b"not a usable delivery")
        events.append("analysis")
        return {"created_at": "2026-10-25T20:00:00Z", "figures": [], "result": {},
                "output": str(output), "request_path": str(kwargs["request_path"]),
                "delivery_package": {"complete": False, "path": str(private)}, "ready_to_use": False}
    return execute


def test_complete_workflow_generation_contains_native_run_manifest_and_matching_zip(tmp_path, monkeypatch):
    project, request, store, before = prepared(tmp_path)
    original = (project / "plot_request.json").read_bytes()
    events = []
    def prepare(candidate, **kwargs):
        assert (project / "plot_request.json").read_bytes() == original
        assert not (project / "studio/document.vsz").exists()
        path = candidate.project_dir / "studio/document.vsz"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"synthetic native candidate")
        events.append("native")
        return {"document": str(path)}
    monkeypatch.setattr(preparation_commands, "prepare_studio_candidate", prepare)
    monkeypatch.setattr(preparation_commands, "audit_studio_candidate", lambda candidate, payload: ([{"kind": "synthetic-native-port"}], []))
    result = run_project_request(project / "plot_request.json", request, execute=execution(events, project, original),
        classifier=lambda *a, **k: {}, new_creation=False, previous_request=None)
    after = store.snapshot()
    assert after["sequence"] == before["sequence"] + 1
    assert after["projection_status"] == "current"
    assert events == ["analysis", "native"]
    assert result["output"] == str(project / "runs/run_001")
    assert (project / "studio/document.vsz").read_bytes() == b"synthetic native candidate"
    assert not list((tmp_path / "delivery").iterdir())
    assert (project / "runs/run_001/run-evidence.txt").read_bytes() == b"prepared analysis"
    assert (project / "source.csv").read_bytes() == b"x,y\n1,2\n"
    import zipfile
    with zipfile.ZipFile(tmp_path / "project.zip") as archive:
        assert archive.read("project/studio/document.vsz") == (project / "studio/document.vsz").read_bytes()
        assert archive.read("project/intake_manifest.json") == (project / "intake_manifest.json").read_bytes()


def test_failed_native_audit_does_not_publish_any_analysis_or_project_members(tmp_path, monkeypatch):
    project, request, store, before = prepared(tmp_path)
    original = (project / "plot_request.json").read_bytes()
    monkeypatch.setattr(preparation_commands, "prepare_studio_candidate", lambda candidate, **kwargs: {})
    def reject(*args):
        raise ValueError("exact native audit failed")
    monkeypatch.setattr(preparation_commands, "audit_studio_candidate", reject)
    with pytest.raises(ValueError, match="exact native audit failed"):
        run_project_request(project / "plot_request.json", request, execute=execution([], project, original),
            classifier=lambda *a, **k: {}, new_creation=False, previous_request=None)
    assert store.snapshot()["generation"] == before["generation"]
    assert (project / "plot_request.json").read_bytes() == original
    assert not (project / "runs").exists()
    assert not (tmp_path / "project.zip").exists()
    assert not list((tmp_path / "delivery").iterdir())
