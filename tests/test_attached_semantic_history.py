"""Exact namespace transfer and cold history preserve the original sealed bytes."""
from contextlib import nullcontext
import json
from pathlib import Path
import shutil

import pytest

from managed_plot_helpers import patch, request_for_source
from test_project_lifecycle import ManagedBackend
from test_attached_semantic_repository import application
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_lifecycle.application import ProjectApplication
from sciplot_core.project_lifecycle.attachment_index import INDEX, OWNER
from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.repository import FileProjectRepository
from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime


def standalone():
    repository = FileProjectRepository(lease=lambda _: nullcontext())
    return ProjectApplication(ManagedBackend(), repository, targets=FilesystemProjectTargets(repository),
                              capabilities=COMPATIBILITY_CAPABILITIES)


def old_managed(tmp_path, *, large=False):
    sources = tmp_path / "original-sources"
    sources.mkdir()
    request = request_for_source(sources)
    if large:
        source = Path(request["data_binding"]["data_sources"][0]["path"])
        source.write_text("Time,Signal\ns,V\n" + "".join(f"{number},{number + 1}\n" for number in range(4500)))
        request["data_binding"]["data_sources"][0]["sha256"] = file_sha256(source)
        request["data_binding"]["data_sources"][0]["table_selection"]["data_end_row"] = 4502
        request["template_definition"]["presentation"]["objects"]["axis:x"]["properties"]["axis.limits"] = [0, 4500]
    created = standalone().create(request)
    return sources, Path(created["plot"]), created


def bytes_in(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_exact_old_namespace_transfer_preserves_history_and_fences_every_old_writer(tmp_path, monkeypatch):
    sources, old, created = old_managed(tmp_path)
    before = bytes_in(old)
    sibling = old.parent / "unrelated-project"
    sibling.mkdir()
    (sibling / "head.json").write_bytes(b"do not import")
    project = tmp_path / "native-project"
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store):
        opened = app.open(old)
    root = Path(opened["plot"])
    assert root != old and opened["plot_id"] == created["plot_id"]
    assert opened["scientific_hash"] == created["scientific_hash"]
    marker = json.loads((old / OWNER).read_bytes())
    backup = Path(marker["history_root"])
    assert {key: data for key, data in bytes_in(backup).items() if key != OWNER} == before
    assert set(bytes_in(old)) == {OWNER, "head.json"}
    assert json.loads((old / "head.json").read_bytes())["kind"] == "sciplot_attached_semantic_redirect"
    assert (old / OWNER).is_file()
    assert all(b"do not import" != store.read_bytes(name) for name in store.snapshot()["files"])
    monkeypatch.setattr(FileProjectRepository, "write", lambda *_: pytest.fail("old writer reused"))
    assert app.open(old)["plot"] == str(root)
    for operation in (lambda: FileProjectRepository().prepare_namespace(old),
                      lambda: FileProjectRepository().publish_content(old / "content/new", b"x", lambda: None)):
        with pytest.raises(EngineError) as caught:
            operation()
        assert caught.value.reason_code == "semantic_attachment_owner_required"
    with pytest.raises(EngineError) as caught:
        app.describe(backup)
    assert caught.value.reason_code == "semantic_attachment_history_read_only"
    assert sources.is_dir()


def test_managed_cold_bundle_rebuilds_after_originals_and_disposable_artifacts_disappear(tmp_path):
    sources, old, created = old_managed(tmp_path, large=True)
    old_bytes = bytes_in(old)
    assert any(name.startswith("content/") for name in old_bytes)
    project = tmp_path / "native-project"
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store):
        opened = app.open(old)
    root = Path(opened["plot"])
    styled = app.patch(root, patch(opened, "style-before-move", "style.line.width", "1.2pt", "series:A"))
    snapshot = store.snapshot()
    history = {name: store.read_bytes(name) for name in snapshot["files"] if "/revisions/" in name or "/content/" in name}
    bundle = store.export_bundle(tmp_path / "bundle")
    sources.rename(tmp_path / "source-offline")
    project.rename(tmp_path / "project-offline")
    moved = FileProjectStore.import_bundle(bundle, tmp_path / "relocated")
    shutil.rmtree(moved.root / ".sciplot_store" / "semantic-derived", ignore_errors=True)
    newapp = application()
    with project_runtime(moved):
        cold = newapp.open(moved.root, figure_id=created["plot_id"])
        exported = newapp.export(Path(cold["plot"]))
    assert cold["plot_id"] == created["plot_id"] and cold["revision"] == styled["revision"]
    assert exported["scientific_hash"] == created["scientific_hash"]
    assert {name: moved.read_bytes(name) for name in history} == history
    assert old_bytes["revisions/00000000.json"] == next(data for name, data in history.items() if name.endswith("/revisions/00000000.json"))
    index = json.loads(moved.read_bytes(INDEX))
    attachment = next(iter(index["attachments"].values()))
    assert attachment["origin_root"] == str(old)
    with repository_scope(newapp.repository, capabilities=COMPATIBILITY_CAPABILITIES):
        loaded = newapp.repository.load_head(Path(cold["plot"]))
    assert all(Path(name).is_relative_to(moved.root) for name in loaded["binding"]["scientific_content_files"])
    assert not old.exists() and not sources.exists()


