"""Actual shared application/store contracts; synthetic bytes, no scientific claim."""

from pathlib import Path
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import pytest

from sciplot_core.project_commands import (
    NativeAdoption, ProjectCommand, ProjectCommands, ProjectMutation, ProjectCommandUnknown,
)
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store import state
from sciplot_core.project_store.errors import ProjectRecoveryRequired


def prepared(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "A.vsz").write_bytes(b"old-A")
    (project / "B.vsz").write_bytes(b"old-B")
    store = FileProjectStore(project)
    original = store.snapshot(import_legacy=True)
    return project, store, original


def make_command(snapshot, key="edit-A", resource="A.vsz", **options):
    return ProjectCommand.create("document_edit", key, project_id=snapshot["project_id"],
        expected_generation=snapshot["generation"], read_set={resource: snapshot["files"][resource]["sha256"]},
        write_set=[resource], request={"resource": resource}, **options)


class LostAfterHead(BaseException):
    pass


@pytest.mark.parametrize("reader", ["query", "commands", "snapshot"], ids=["query", "list", "snapshot"])
def test_status_read_cannot_repair_active_native_bytes_after_interrupted_publication(tmp_path, monkeypatch, reader):
    project, store, original = prepared(tmp_path)
    def stop(point):
        if point == "after_head":
            raise LostAfterHead()
    monkeypatch.setattr(state, "boundary", stop)
    command = make_command(original)
    with pytest.raises(LostAfterHead):
        ProjectCommands(store).execute(command, lambda: ProjectMutation({"A.vsz": b"new-A"}, {}))
    before = {name: ((project / name).read_bytes(), (project / name).stat().st_mtime_ns)
              for name in ("A.vsz", "B.vsz")}
    try:
        getattr(store, reader)(command.key) if reader == "query" else getattr(store, reader)()
    except ProjectRecoveryRequired:
        pass
    assert {name: ((project / name).read_bytes(), (project / name).stat().st_mtime_ns)
            for name in before} == before
    store.recover()
    assert (project / "A.vsz").read_bytes() == b"new-A"
    assert store.query(command.key)["phase"] == "complete"


def test_exact_preview_artifacts_and_reply_loss_share_the_real_store_owner(tmp_path):
    _project, store, original = prepared(tmp_path)
    app = ProjectCommands(store)
    command = make_command(original)
    native_calls = []
    def preview():
        native_calls.append("native")
        return ProjectMutation({"A.vsz": b"new-A"}, {"export_status": "pending"},
                               review={"image": "preview.png"}, artifacts={"preview.png": b"sealed-pixels"})
    pending = app.preview(command, preview)
    assert Path(pending["artifact_paths"]["preview.png"]).read_bytes() == b"sealed-pixels"
    assert app.query_decision(pending["decision_id"])["metadata"] == command.to_payload()
    result = app.decide(command, decision_id=pending["decision_id"], accept=True)
    retry = app.execute(ProjectCommand.from_payload(result["metadata"]), preview)
    assert retry["phase"] == "complete"
    assert retry["result"]["export_status"] == "pending"
    assert native_calls == ["native"]
    assert Path(retry["artifact_paths"]["preview.png"]).read_bytes() == b"sealed-pixels"


def test_unrelated_figure_generation_does_not_invalidate_exact_A_readset(tmp_path):
    project, store, original = prepared(tmp_path)
    app = ProjectCommands(store)
    a = make_command(original)
    b = make_command(original, "edit-B", "B.vsz")
    app.execute(b, lambda: ProjectMutation({"B.vsz": b"new-B"}, {}))
    app.execute(a, lambda: ProjectMutation({"A.vsz": b"new-A"}, {}))
    assert (project / "A.vsz").read_bytes() == b"new-A"
    assert (project / "B.vsz").read_bytes() == b"new-B"


def test_two_applications_cannot_repeat_the_same_inflight_native_callback(tmp_path):
    _project, store, original = prepared(tmp_path)
    command = make_command(original)
    entered, release = Event(), Event()
    calls = []
    def native():
        calls.append("native")
        entered.set()
        assert release.wait(5)
        return ProjectMutation({"A.vsz": b"new-A"}, {})
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ProjectCommands(store).execute, command, native)
        assert entered.wait(5)
        second = pool.submit(ProjectCommands(FileProjectStore(store.root)).execute, command, native)
        try:
            with pytest.raises(ProjectCommandUnknown):
                second.result(timeout=5)
        finally:
            release.set()
        assert first.result(timeout=5)["phase"] == "complete"
    assert calls == ["native"]


def test_audited_legacy_adoption_keeps_native_bytes_and_history_without_force_write(tmp_path):
    project, store, original = prepared(tmp_path)
    (project / "A.vsz").write_bytes(b"manual-A")
    new_sha = state.digest("placeholder")  # Distinct test audit identity, not a scientific certificate.
    import hashlib
    observed = hashlib.sha256(b"manual-A").hexdigest()
    adoption = NativeAdoption("A.vsz", original["files"]["A.vsz"]["sha256"], observed, new_sha)
    command = ProjectCommand.create("native_import", "adopt-A", project_id=original["project_id"],
        expected_generation=original["generation"], read_set={"A.vsz": adoption.before_sha256},
        write_set=["A.vsz"], request={"observed_sha256": observed}, native_adoptions=[adoption])
    result = ProjectCommands(store).execute(command, lambda: ProjectMutation({"A.vsz": b"manual-A"}, {}))
    assert result["phase"] == "complete"
    assert store.read_bytes("A.vsz", generation=original["generation"]) == b"old-A"
    assert store.read_bytes("A.vsz") == b"manual-A"
    assert (project / "A.vsz").read_bytes() == b"manual-A"
