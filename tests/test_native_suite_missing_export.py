"""Explicit export owns fresh derived output, never missing scientific authority."""

from pathlib import Path
import subprocess

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.project_store import ProjectConflict
from sciplot_core.workflow import native_suite_transactions as native
from sciplot_core.workflow.native_suite_generation import open_store
from sciplot_core.workflow.rheology_tts_style_storage import snapshot

from test_native_suite_project_commands import bound as bound, request
from test_native_suite_operations import suite as suite


@pytest.fixture
def exporter(bound, monkeypatch):
    from sciplot_core import rheology_tts_render

    calls = []

    def render(documents):
        calls.append([str(path) for path, _out, _figure in documents])
        return [bound[6](path, out, figure) for path, out, figure in documents]

    monkeypatch.setattr(rheology_tts_render, "export_tts_documents", render)
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("Pure adapter control started native work"))
    return calls


def test_noop_then_explicit_export_regenerates_only_missing_owned_derived_pdf(bound, exporter):
    workspace, delivery, source, documents, _capture, calls, _render = bound
    plot = Path(documents[0]["path"])
    store = open_store(workspace, delivery)
    artifact = Path(documents[0]["exports"][0])
    logical = store.logical_path(artifact)
    before = store.snapshot()
    assert logical in before["files"] and artifact.suffix == ".pdf"
    protected = snapshot([source, plot, workspace / "A.spec.json", Path(documents[1]["path"]),
                          *(Path(path) for path in documents[1]["exports"])])
    artifact.unlink()
    req = request(bound)
    req["changes"][0]["value"] = "top-left"
    unchanged = native.patch_native(plot, req)
    assert unchanged["changed"] is False and unchanged["exports"] == []
    assert unchanged["ready_to_use"] is False and unchanged["export_status"] == "pending"
    assert unchanged["next_step"]["action"] == "plot.export" and calls == []
    assert not artifact.exists() and snapshot([Path(name) for name in protected]) == protected

    result = native.export_native(plot)
    assert result["status"] == "complete" and result["ready_to_use"] is True
    assert exporter == [[str(plot)]] and calls == ["export"]
    assert artifact.read_bytes() == plot.read_bytes() + b"pdf"
    assert artifact.read_bytes() != store.read_bytes(logical, generation=before["generation"])
    assert next(item for item in result["exports"] if item["path"] == str(artifact))["sha256"] == file_sha256(artifact)
    assert snapshot([Path(name) for name in protected]) == protected


def test_complete_export_keeps_its_receipt_and_fresh_absence_gets_one_new_export(bound, exporter):
    workspace, delivery, source, documents, _capture, calls, _render = bound
    plot = Path(documents[0]["path"])
    store = open_store(workspace, delivery)
    first = native.export_native(plot)
    original = store.commands()[0]
    artifact = Path(documents[0]["exports"][0])
    before = store.snapshot()
    protected = snapshot([source, plot, workspace / "A.spec.json", Path(documents[1]["path"])])
    artifact.unlink()
    second = native.export_native(plot)
    records = store.commands()
    latest = next(item for item in records if item["metadata"].get("missing_outputs"))
    assert second["generation"] != first["generation"] and len(records) == 2
    assert latest["metadata"]["missing_outputs"][0]["owner_key"] == original["command_id"]
    assert latest["metadata"]["read_set"][store.logical_path(artifact)] == before["files"][store.logical_path(artifact)]["sha256"]
    assert store.query(original["command_id"]) == original
    assert native.export_native(plot)["generation"] == second["generation"]
    assert len(store.commands()) == 2 and exporter == [[str(plot)], [str(plot)]] and calls == ["export", "export"]
    assert snapshot([Path(name) for name in protected]) == protected