def test_attaching_an_already_tracked_old_namespace_retires_its_current_writer_and_derivatives(tmp_path):
    project = tmp_path / "already-tracked-project"
    project.mkdir()
    created = standalone().create(request_for_source(project))
    old = Path(created["plot"])
    before_bytes = bytes_in(old)
    store = FileProjectStore(project)
    snapshot = store.snapshot(import_legacy=True)
    old_prefix = old.relative_to(project).as_posix()
    assert old_prefix + "/head.json" in snapshot["files"]
    app = application()
    # The explicit old-format path is already in this project's generation;
    # no ambient runtime scope may let it fall back to the standalone writer.
    opened = app.open(old)
    current = store.snapshot()
    assert current["projection_status"] == "current", current["outside_changes"]
    assert opened["plot_id"] == created["plot_id"]
    old_members = {name for name in current["files"] if name.startswith(old_prefix + "/")}
    assert old_members == {old_prefix + "/head.json", old_prefix + "/" + OWNER}
    assert json.loads(store.read_bytes(old_prefix + "/head.json"))["kind"] == "sciplot_attached_semantic_redirect"
    entry = next(iter(json.loads(store.read_bytes(INDEX))["attachments"].values()))
    assert {key: data for key, data in bytes_in(Path(entry["history_root"])).items() if key != OWNER} == before_bytes


def test_tracked_old_namespace_can_attach_after_project_moved_without_rewriting_its_seal(tmp_path):
    project = tmp_path / "original-project"
    project.mkdir()
    created = standalone().create(request_for_source(project))
    old = Path(created["plot"])
    revision = (old / "revisions/00000000.json").read_bytes()
    store = FileProjectStore(project)
    identity = store.snapshot(import_legacy=True)["project_id"]
    bundle = store.export_bundle(tmp_path / "bundle")
    project.rename(tmp_path / "offline")
    moved = FileProjectStore.import_bundle(bundle, tmp_path / "moved")
    app = application()
    with project_runtime(moved):
        opened = app.open(old)
        exported = app.export(Path(opened["plot"]))
    assert opened["plot_id"] == created["plot_id"] and exported["scientific_hash"] == created["scientific_hash"]
    entry = next(iter(json.loads(moved.read_bytes(INDEX))["attachments"].values()))
    assert entry["origin_root"] == str(old) and entry["transfer_root"] != str(old)
    assert app.open(Path(entry["transfer_root"]))["plot"] == opened["plot"]
    assert moved.read_bytes(entry["namespace"] + "/revisions/00000000.json") == revision
    assert moved.snapshot()["project_id"] == identity and moved.snapshot()["projection_status"] == "current"
    assert not old.exists()


def test_other_project_cannot_adopt_an_already_tracked_legacy_namespace(tmp_path):
    project = tmp_path / "original-project"
    project.mkdir()
    created = standalone().create(request_for_source(project))
    old = Path(created["plot"])
    original = FileProjectStore(project)
    before = original.snapshot(import_legacy=True)
    foreign_root = tmp_path / "foreign-project"
    foreign_root.mkdir()
    foreign = FileProjectStore(foreign_root)
    foreign_before = foreign.snapshot(import_legacy=True)
    with project_runtime(foreign), pytest.raises(EngineError) as error:
        application().open(old)
    assert error.value.reason_code == "semantic_attachment_project_conflict"
    assert not (old / OWNER).exists()
    assert original.snapshot()["generation"] == before["generation"]
    assert foreign.snapshot()["generation"] == foreign_before["generation"]


