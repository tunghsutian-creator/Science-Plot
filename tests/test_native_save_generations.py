"""Native Save and command Save share the original edit baseline and quarantine."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from sciplot_core.project_store import ProjectConflict
from sciplot_core.project_store.adapters import publish_files, store_for_project
from sciplot_core.studio_core import persistence
from sciplot_core.studio_core.native_save_storage import project_save_binding
from test_veusz_series_revision import _SavableDocument


def fixture_document(tmp_path, monkeypatch):
    root = tmp_path / "project"
    target = root / "studio/document.vsz"
    target.parent.mkdir(parents=True)
    target.write_text("old native")
    (root / "plot_request.json").write_text("{}")
    document = _SavableDocument()
    document.filename = str(target)
    document._sciplot_project_read_set = project_save_binding(root, target)
    monkeypatch.setattr(persistence, "_validate_staged_veusz_document", lambda *_a, **_kw: True)
    persistence.bind_project_document_save(document, root, target)
    return root, target, document


def test_direct_native_save_publishes_generation_and_updates_edit_baseline(tmp_path, monkeypatch):
    root, target, document = fixture_document(tmp_path, monkeypatch)
    before = document._sciplot_project_read_set.copy()
    receipt = document.save(str(target))
    store = store_for_project(root)
    assert receipt["project_command"]["phase"] == "complete"
    assert store.read_bytes("studio/document.vsz") == b"new document"
    assert document._sciplot_project_read_set["generation"] != before["generation"]
    assert document.filename == str(target)
    assert not document.isModified()
    assert not list(target.parent.glob(".sciplot*"))


def test_live_draft_save_refuses_foreign_same_figure_revision(tmp_path, monkeypatch):
    root, target, document = fixture_document(tmp_path, monkeypatch)
    publish_files(store_for_project(root), {"studio/document.vsz": b"foreign saved native"}, kind="save")
    with pytest.raises(ProjectConflict):
        document.save(str(target))
    assert target.read_bytes() == b"foreign saved native"
    assert document.isModified()


def test_native_save_checks_quarantine_installed_after_original_serializer(tmp_path, monkeypatch):
    _root, target, document = fixture_document(tmp_path, monkeypatch)

    class Quarantined:
        def require_usable(self):
            raise RuntimeError("native draft quarantined")

    document._sciplot_native_setting_batch_adapter = Quarantined()
    with pytest.raises(RuntimeError, match="quarantined"):
        document.save(str(target))
    assert target.read_bytes() == b"old native"
    assert document.isModified()


def test_private_stream_serialization_keeps_exact_logical_base(tmp_path):
    target = tmp_path / "document.vsz"
    target.write_bytes(b"old")
    document = _SavableDocument()
    document.saveToFile = lambda handle: handle.write(repr(handle.name))
    document._sciplot_project_read_set = {"files": {}}
    result = persistence.stage_veusz_document(document, target, staged_validator=lambda *_a, **_kw: True)
    stage = Path(result["staged"])
    try:
        assert stage.parent != target.parent
        assert stage.read_text() == repr(str(target))
        assert target.read_bytes() == b"old"
        assert (document.filename, document.modified, document.changeset) == ("live.vsz", True, 7)
    finally:
        stage.unlink()


def test_legacy_native_save_without_generation_keeps_ordinary_atomic_save(tmp_path, monkeypatch):
    root = tmp_path / "project"
    target = root / "studio/document.vsz"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    (root / "plot_request.json").write_bytes(b"{}")
    monkeypatch.setattr(persistence, "_validate_staged_veusz_document", lambda *_a, **_kw: True)
    receipt = persistence.atomic_save_veusz_document(_SavableDocument(), target)
    assert receipt["project_command"] is None
    assert target.read_bytes() == b"new document"
    assert not (root / ".sciplot_store").exists()


def test_native_save_uses_only_explicit_host_selected_store_capabilities(tmp_path, monkeypatch):
    from sciplot_core.project_store import FileProjectStore

    root, target, document = fixture_document(tmp_path, monkeypatch)
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    selected = FileProjectStore(root, locations={"delivery": delivery})
    publish_files(selected, {"@delivery/result.pdf": b"existing exact delivery"}, kind="publish")
    document._sciplot_project_read_set = project_save_binding(root, target, store=selected)
    document._sciplot_project_store = selected
    receipt = document.save(str(target))
    assert receipt["project_command"]["phase"] == "complete"
    assert (delivery / "result.pdf").read_bytes() == b"existing exact delivery"


def save_as_document(tmp_path, monkeypatch, *, existing=False):
    root = tmp_path / "project"
    (root / "studio/processed").mkdir(parents=True)
    (root / "source").mkdir()
    (root / "raw").mkdir()
    target = root / "studio/document.vsz"
    target.write_bytes(b"original native")
    (root / "plot_request.json").write_bytes(b"{}")
    (root / "studio/spec.json").write_bytes(b'{"scientific":"original"}')
    (root / "studio/processed/source.csv").write_bytes(b"x,y\n1,2\n")
    destination = root / "studio/copy.vsz"
    if existing:
        destination.write_bytes(b"existing native copy")
    store = store_for_project(root)
    before = store.snapshot(import_legacy=True)
    selected = ("studio/document.vsz", "studio/spec.json", "plot_request.json", "studio/processed/source.csv")
    document = _SavableDocument()
    document.filename = str(target)
    document._sciplot_project_store = store
    document._sciplot_project_read_set = {"project_id": before["project_id"], "generation": before["generation"],
        "files": {name: before["files"][name]["sha256"] for name in selected}}
    persistence.bind_project_document_save(document, root, target)
    monkeypatch.setattr(persistence, "_validate_staged_veusz_document", lambda *_a, **_kw: True)
    return root, target, destination, document, store


@pytest.mark.parametrize("existing", [False, True], ids=["new-absence", "unchanged-old-preimage"])
def test_bound_native_save_as_declares_only_destination_and_preserves_original_witness(tmp_path, monkeypatch, existing):
    root, target, destination, document, store = save_as_document(tmp_path, monkeypatch, existing=existing)
    before = document._sciplot_project_read_set
    expected_destination = store.snapshot()["files"].get("studio/copy.vsz", {}).get("sha256")
    original = {name: (root / name).read_bytes() for name in before["files"]}
    receipt = document.save(str(destination))
    record = receipt["project_command"]
    assert record["phase"] == "complete"
    assert record["expected_generation"] == before["generation"]
    assert {name: record["read_set"][name] for name in before["files"]} == before["files"]
    assert record["write_set"] == ["studio/copy.vsz"]
    assert record["read_set"]["studio/copy.vsz"] == expected_destination
    assert destination.read_bytes() == b"new document"
    assert original == {name: (root / name).read_bytes() for name in before["files"]}
    assert target.read_bytes() == b"original native"
    assert document._sciplot_project_read_set["files"]["studio/copy.vsz"] == store.snapshot()["files"]["studio/copy.vsz"]["sha256"]


@pytest.mark.parametrize("change", ["late-file", "target-bytes", "target-mode", "native", "spec", "request", "source"])
def test_bound_native_save_as_never_refreshes_old_or_foreign_preimages(tmp_path, monkeypatch, change):
    root, target, destination, document, store = save_as_document(tmp_path, monkeypatch, existing=change.startswith("target-"))
    binding = document._sciplot_project_read_set.copy()
    if change == "late-file":
        destination.write_bytes(b"foreign late file")
    elif change == "target-bytes":
        publish_files(store, {"studio/copy.vsz": b"newer native copy"}, kind="save")
    elif change == "target-mode":
        from sciplot_core.project_commands.resources import PreparedFile
        old = store.snapshot()["files"]["studio/copy.vsz"]
        publish_files(store, {"studio/copy.vsz": PreparedFile(destination.read_bytes(), old["mode"] ^ 0o200)}, kind="save")
    else:
        name = {"native": "studio/document.vsz", "spec": "studio/spec.json", "request": "plot_request.json",
                "source": "studio/processed/source.csv"}[change]
        publish_files(store, {name: b"newer selected revision"}, kind="publish")
    before = store.snapshot()
    observed = destination.read_bytes() if destination.exists() else None
    with pytest.raises(ProjectConflict):
        document.save(str(destination))
    assert store.snapshot()["generation"] == before["generation"]
    assert (destination.read_bytes() if destination.exists() else None) == observed
    assert document._sciplot_project_read_set == binding
    assert document.isModified()


def test_bound_native_save_as_rechecks_new_absence_at_before_head(tmp_path, monkeypatch):
    from sciplot_core.project_store import state

    _root, _target, destination, document, store = save_as_document(tmp_path, monkeypatch)
    before = store.snapshot()
    def create_foreign(name):
        if name == "before_head":
            destination.write_bytes(b"late outside bytes")
    monkeypatch.setattr(state, "boundary", create_foreign)
    with pytest.raises(ProjectConflict):
        document.save(str(destination))
    assert store.snapshot()["generation"] == before["generation"]
    assert destination.read_bytes() == b"late outside bytes"
    assert document.isModified()


@pytest.mark.parametrize("destination", ["raw/copy.vsz", "source/copy.vsz", "studio/processed/source.csv",
                                         "studio/spec.json", "plot_request.json", ".sciplot_store/forbidden.vsz"])
def test_bound_native_save_as_cannot_reclassify_source_or_store_destinations(tmp_path, monkeypatch, destination):
    root, target, _destination, document, store = save_as_document(tmp_path, monkeypatch)
    before = store.snapshot()
    path = root / destination
    observed = path.read_bytes() if path.is_file() else None
    with pytest.raises((ProjectConflict, ValueError)):
        document.save(str(path))
    assert store.snapshot()["generation"] == before["generation"]
    assert (path.read_bytes() if path.is_file() else None) == observed
    assert target.read_bytes() == b"original native"


def test_bound_native_save_as_does_not_follow_an_alias_into_standalone_io(tmp_path, monkeypatch):
    root, target, _destination, document, store = save_as_document(tmp_path, monkeypatch)
    external = tmp_path / "external"
    external.mkdir()
    (root / "studio/alias").symlink_to(external, target_is_directory=True)
    before = store.snapshot()
    with pytest.raises(ValueError, match="symlink"):
        document.save(str(root / "studio/alias/copy.vsz"))
    assert not (external / "copy.vsz").exists()
    assert store.snapshot()["generation"] == before["generation"]
    assert target.read_bytes() == b"original native"


def test_bound_native_save_as_keeps_standalone_distinct_and_rejects_a_foreign_project(tmp_path, monkeypatch):
    _root, target, _destination, document, store = save_as_document(tmp_path, monkeypatch)
    before = store.snapshot()
    foreign = tmp_path / "foreign"
    (foreign / "studio").mkdir(parents=True)
    (foreign / "plot_request.json").write_bytes(b"{}")
    with pytest.raises(ProjectConflict):
        document.save(str(foreign / "studio/copy.vsz"))
    assert not (foreign / "studio/copy.vsz").exists()
    assert store.snapshot()["generation"] == before["generation"]
    standalone = tmp_path / "standalone.vsz"
    receipt = document.save(str(standalone))
    assert receipt["project_command"] is None
    assert standalone.read_bytes() == b"new document"
    assert store.snapshot()["generation"] == before["generation"]
    assert target.read_bytes() == b"original native"


def test_bound_native_save_as_can_return_from_standalone_to_original_native_without_rebinding(tmp_path, monkeypatch):
    _root, target, _destination, document, store = save_as_document(tmp_path, monkeypatch)
    binding = document._sciplot_project_read_set
    standalone = tmp_path / "standalone.vsz"
    document.save(str(standalone))
    assert document._sciplot_project_read_set is binding
    receipt = document.save(str(target))
    assert receipt["project_command"]["phase"] == "complete"
    assert receipt["project_command"]["expected_generation"] == binding["generation"]
    assert receipt["project_command"]["read_set"] == binding["files"]
    assert standalone.read_bytes() == b"new document"
    assert target.read_bytes() == b"new document"
    assert store.read_bytes("studio/processed/source.csv") == b"x,y\n1,2\n"


def test_bound_native_save_as_cannot_write_real_transferred_history(tmp_path, monkeypatch):
    from sciplot_core.project_commands import ProjectCommands
    from test_project_namespace_transfer import fence, fixture_transfer

    _original, store, _before, old, backup, owner, descriptor, command, mutation = fixture_transfer(tmp_path)
    app = ProjectCommands(store)
    review = app.stage_prepared(command, mutation)
    fence(old, backup, owner)
    assert app.decide(command, decision_id=review["decision_id"], accept=True)["phase"] == "complete"
    publish_files(store, {"plot_request.json": b"{}", "studio/document.vsz": b"old native"}, kind="publish")
    target = store.root / "studio/document.vsz"
    historical = store.root / descriptor.history_prefix / "head.json"
    before = store.snapshot()
    assert descriptor.history_prefix + "/head.json" in before["history_resources"]
    preserved = historical.read_bytes()
    document = _SavableDocument()
    document.filename = str(target)
    document._sciplot_project_store = store
    document._sciplot_project_read_set = project_save_binding(store.root, target, store=store)
    persistence.bind_project_document_save(document, store.root, target)
    monkeypatch.setattr(persistence, "_validate_staged_veusz_document", lambda *_a, **_kw: True)
    with pytest.raises(ProjectConflict):
        document.save(str(historical))
    assert historical.read_bytes() == preserved
    assert store.snapshot()["generation"] == before["generation"]


@pytest.mark.parametrize("name", ["studio/figure_set.json", "studio/unselected.spec.json"])
def test_bound_native_save_as_cannot_overwrite_unselected_registered_metadata(tmp_path, monkeypatch, name):
    root, _target, _destination, document, store = save_as_document(tmp_path, monkeypatch)
    publish_files(store, {name: b'{"kind":"registered-metadata"}'}, kind="publish")
    before = store.snapshot()
    # This exact editing baseline is captured after fixture creation, before
    # the synthetic user edit; the metadata is intentionally not an edit read.
    document.modified = False
    document._sciplot_project_read_set = {**document._sciplot_project_read_set,
        "generation": before["generation"]}
    binding = document._sciplot_project_read_set.copy()
    document.modified = True
    assert name not in binding["files"]
    original = (root / name).read_bytes()
    with pytest.raises(ProjectConflict):
        document.save(str(root / name))
    assert store.snapshot()["generation"] == before["generation"]
    assert (root / name).read_bytes() == original
    assert document._sciplot_project_read_set == binding


def test_bound_native_save_as_native_format_never_authorizes_a_registered_source(tmp_path, monkeypatch):
    from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
    from sciplot_core.foundation.file_hashing import file_sha256

    root, _target, _destination, document, store = save_as_document(tmp_path, monkeypatch)
    name = "studio/original-source.vsz"
    path = root / name
    publish_files(store, {name: b"scientific input with a native suffix"}, kind="publish")
    current = store.snapshot()
    source = PreparedSource("a" * 32, str(path), file_sha256(path), path.read_bytes(),
        mode=current["files"][name]["mode"])
    mutation = ProjectMutation({}, {}, prepared_sources=(source,))
    command = ProjectCommand.create("semantic_record", "source-role", project_id=current["project_id"],
        expected_generation=current["generation"], read_set={name: source.version}, write_set=[],
        request={"prepared_digest": mutation.prepared_digest})
    ProjectCommands(store).execute(command, lambda: mutation)
    before = store.snapshot()
    document.modified = False
    document._sciplot_project_read_set = {**document._sciplot_project_read_set,
        "generation": before["generation"]}
    document.modified = True
    with pytest.raises(ProjectConflict, match="scientific source"):
        document.save(str(path))
    assert path.read_bytes() == source.data
    assert store.snapshot()["generation"] == before["generation"]


@pytest.mark.parametrize("concurrent_save,declared_delivery", [(False, False), (True, False), (False, True)],
                         ids=["current", "concurrent-save", "declared-delivery"])
def test_unit_migration_captures_the_generation_before_loading_native_bytes(tmp_path, monkeypatch, concurrent_save, declared_delivery):
    root = tmp_path / "project"
    target = root / "studio/document.vsz"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old native")
    if declared_delivery:
        import json
        from sciplot_core.project_store import FileProjectStore, ResourceRoot

        delivery = tmp_path / "delivery"
        delivery.mkdir()
        (delivery / "figure.pdf").write_bytes(b"original delivery")
        (tmp_path / "project.zip").write_bytes(b"original snapshot")
        (root / "plot_request.json").write_text(json.dumps({"delivery_output": str(delivery)}))
        store = FileProjectStore(root, locations={"delivery": delivery,
            "snapshot": ResourceRoot(tmp_path, members=("project.zip",))})
    else:
        (root / "plot_request.json").write_bytes(b"{}")
        store = store_for_project(root)
    before = store.snapshot(import_legacy=True)
    events, documents, saved = [], [], []
    binding = persistence.project_save_binding

    def capture(*args, **kwargs):
        events.append("baseline")
        return binding(*args, **kwargs)

    class Setting:
        value = "Velocity (m/s)"

        def get(self):
            return self.value

        def normalize(self, value):
            return value

    class Document(_SavableDocument):
        def __init__(self):
            super().__init__()
            self.setting = Setting()
            documents.append(self)

        def load(self, path):
            self.filename = str(path)
            self.observed = Path(path).read_bytes()
            events.append("load")
            if concurrent_save:
                saved.append(publish_files(store, {"studio/document.vsz": b"concurrent native save"}, kind="save"))

        def walkNodes(self, collect, **_kwargs):
            collect("/page/graph", SimpleNamespace(settings=SimpleNamespace(setdict={"label": self.setting})))

        def applyOperation(self, operation):
            self.setting.value = operation[1]

    app = SimpleNamespace(quit=lambda: events.append("quit"))
    monkeypatch.setitem(sys.modules, "PyQt6", SimpleNamespace(QtWidgets=SimpleNamespace(
        QApplication=SimpleNamespace(instance=lambda: app))))
    monkeypatch.setattr("sciplot_core.veusz_runtime.needs_veusz_worker_process", lambda: False)
    monkeypatch.setattr("sciplot_core.studio_core.qt_compat.ensure_veusz_loader_compat", lambda: None)
    monkeypatch.setattr(persistence, "_prefer_offscreen_export_platform", lambda: None)
    monkeypatch.setattr(persistence, "_ensure_veusz_on_path", lambda: None)
    monkeypatch.setattr(persistence, "import_module", lambda name: SimpleNamespace(
        Document=Document, OperationSettingSet=lambda path, value: (path, value)))
    monkeypatch.setattr(persistence, "project_save_binding", capture)
    monkeypatch.setattr(persistence, "selected_project_store", lambda: None)
    monkeypatch.setattr(persistence, "_validate_staged_veusz_document", lambda *_args, **_kwargs: True)

    if concurrent_save:
        with pytest.raises(ProjectConflict):
            persistence.migrate_studio_document_unit_labels(target)
        assert target.read_bytes() == b"concurrent native save"
        assert store.snapshot()["generation"] == saved[0]["generation"]
        assert documents[0]._sciplot_project_read_set["generation"] == before["generation"]
        assert len(store.commands()) == 1
    else:
        result = persistence.migrate_studio_document_unit_labels(target)
        assert result["status"] == "migrated" and result["operation_count"] == 1
        assert result["save"]["project_command"]["phase"] == "complete"
        assert documents[0].setting.value != "Velocity (m/s)"
        assert target.read_bytes() == b"new document"
        if declared_delivery:
            assert documents[0]._sciplot_project_store.locations == store.locations
            assert documents[0]._sciplot_project_store.location_members == store.location_members
            assert (delivery / "figure.pdf").read_bytes() == b"original delivery"
            assert (tmp_path / "project.zip").read_bytes() == b"original snapshot"
    assert documents[0].observed == b"old native"
    assert events == ["baseline", "load"]


@pytest.mark.comprehensive
def test_private_real_veusz_linked_source_save_keeps_logical_relative_base(tmp_path):
    import os
    import subprocess
    import sys

    script = r'''
import sys
from pathlib import Path
from sciplot_core.studio_core.runtime import _ensure_veusz_on_path
_ensure_veusz_on_path()
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
ensure_veusz_loader_compat()
from PyQt6 import QtWidgets
from veusz import document, dataimport, setting, widgets
from veusz.document.commandinterface import CommandInterface
from sciplot_core.studio_core.persistence import atomic_save_veusz_document, bind_project_document_save
from sciplot_core.studio_core.native_save_storage import project_save_binding
app = QtWidgets.QApplication([])
root = Path(sys.argv[1])
target = root / "studio/document.vsz"
target.parent.mkdir(parents=True)
(root / "plot_request.json").write_bytes(b"{}")
source = root / "source.txt"
source.write_text("1 2\n3 4\n")
setting.settingdb['docfile_addimportpaths'] = False
live = document.Document()
CommandInterface(live).ImportFile(str(source), 'x y', linked=True)
live.save(str(target))
live._sciplot_project_read_set = project_save_binding(root, target)
bind_project_document_save(live, root, target)
receipt = atomic_save_veusz_document(live, target)
assert receipt['ready_for_export'] is True
assert '../source.txt' in target.read_text()
reopened = document.Document()
reopened.load(str(target), callbackunsafe=lambda:False)
assert reopened.data['x'].data.tolist() == [1.0, 3.0]
assert reopened.data['y'].data.tolist() == [2.0, 4.0]
assert source.read_text() == "1 2\n3 4\n"
app.quit()
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path / "project")],
        capture_output=True, text=True, check=False, env=dict(os.environ), timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
