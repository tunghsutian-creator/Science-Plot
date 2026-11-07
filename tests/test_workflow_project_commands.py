"""The real workflow/store composition publishes once after private preparation."""

import json

import pytest

from sciplot_core.project_store import FileProjectStore, ResourceRoot
from sciplot_core.studio_core import preparation_commands
from sciplot_core.workflow.project_requests import run_project_request


def prepared(tmp_path, *, previous_delivery=None, delivery_files=None):
    project, delivery = tmp_path / "project", tmp_path / "delivery"
    project.mkdir()
    delivery.mkdir()
    for name, content in (delivery_files or {}).items():
        member = delivery / name
        member.parent.mkdir(parents=True, exist_ok=True)
        member.write_bytes(content)
    (project / "source.csv").write_bytes(b"x,y\n1,2\n")
    request = {"input": "source.csv", "output": str(project / "runs/run_001"), "delivery_output": str(delivery)}
    (project / "plot_request.json").write_text(json.dumps(request))
    registry = {"kind": "sciplot_intake_project", "version": 1, "project_slug": "project"}
    if previous_delivery is not None:
        registry["delivery_package"] = previous_delivery
    (project / "intake_manifest.json").write_text(json.dumps(registry))
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


def test_request_preparation_forwards_committed_delivery_evidence(tmp_path, monkeypatch):
    # This opaque record tests transport, not acceptance of any historical file.
    previous = {"fixture": "committed delivery evidence", "version": 6}
    project, request, store, before = prepared(tmp_path, previous_delivery=previous)
    original = (project / "plot_request.json").read_bytes()
    execute = execution([], project, original)
    observed = []

    def prepare(**kwargs):
        observed.append(kwargs["previous_delivery"])
        return execute(**kwargs)

    monkeypatch.setattr(preparation_commands, "prepare_studio_candidate", lambda *_a, **_k: {})
    monkeypatch.setattr(preparation_commands, "audit_studio_candidate", lambda *_a: ([], []))
    run_project_request(project / "plot_request.json", request, execute=prepare,
        classifier=lambda *a, **k: {}, new_creation=False, previous_request=None)
    assert observed == [previous]
    assert store.snapshot()["sequence"] == before["sequence"] + 1
    assert (project / "source.csv").read_bytes() == b"x,y\n1,2\n"
    assert not list((tmp_path / "delivery").iterdir())


def test_complete_workflow_publishes_the_capture_delta_without_deleting_unchanged_members(tmp_path, monkeypatch):
    from sciplot_core.policy import DELIVERY_DATA_DIR, DELIVERY_PDF_DIR, DELIVERY_TIFF_DIR

    initial = {f"{DELIVERY_DATA_DIR}/stable.csv": b"unchanged generated table", f"{DELIVERY_TIFF_DIR}/stable.tiff": b"unchanged generated image",
               f"{DELIVERY_PDF_DIR}/replaced.pdf": b"old export", f"{DELIVERY_DATA_DIR}/retired.csv": b"old output no longer produced"}
    project, request, store, before = prepared(tmp_path, delivery_files=initial)
    current = {f"{DELIVERY_DATA_DIR}/stable.csv": initial[f"{DELIVERY_DATA_DIR}/stable.csv"], f"{DELIVERY_TIFF_DIR}/stable.tiff": initial[f"{DELIVERY_TIFF_DIR}/stable.tiff"],
               f"{DELIVERY_PDF_DIR}/replaced.pdf": b"new export", f"{DELIVERY_PDF_DIR}/added.pdf": b"additional export"}

    def execute(**kwargs):
        output = kwargs["output_dir"]
        (output / "run-evidence.txt").write_bytes(b"controlled native publication port")
        private, _logical = kwargs["staged_delivery"]
        retired = private / DELIVERY_DATA_DIR / "retired.csv"
        assert retired.read_bytes() == initial[f"{DELIVERY_DATA_DIR}/retired.csv"]
        retired.unlink()  # An actual removal in the host-owned private candidate.
        for name, content in current.items():
            member = private / name
            member.parent.mkdir(parents=True, exist_ok=True)
            member.write_bytes(content)
        return {"created_at": "2026-11-07T18:00:00Z", "figures": [], "result": {},
                "output": str(output), "request_path": str(kwargs["request_path"]),
                "delivery_package": {"complete": True, "path": str(private)}, "ready_to_use": True}

    monkeypatch.setattr(preparation_commands, "prepare_studio_candidate", lambda *_a, **_k: {})
    monkeypatch.setattr(preparation_commands, "audit_studio_candidate", lambda *_a: ([], []))
    result = run_project_request(project / "plot_request.json", request, execute=execute,
        classifier=lambda *a, **k: {}, new_creation=False, previous_request=None)
    assert result["delivery_package"]["complete"] is True
    assert {p.relative_to(tmp_path / "delivery").as_posix(): p.read_bytes()
            for p in (tmp_path / "delivery").rglob("*") if p.is_file()} == current
    after = store.snapshot()
    writes = store.commands()[-1]["draft"]["writes"]
    for name in (f"{DELIVERY_DATA_DIR}/stable.csv", f"{DELIVERY_TIFF_DIR}/stable.tiff"):
        logical = "@delivery/" + name
        assert logical not in writes
        assert after["files"][logical] == before["files"][logical]
    assert writes[f"@delivery/{DELIVERY_DATA_DIR}/retired.csv"] is None
    assert {f"@delivery/{DELIVERY_PDF_DIR}/replaced.pdf", f"@delivery/{DELIVERY_PDF_DIR}/added.pdf"} <= writes.keys()
    assert (project / "source.csv").read_bytes() == b"x,y\n1,2\n"