def test_tracked_namespace_imports_the_latest_legal_old_commit_after_early_project_snapshot(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    legacy = standalone()
    created = legacy.create(request_for_source(project))
    old = Path(created["plot"])
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    edited = legacy.patch(old, patch(created, "late-old-commit", "style.line.width", "1.2pt", "series:A"))
    assert edited["ready_to_use"] and edited["revision"] == 1
    latest = bytes_in(old)
    opened = application().open(old)
    assert opened["revision"] == 1 and opened["scientific_hash"] == created["scientific_hash"]
    entry = next(iter(json.loads(store.read_bytes(INDEX))["attachments"].values()))
    assert {name: data for name, data in bytes_in(Path(entry["history_root"])).items() if name != OWNER} == latest
    assert store.read_bytes(entry["namespace"] + "/revisions/00000001.json") == latest["revisions/00000001.json"]
    assert store.snapshot()["projection_status"] == "current"


def _query_tree(root):
    """Persistent read-only means bytes, permission, mtime and membership."""
    return {str(path.relative_to(root)): (path.stat().st_mode, path.stat().st_mtime_ns,
            path.read_bytes() if path.is_file() else None)
            for path in [root, *root.rglob('*')]}


def _query_plan(created):
    return {"mode": "plan", "plot_id": created["plot_id"], "base_revision": created["revision"],
            "idempotency_key": "read-only-plan", "property": "axis.label",
            "target_id": "axis:xb", "value": "Frequency, Hz"}


@pytest.mark.parametrize("state", ["standalone", "tracked", "moved", "attached-cold"])
@pytest.mark.parametrize("entry", ["describe", "plan", "typed-plan"])
def test_queries_never_migrate_or_install_persistent_views(tmp_path, state, entry):
    from test_figure_document import request_for_figure
    from sciplot_core.project_lifecycle.contracts import NormalizedCommand, RevisionToken
    from sciplot_core.plot_engine.typed_intent import compile_intent

    project = tmp_path / "original"
    project.mkdir()
    created = standalone().create(request_for_figure(project))
    assert created["ready_to_use"]
    root = Path(created["plot"])
    document = standalone().repository.load_head(root)["document"]
    store = None
    if state != "standalone":
        store = FileProjectStore(project)
        store.snapshot(import_legacy=True)
    app = application()
    if state == "moved":
        bundle = store.export_bundle(tmp_path / "bundle")
        project.rename(tmp_path / "offline")
        store = FileProjectStore.import_bundle(bundle, tmp_path / "moved")
    elif state == "attached-cold":
        with project_runtime(store):
            root = Path(app.open(root)["plot"])
        cache = project / ".sciplot_store" / "semantic-derived"
        if cache.exists():
            shutil.rmtree(cache)
    before = _query_tree(tmp_path)
    with project_runtime(store) if store is not None else nullcontext():
        if entry == "describe":
            result = app.describe(root)
        elif entry == "plan":
            result = app.intent(root, _query_plan(created))
        else:
            request = _query_plan(created)
            business, _ = compile_intent(document, request)
            command = NormalizedCommand.create("intent", request,
                expected_revision=RevisionToken.of(document), business_request=business)
            result = app.execute(root, command)
    assert result["plot_id"] == created["plot_id"]
    assert _query_tree(tmp_path) == before


def test_query_capture_rechecks_selected_namespace_and_refuses_every_write(tmp_path):
    project = tmp_path / "original"
    project.mkdir()
    created = standalone().create(request_for_source(project))
    root = Path(created["plot"])
    store = FileProjectStore(project)
    head = store.snapshot(import_legacy=True)
    active_bytes = (root / "active.json").read_bytes()
    app = application()
    with project_runtime(store), repository_scope(app.repository):
        with pytest.raises(EngineError) as caught:
            with app.repository.query_scope(root):
                original = app.repository.load_head(root)
                with pytest.raises(EngineError, match="query"):
                    app.repository.lease(root)
                with pytest.raises(EngineError, match="query"):
                    app.repository.write(root / "active.json", {"key": "unauthorized"})
                pointer = root / "head.json"
                pointer.write_bytes(pointer.read_bytes() + b"\n")  # independent noncooperative actor
                assert app.repository.load_head(root) == original
        assert caught.value.reason_code == "document_inputs_changed"
    assert store.snapshot()["generation"] == head["generation"]
    assert not store.commands() and (root / "active.json").read_bytes() == active_bytes


def test_query_capture_allows_an_unrelated_project_command(tmp_path):
    from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation

    project = tmp_path / "original"
    project.mkdir()
    created = standalone().create(request_for_source(project))
    root = Path(created["plot"])
    store = FileProjectStore(project)
    head = store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store), repository_scope(app.repository), app.repository.query_scope(root):
        original = app.repository.load_head(root)
        command = ProjectCommand.create("figure_set", "unrelated-query-concurrent", project_id=head["project_id"],
            expected_generation=head["generation"], read_set={"unrelated.json": None}, write_set=["unrelated.json"], request={})
        ProjectCommands(store).execute(command, lambda: ProjectMutation({"unrelated.json": b"{}\n"}, {}))
        assert app.repository.load_head(root) == original
    assert store.snapshot()["generation"] != head["generation"]
    assert len(store.commands()) == 1


