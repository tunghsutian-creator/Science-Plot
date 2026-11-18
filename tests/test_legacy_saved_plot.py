"""A legacy plot can be viewed and redrawn without admitting a writable project."""
import json
from pathlib import Path

import pytest

from sciplot_core.cli import main
from sciplot_core.foundation.file_hashing import file_sha256

_SAVED_VSZ = """SetData('x', [0., 1., 2.])
SetData('y', [1., 3., 2.])
Add('page', name='page1', autoadd=False)
To('page1')
Add('graph', name='graph1', autoadd=False)
To('graph1')
Add('axis', name='x', autoadd=False)
Add('axis', name='y', autoadd=False)
To('y')
Set('direction', 'vertical')
To('..')
Add('xy', name='curve', autoadd=False)
To('curve')
Set('xData', 'x')
Set('yData', 'y')
"""


def _old_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "archive"
    studio = project / "studio"
    studio.mkdir(parents=True)
    (project / "plot_request.json").write_text("{}")
    (project / "keep.txt").write_text("old scientific notes")
    (studio / "spec.json").write_text("{}")
    native = studio / "document.vsz"
    native.write_text(_SAVED_VSZ)
    return project, native


def _tree(root: Path) -> dict[str, tuple[int, int, bytes | None]]:
    return {str(path.relative_to(root)): (path.stat().st_mode, path.stat().st_mtime_ns,
            path.read_bytes() if path.is_file() else None) for path in (root, *root.rglob("*"))}


