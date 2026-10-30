"""Attached semantic revisions and journals use the complete project generation."""
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest

from managed_plot_helpers import patch, request_for_source
from test_project_lifecycle import ManagedBackend
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.plot_engine.managed_backend import fingerprint_input_roles
from sciplot_core.project_lifecycle.application import ProjectApplication
from sciplot_core.project_lifecycle.backend_paths import RepositoryBackendPaths
from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_lifecycle.repository import FileProjectRepository
from sciplot_core.project_lifecycle.repository_router import ComposedProjectRepository
from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime


class SourceAwareManagedBackend(ManagedBackend):
    def fingerprint(self, binding, *, input_document=None):
        if input_document is not None:
            fingerprint_input_roles(binding, input_document=input_document)
        return {"files": {path: file_sha256(resolve_source_path(path, expected_sha256=sha))
                          for path, sha in binding["fingerprint"]["files"].items()},
                "artifacts": binding["fingerprint"]["artifacts"]}


def application(repo=None, backend=None):
    from sciplot_core.project_lifecycle.attachment_preflight import preflight

    backend = backend or SourceAwareManagedBackend()
    repo = repo or ComposedProjectRepository(lease=lambda _: nullcontext(),
        attachment_admission=lambda namespace, head, attachment: preflight(backend, COMPATIBILITY_CAPABILITIES, namespace, head, attachment))
    return ProjectApplication(RepositoryBackendPaths(backend, repo), repo,
        targets=FilesystemProjectTargets(repo), capabilities=COMPATIBILITY_CAPABILITIES)


def test_attached_managed_create_patch_undo_export_has_one_generation_writer(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    wire = request_for_source(project)
    store = FileProjectStore(project)
    initial = store.snapshot(import_legacy=True)
    app = application()
    monkeypatch.setattr(FileProjectRepository, "write", lambda *_: pytest.fail("Attached semantic state escaped to FileRepo.write"))
    monkeypatch.setattr(FileProjectRepository, "publish_content", lambda *_: pytest.fail("Attached content escaped to FileRepo"))
    with project_runtime(store):
        created = app.create(wire)
    root = Path(created["plot"])
    assert root.parent == project / ".sciplot_semantic"
    assert not (project.parent / ".sciplot_documents").exists()
    snapshot = store.snapshot()
    assert snapshot["generation"] != initial["generation"]
    assert root.relative_to(project).as_posix() + "/head.json" in snapshot["files"]
    assert all("artifacts/" not in name and "/ir/" not in name for name in snapshot["files"])
    original = app.describe(root)
    edited = app.patch(root, patch(created, "style", "style.line.width", "1.2pt", "series:A"))
    assert edited["revision"] == 1 and edited["scientific_hash"] == original["scientific_hash"]
    review = app.rollback(root, {"base_revision": 1, "target_revision": 0, "idempotency_key": "undo"})
    done = app.decide(root, review["next_step"]["request"])
    assert done["revision"] == 2 and app.export(root)["scientific_hash"] == original["scientific_hash"]
    with repository_scope(app.repository, capabilities=COMPATIBILITY_CAPABILITIES):
        head = app.repository.load_head(root)
    raw = __import__("json").loads(store.read_bytes(root.relative_to(project).as_posix() + "/revisions/00000002.json"))
    assert raw["document"] == head["document"]
    assert all(record["phase"] != "applying" for record in store.commands() if record["kind"] == "semantic_record")
    assert created["plot_id"] == done["plot_id"]


def test_runtime_view_cannot_hide_original_envelope_digest_corruption(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    wire = request_for_source(project)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store):
        created = app.create(wire)
    root = Path(created["plot"])
    before = deepcopy(app.describe(root))
    # A legitimate new generation may still carry an invalid semantic pointer;
    # original semantic envelope validation must reject it before any projection.
    from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
    logical = root.relative_to(project).as_posix() + "/head.json"
    snapshot = store.snapshot()
    mutation = ProjectMutation({logical: b'{"revision":0,"sha256":"wrong"}\n'}, {})
    command = ProjectCommand.create("semantic_record", "corrupt-control", project_id=snapshot["project_id"],
        expected_generation=snapshot["generation"], read_set={logical: snapshot["files"][logical]["sha256"]},
        write_set=[logical], request={"prepared_digest": mutation.prepared_digest})
    ProjectCommands(store).publish_prepared(command, mutation)
    with pytest.raises(ValueError, match="committed pointer"):
        app.describe(root)
    assert before["plot_id"] == created["plot_id"]


def test_concurrent_applications_keep_attachment_and_source_scopes_separate(tmp_path):
    from sciplot_core.foundation.source_locations import selected_source_resolver
    from sciplot_core.project_lifecycle.attachment_index import Attachment

    barrier = Barrier(2)

    def create(name):
        project = tmp_path / name
        project.mkdir()
        wire = request_for_source(project)
        store = FileProjectStore(project)
        store.snapshot(import_legacy=True)
        app = application()
        with project_runtime(store):
            barrier.wait(timeout=10)
            result = app.create(wire)
            assert Path(result["plot"]).is_relative_to(project)
        assert selected_source_resolver() is None
        with pytest.raises(RuntimeError, match="invocation scope"):
            app.repository.select(Attachment(store, {}))
        return result, store.snapshot()["project_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ("A", "B")))
    assert results[0][1] != results[1][1]
    assert results[0][0]["plot_id"] != results[1][0]["plot_id"]
    assert results[0][0]["scientific_hash"] != results[1][0]["scientific_hash"]
    assert selected_source_resolver() is None