@pytest.mark.parametrize("moved", [False, True])
@pytest.mark.parametrize("sealed", [False, True])
def test_tracked_query_uses_real_managed_source_identity_without_adopting_aliases(tmp_path, moved, sealed):
    from copy import deepcopy
    from sciplot_core.plot_engine.managed_backend import ManagedBackend as RealManagedBackend

    project = tmp_path / "original"
    project.mkdir()
    created = standalone().create(request_for_source(project))
    root = Path(created["plot"])
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    if moved:
        bundle = store.export_bundle(tmp_path / "bundle")
        project.rename(tmp_path / "offline")
        store = FileProjectStore.import_bundle(bundle, tmp_path / "moved")
    from sciplot_core.project_store.incoming_sources import SourceExpectation
    from sciplot_core.project_store.runtime import sealed_source_runtime
    if sealed:
        snapshot = store.snapshot()
        source = next(iter(snapshot["sources"].values()))
        version, entry = next(iter(source.items()))
        identity = entry["source_id"]
        physical = store.root / "A.csv"
        physical.write_bytes(b"a new independent live source revision")
        source_context = sealed_source_runtime(store, [SourceExpectation(entry["locator"], identity, version)])
    else:
        source_context = project_runtime(store)
    app = application()
    before = _query_tree(tmp_path)
    with source_context, repository_scope(app.repository), app.repository.query_scope(root):
        head = app.repository.load_head(root)
        document = head["document"]
        source = document["scientific"]["data_sources"][0]
        actual = next(path for path, sha in head["binding"]["fingerprint"]["files"].items() if sha == source["sha256"])
        assert RealManagedBackend._source_hash(document, actual, source["sha256"]) == source["sha256"]
        foreign = deepcopy(document)
        foreign["scientific"]["data_sources"][0]["source_id"] = "unknown-semantic-alias"
        assert RealManagedBackend._source_hash(foreign, actual, source["sha256"]) is None
    assert _query_tree(tmp_path) == before


@pytest.mark.parametrize("change_source", [False, True])
def test_current_query_does_not_turn_into_a_sealed_read_after_unrelated_generation(tmp_path, change_source):
    from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
    from sciplot_core.plot_engine.managed_backend import ManagedBackend as RealManagedBackend

    project = tmp_path / "original"
    project.mkdir()
    created = standalone().create(request_for_source(project))
    root = Path(created["plot"])
    store = FileProjectStore(project)
    baseline = store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store), repository_scope(app.repository), app.repository.query_scope(root):
        document = app.repository.load_head(root)["document"]
        source = document["scientific"]["data_sources"][0]
        assert RealManagedBackend._source_hash(document, source["path"], source["sha256"]) == source["sha256"]
        command = ProjectCommand.create("figure_set", "concurrent-currentness", project_id=baseline["project_id"],
            expected_generation=baseline["generation"], read_set={"unrelated.json": None}, write_set=["unrelated.json"], request={})
        ProjectCommands(store).execute(command, lambda: ProjectMutation({"unrelated.json": b"{}\n"}, {}))
        if change_source:
            Path(source["path"]).write_bytes(b"an independently changed original input")
        actual = RealManagedBackend._source_hash(document, source["path"], source["sha256"])
        assert actual == (None if change_source else source["sha256"])


def test_tracked_legacy_query_preserves_path_and_sha_only_source_identity(tmp_path):
    from test_plot_engine import FakeBackend

    project = tmp_path / "original"
    project.mkdir()
    backend = FakeBackend(project)
    document, binding = backend.initial()
    assert "source_id" not in document["scientific"]["data_sources"][0]
    root = project / ".sciplot_documents" / "legacy-read-fixture"
    FileProjectRepository().commit(root, document, binding, "import")
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application(backend=backend)
    before = _query_tree(tmp_path)
    with project_runtime(store):
        described = app.describe(root)
    assert described["plot_id"] == document["plot_id"] and described["status"] == "current"
    assert _query_tree(tmp_path) == before


def test_explicit_decision_migrates_a_late_old_pending_preview(tmp_path):
    from test_plot_engine import FakeBackend, request

    project = tmp_path / "original"
    project.mkdir()
    backend = FakeBackend(project)
    document, binding = backend.initial()
    root = project / ".sciplot_documents" / "legacy-decision-fixture"
    repository = FileProjectRepository(lease=lambda _: nullcontext())
    repository.commit(root, document, binding, "import")
    old_app = ProjectApplication(backend, repository, targets=FilesystemProjectTargets(repository),
                                capabilities=COMPATIBILITY_CAPABILITIES)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    wire = {**request(changes=[{"op": "set", "target": ["title:main"],
            "property": "title.text", "value": "Reviewed title"}]), "intent_class": "review"}
    pending = old_app.patch(root, wire)
    assert pending["status"] == "needs_review"
    app = application(backend=backend)
    completed = app.decide(root, pending["next_step"]["request"])
    assert completed["ready_to_use"] and completed["revision"] == 1
    assert completed["scientific_hash"] == document["scientific_hash"]