@pytest.mark.comprehensive
def test_legacy_open_and_redraw_read_exact_saved_vsz_without_writing_project(tmp_path, capsys, monkeypatch):
    from PIL import Image, ImageChops
    from sciplot_core.veusz_worker.operations import export_document

    project, native = _old_project(tmp_path)
    expected = export_document(native, formats=["png_300"], output_dir=tmp_path / "before")
    old_tree = _tree(project)
    assert main(["plot", "open", str(project), "--direct", "--json"]) == 0
    opened = json.loads(capsys.readouterr().out)
    assert opened["read_only"] and opened["new_features_require_conversion"]
    assert opened["document"] == {"path": str(native), "sha256": file_sha256(native)}
    assert opened["pages"] == ["page1"]
    assert opened["next_step"]["action"] == "redraw_legacy"
    assert _tree(project) == old_tree

    output = tmp_path / "redrawn"
    assert main(["project", "legacy-redraw", str(project), "--out", str(output),
                 "--formats", "pdf,png_300", "--json"]) == 0
    redrawn = json.loads(capsys.readouterr().out)
    assert redrawn["document_sha256"] == opened["document"]["sha256"]
    exports = {record["format"]: record for record in redrawn["exports"]}
    assert set(exports) == {"pdf", "png_300"}
    for record in exports.values():
        assert Path(record["path"]).is_relative_to(output)
        assert file_sha256(Path(record["path"])) == record["sha256"]
    with Image.open(expected["exports"][0]["path"]) as original, Image.open(exports["png_300"]["path"]) as actual:
        assert original.size == actual.size
        assert ImageChops.difference(original.convert("RGB"), actual.convert("RGB")).getbbox() is None
    assert _tree(project) == old_tree

    # Historic delivery roots must not fall through to implicit source import.
    portable = tmp_path / "portable"
    (portable / "project").mkdir(parents=True)
    snapshot = portable / "project" / "figure.vsz"
    snapshot.write_bytes(native.read_bytes())
    (portable / "SciPlot_delivery.json").write_text(json.dumps({
        "kind": "sciplot_delivery_identity", "version": 1, "binding": None}))
    saved_delivery = _tree(portable)
    assert main(["plot", "open", str(portable), "--direct", "--json"]) == 0
    reopened = json.loads(capsys.readouterr().out)
    assert reopened["read_only"] and reopened["document"]["path"] == str(snapshot)
    assert _tree(portable) == saved_delivery

    from sciplot_core.plot_protocol import socket_client
    from sciplot_core.plot_protocol.server import make_service

    def no_nested_rpc(*_args, **_kwargs):
        pytest.fail("The active public plot owner must not reconnect to itself.")

    monkeypatch.setattr(socket_client, "call", no_nested_rpc)
    service = make_service()
    raw = tmp_path / "UVvis.csv"
    original = b"Wavelength,Absorbance\nnm,a.u.\nA,A\n400,2\n460,5\n500,1\n"
    raw.write_bytes(original)
    request = {"source": str(raw), "idempotency_key": "new-public-source-only"}
    deliver = service.deliver

    def fail_before_delivery(_request):
        return {"status": "blocked", "ready_to_use": False,
                "blocker": {"reason_code": "temporary_delivery_outage", "message": "Simulated delivery interruption."},
                "next_step": {"action": "retry_same_request"}}

    try:
        monkeypatch.setattr(service, "deliver", fail_before_delivery)
        blocked = service.create(request)
        assert blocked["status"] == "blocked" and blocked["plot_type"] == "ManagedPlot"
        journal = Path(blocked["plot"]) / "task" / "task.json"
        saved = json.loads(journal.read_text())
        assert saved["phase"] == "delivering" and saved["result"]["ready_to_use"] is True
        monkeypatch.setattr(service, "deliver", deliver)
        ready = service.decide(Path(blocked["plot"]), blocked["next_step"]["request"])
        assert ready["ready_to_use"] and not ready["read_only"] and ready["plot_type"] == "ManagedPlot"
        assert (ready["plot_id"], ready["revision"]) == (saved["result"]["plot_id"], 0)
        assert ready["analysis_metrics"][0]["value"] == 460
        assert {entry["format"] for entry in ready["exports"]} == {"pdf", "tiff_300", "vsz"}
        assert all(Path(entry["path"]).is_file() for entry in ready["exports"])
        persisted = journal.read_bytes()
        assert service.create(request) == ready
        assert journal.read_bytes() == persisted and raw.read_bytes() == original
        raw.write_bytes(original.replace(b"460,5", b"460,6"))
        stale = service.create(request)
        assert stale["status"] == "blocked" and not stale["ready_to_use"]
        action = stale["next_step"]
        assert action["action"] == "resolve_current_evidence" and "request" not in action
        assert action["inspect_cli_argv"][1:4] == ["plot", "describe", ready["plot"]]
        assert action["changed_inputs"] and journal.read_bytes() == persisted
        raw.write_bytes(original)
        assert service.create(request) == ready
        assert _tree(project) == old_tree

        # A pre-upgrade receipt, even if interrupted before its task allocation,
        # is still bound to its original legacy-capable creation route.
        from sciplot_core.project_lifecycle import creation
        from sciplot_core.project_lifecycle.context import digest

        historical = {**request, "idempotency_key": "pre-upgrade-source-only"}
        historical_root = service.targets.creation_root(raw, historical["idempotency_key"])
        historical_root.mkdir(parents=True)
        original_record = {"request": historical, "request_hash": digest(historical)}
        historic_journal = historical_root / "creation.json"
        historic_journal.write_text(json.dumps(original_record))
        admitted = []

        def interrupt_historical(_request, **kwargs):
            admitted.append(kwargs["_prefer_managed"])
            return {"status": "blocked"}

        monkeypatch.setattr(creation, "start_task", interrupt_historical)
        assert service.create(historical)["status"] == "blocked"
        assert admitted == [False] and "raw_admission" not in json.loads(historic_journal.read_bytes())
    finally:
        service.close()



def test_exact_legacy_vsz_rejects_output_inside_original_project(tmp_path, capsys):
    project, native = _old_project(tmp_path)
    old_tree = _tree(project)
    assert main(["project", "legacy-redraw", str(native), "--out", str(project / "export"), "--json"]) == 1
    assert "outside the original project" in capsys.readouterr().out
    assert _tree(project) == old_tree


def test_committed_legacy_head_is_read_only_even_with_a_real_revision_pointer(tmp_path, monkeypatch):
    from test_plot_engine import FakeBackend, commit, request
    from sciplot_core.plot_engine.errors import EngineError
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.studio_core import project_query

    backend = FakeBackend(tmp_path / "backend")
    doc, binding = backend.initial()
    binding.update(kind="sciplot_veusz_binding", project=str(backend.directory), document=str(backend.native))
    root = tmp_path / "old-shadow"
    commit(root, doc, binding, "import")
    previous = _tree(tmp_path)
    monkeypatch.setattr(project_query, "_inspect_document", lambda source: {
        "document": {"path": str(source), "sha256": file_sha256(source)}, "pages": ["page1"], "linked_files": []})
    service = PlotService(backend, read_only_legacy=True)
    try:
        assert service.open(root)["read_only"]
        assert service.describe(root)["read_only"]
        with pytest.raises(EngineError) as caught:
            service.patch(root, request())
        assert caught.value.reason_code == "legacy_conversion_required"
        assert backend.calls["apply"] == 0
        with pytest.raises(EngineError, match="read-only"):
            service.export(root)
    finally:
        service.close()
    assert _tree(tmp_path) == previous