def test_audited_saved_native_and_missing_creation_catalog_output_keep_distinct_authorities(bound, exporter, monkeypatch):
    from sciplot_core import rheology_tts_render

    workspace, delivery, source, documents, _capture, calls, _render = bound
    plot, artifact = Path(documents[0]["path"]), Path(documents[0]["exports"][0])
    store = open_store(workspace, delivery)
    assert store.commands() == ()
    protected = snapshot([source, workspace / "A.spec.json", Path(documents[1]["path"]),
                          *(Path(path) for path in documents[1]["exports"])])
    plot.write_bytes(plot.read_bytes() + b":audited manual save")
    saved = plot.read_bytes()
    audits = []

    def audit(path, figure):
        audits.append((str(path), figure["id"]))
        return {"status": "passed", "document": str(path), "document_sha256": file_sha256(path)}

    monkeypatch.setattr(rheology_tts_render, "audit_tts_document", audit)
    artifact.unlink()
    result = native.export_native(plot)
    records = store.commands()
    reconstructed, = [item for item in records if item["metadata"].get("missing_outputs")]
    assert result["ready_to_use"] is True and len(records) == 3
    assert reconstructed["metadata"]["missing_outputs"][0]["catalog"]["key"] == "A"
    assert [item["metadata"]["kind"] for item in records].count("native_import") == 1
    assert audits == [(str(plot), "A")] and exporter == [[str(plot)]] and calls == ["export"]
    assert plot.read_bytes() == saved and artifact.read_bytes() == saved + b"pdf"
    assert snapshot([Path(path) for path in protected]) == protected


@pytest.mark.comprehensive
def test_real_native_missing_output_rebuilds_after_complete_without_repeating_retry(suite, monkeypatch):
    from sciplot_core import rheology_tts_render

    workspace, delivery, source, prepared, manifest = suite
    selected, optional = manifest["documents"]
    plot, artifact = Path(selected["path"]), Path(selected["exports"][0])
    protected = snapshot([source, prepared, plot, workspace / "figure_plan.json",
        *(Path(item["spec_path"]) for item in manifest["native_result"]["figures"]),
        Path(optional["path"]), *(Path(path) for path in optional["exports"])])
    first = native.export_native(plot)
    store = open_store(workspace, delivery)
    original = next(item for item in store.commands() if item["metadata"]["request"].get("adapter") == "native_suite_export")
    calls, dispatch = [], rheology_tts_render._dispatch

    def counted(payload):
        calls.append(payload["action"])
        return dispatch(payload)

    monkeypatch.setattr(rheology_tts_render, "_dispatch", counted)
    artifact.unlink()
    rebuilt = native.export_native(plot)
    assert first["ready_to_use"] is True and rebuilt["ready_to_use"] is True
    assert rebuilt["generation"] != first["generation"] and calls == ["export_batch"]
    assert next(item for item in rebuilt["exports"] if item["format"] == "pdf")["sha256"] == file_sha256(artifact)
    assert rebuilt["transform_execution"]["executed"] == []
    assert native.export_native(plot)["generation"] == rebuilt["generation"] and calls == ["export_batch"]
    assert store.query(original["command_id"]) == original
    assert snapshot([Path(path) for path in protected]) == protected


@pytest.mark.parametrize("fault", ["changed-export", "foreign-export", "native", "spec", "raw"])
def test_explicit_export_never_recreates_authority_or_overwrites_foreign_outputs(bound, exporter, fault):
    workspace, delivery, source, documents, _capture, calls, _render = bound
    plot = Path(documents[0]["path"])
    store = open_store(workspace, delivery)
    artifact = Path(documents[0]["exports"][0])
    if fault == "changed-export":
        artifact.write_bytes(b"outside changed output")
    elif fault == "foreign-export":
        foreign = workspace.parent / "foreign.pdf"
        foreign.write_bytes(b"unrelated output must survive")
        artifact.unlink()
        artifact.symlink_to(foreign)
    else:
        {"native": plot, "spec": workspace / "A.spec.json", "raw": source}[fault].unlink()
    head = (workspace / ".sciplot_store/head.json").read_bytes()
    protected = snapshot([path for path in [source, plot, workspace / "A.spec.json",
        Path(documents[1]["path"]), *(Path(path) for path in documents[1]["exports"])] if path.exists()])
    expected = {"foreign-export": OSError, "raw": ValueError, "native": EngineError}.get(fault, ProjectConflict)
    with pytest.raises(expected) as caught:
        native.export_native(plot)
    assert exporter == [] and calls == []
    assert (workspace / ".sciplot_store/head.json").read_bytes() == head
    assert snapshot([Path(name) for name in protected]) == protected
    records = store.commands()
    if fault == "raw":
        assert str(caught.value).startswith("Original source changed")
        assert len(records) == 1 and records[0]["phase"] == "unknown"
    else:
        assert records == ()
    if fault in {"native", "spec", "raw"}:
        assert not {"native": plot, "spec": workspace / "A.spec.json", "raw": source}[fault].exists()
    if fault == "changed-export":
        assert artifact.read_bytes() == b"outside changed output"
    elif fault == "foreign-export":
        assert artifact.is_symlink() and foreign.read_bytes() == b"unrelated output must survive"