def test_registered_project_selects_legacy_or_managed_by_exact_figure_identity(tmp_path, monkeypatch):
    from managed_plot_helpers import request_for_source
    from test_project_lifecycle import ManagedBackend
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.project_store.repository import FileProjectStore
    from sciplot_core.studio_core import project_query

    project, native = _old_project(tmp_path)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    source_parent = project / "source"
    source_parent.mkdir()
    request = request_for_source(source_parent)
    # The read test uses a real store and attached Managed head, but a fake
    # renderer so authority routing is independent of GUI/runtime availability.
    service = PlotService(ManagedBackend(), read_only_legacy=True)
    try:
        created = service.create(request, project=project)
        assert created["ready_to_use"], created
        before = _tree(project)
        monkeypatch.setattr(project_query, "_inspect_document", lambda source: {
            "document": {"path": str(source), "sha256": file_sha256(source)},
            "pages": ["page1"], "linked_files": []})
        assert service.open(project, figure_id=created["plot_id"])["plot_type"] == "ManagedPlot"
        legacy = service.open(project, figure_id="primary")
        assert legacy["read_only"] and legacy["document"]["path"] == str(native)
        assert _tree(project) == before
    finally:
        service.close()


def test_public_task_and_native_edit_entrypoints_cannot_allocate_old_project_writes(tmp_path, capsys):
    from sciplot_core.mcp_server.services import invoke_owner
    from sciplot_core.plot_engine.errors import EngineError

    project, native = _old_project(tmp_path)
    before = _tree(project)
    changes = tmp_path / "changes.json"
    changes.write_text("[]")
    arguments = ["project", "edit-preview", str(project), "--out", str(tmp_path / "candidate"),
                 "--expected-document", file_sha256(native), "--changes", str(changes), "--json"]
    assert main(arguments) == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "legacy_conversion_required"
    assert not (tmp_path / "candidate").exists()
    request = tmp_path / "task-request.json"
    request.write_text(json.dumps({"version": 1, "action": "export", "project": str(project)}))
    assert main(["task", "start", "--request", str(request), "--task-dir", str(tmp_path / "new-task"), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "legacy_conversion_required"
    assert not (tmp_path / "new-task").exists()
    with pytest.raises(EngineError) as error:
        invoke_owner("sciplot_export", {"project": str(project)})
    assert error.value.reason_code == "legacy_conversion_required"
    assert _tree(project) == before


def test_public_legacy_resume_requires_and_only_finishes_a_saved_transaction(tmp_path, monkeypatch):
    from test_plot_engine import FakeBackend, commit, request
    from sciplot_core.plot_engine import external_mutation
    from sciplot_core.plot_engine.errors import EngineError
    from sciplot_core.plot_engine.service import PlotService

    backend = FakeBackend(tmp_path / "backend")
    document, binding = backend.initial()
    binding.update(kind="sciplot_veusz_binding", project=str(backend.directory), document=str(backend.native))
    root = tmp_path / "old-shadow"
    commit(root, document, binding, "import")
    # The transport exercises the real saved transaction; native output is fake.
    monkeypatch.setattr(external_mutation, "capture_baseline", lambda _root, result: result)
    historical = PlotService(backend)
    public = PlotService(backend, read_only_legacy=True)
    retry = {"plot_id": "test-plot", "base_revision": 0, "idempotency_key": "saved"}
    try:
        with pytest.raises(EngineError) as error:
            public.resume(root, retry)
        assert error.value.reason_code == "legacy_transaction_unknown"
        assert backend.calls["apply"] == 0
        backend.export_failures = [RuntimeError("interrupted historical export")]
        prior = historical.patch(root, request(key="saved"))
        assert prior["commit_status"] == "committed" and not prior["ready_to_use"]
        assert backend.calls["apply"] == 1
        assert public.resume(root, retry)["ready_to_use"]
        assert backend.calls["apply"] == 1
    finally:
        public.close()
        historical.close()
