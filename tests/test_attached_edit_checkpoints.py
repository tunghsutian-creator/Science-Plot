"""Public default edit entries belong to the attached project generation."""
from pathlib import Path

import pytest
from test_attached_semantic_repository import SourceAwareManagedBackend
from test_figure_document import request_for_figure

from sciplot_core.plot_engine import compat
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.task_common_edits import edit_task
from sciplot_core.task_shortcuts import style_task


@pytest.mark.parametrize("operation", ["common", "style", "outer_style"])
def test_public_default_attached_checkpoint_is_committed_before_patch(tmp_path, monkeypatch, operation):
    project = tmp_path / "project"
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    service = PlotService(SourceAwareManagedBackend())
    monkeypatch.setattr("sciplot_core.task_common_edits.doctor_payload", lambda: {"kind": "doctor", "status": "ready", "checks": []})
    monkeypatch.setattr(compat, "PlotService", lambda: service)
    try:
        created = service.create(request_for_figure(tmp_path), project=project)
        root = Path(created["plot"])
        original = service.patch
        observed = []
        def patch(plot, request):
            entries = [name for name in store.snapshot()["files"] if name.endswith(("semantic-edit.json", "semantic-style.json"))]
            assert len(entries) == 1
            observed.append(store.read_bytes(entries[0]))
            return original(plot, request)
        monkeypatch.setattr(service, "patch", patch)
        result = (edit_task(root, font_size="9pt", service=service) if operation == "common" else
                  style_task(project if operation == "outer_style" else root, all_samples=True, width="1.2pt"))
        assert result["ready_to_use"] and result["revision"] == 1
        assert observed and result["scientific_hash"] == created["scientific_hash"]
    finally:
        service.close()


@pytest.mark.parametrize("operation", ["common", "style"])
def test_public_default_legacy_checkpoint_preserves_project_guard(tmp_path, monkeypatch, operation):
    from test_plot_engine import FakeBackend
    from sciplot_core.project_store.runtime import project_runtime

    project = tmp_path / "project"
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    backend = FakeBackend(tmp_path / "backend")
    imported = backend.import_project
    def import_project(*args, **kwargs):
        document, binding = imported(*args, **kwargs)
        document["presentation"]["objects"]["series:E2"]["properties"]["style.line.color"] = "#000000"
        document["presentation"]["objects"]["series:E2"]["capabilities"]["style.line.color"] = {"type": "color", "risk": "presentation"}
        from sciplot_core.plot_document import seal_document
        document = seal_document(document)
        return document, {**binding, "project": str(project)}
    monkeypatch.setattr(backend, "import_project", import_project)
    service = PlotService(backend, resolve_figure=lambda *_: {"project": str(project), "figure_id": "primary"})
    monkeypatch.setattr("sciplot_core.task_common_edits.doctor_payload", lambda: {"kind": "doctor", "status": "ready", "checks": []})
    monkeypatch.setattr(compat, "PlotService", lambda: service)
    try:
        with project_runtime(store):
            opened = service.open(project)
        root = Path(opened["plot"])
        result = (edit_task(root, palette="tol_bright", service=service) if operation == "common" else
                  style_task(root, all_samples=True, width="1.2pt"))
        assert result["ready_to_use"] and result["revision"] == 1
        assert result["scientific_hash"] == opened["scientific_hash"]
    finally:
        service.close()


def test_bound_default_checkpoint_cold_replays_literal_intent_before_discovery(tmp_path, monkeypatch):
    import json
    from sciplot_core.plot_engine.edit_entry import read_edit_entry

    project = tmp_path / "project"
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    backend = SourceAwareManagedBackend()
    service = PlotService(backend)
    monkeypatch.setattr("sciplot_core.task_common_edits.doctor_payload", lambda: {"kind": "doctor", "status": "ready", "checks": []})
    created = service.create(request_for_figure(tmp_path), project=project)
    original_root = Path(created["plot"])
    first = edit_task(original_root, font_size="9pt", service=service)
    entry = Path(first["edit_entry"])
    logical = (entry / "semantic-edit.json").relative_to(project).as_posix()
    original = store.read_bytes(logical)
    saved = json.loads(original)
    assert saved["intent"]["target"] == saved["plot"] == str(original_root)
    assert saved["request"]["base_revision"] == 0
    history = {name: store.read_bytes(name) for name in store.snapshot()["files"] if "/revisions/" in name}
    bundle = store.export_bundle(tmp_path / "bundle")
    service.close()
    project.rename(tmp_path / "offline")
    moved = FileProjectStore.import_bundle(bundle, tmp_path / "moved")
    replay_entry = moved.root / entry.relative_to(project)
    cold = PlotService(SourceAwareManagedBackend())
    monkeypatch.setattr(cold, "open", lambda *_a, **_k: pytest.fail("replay discovered a new baseline"))
    try:
        replayed = edit_task(original_root, font_size="9pt", task_dir=replay_entry, service=cold)
        assert replayed["ready_to_use"] and replayed["revision"] == 1
        assert cold.backend.backend.calls["apply"] == 0
        assert {name: moved.read_bytes(name) for name in history} == history
        assert replayed["scientific_hash"] == created["scientific_hash"]
        assert moved.read_bytes(logical) == original
        assert read_edit_entry(replay_entry, "semantic-edit.json") == saved
    finally:
        cold.close()


@pytest.mark.parametrize("external", [False, True])
def test_checkpoint_survives_export_failure_and_never_rebinds(tmp_path, monkeypatch, external):
    from copy import deepcopy
    from sciplot_core.plot_engine.edit_entry import read_edit_entry

    project = tmp_path / "project"
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    backend = SourceAwareManagedBackend()
    service = PlotService(backend)
    monkeypatch.setattr("sciplot_core.task_common_edits.doctor_payload", lambda: {"kind": "doctor", "status": "ready", "checks": []})
    try:
        created = service.create(request_for_figure(tmp_path), project=project)
        root = Path(created["plot"])
        backend.fail_export = True
        first = edit_task(root, font_size="9pt", task_dir=tmp_path / "external" if external else None, service=service)
        assert first["commit_status"] == "committed" and first["export_status"] == "pending"
        entry = Path(first["edit_entry"])
        saved = deepcopy(read_edit_entry(entry, "semantic-edit.json"))
        counts = dict(backend.calls)
        backend.fail_export = False
        monkeypatch.setattr(service, "open", lambda *_a, **_k: pytest.fail("replay rebound intent"))
        replay = edit_task(root, font_size="9pt", task_dir=entry, service=service)
        assert replay["ready_to_use"] and replay["revision"] == 1
        assert backend.calls["apply"] == counts["apply"]
        assert read_edit_entry(entry, "semantic-edit.json") == saved
        with pytest.raises(ValueError):
            edit_task(root, font_size="10pt", task_dir=entry, service=service)
        assert read_edit_entry(entry, "semantic-edit.json") == saved
        assert any(name.endswith("semantic-edit.json") for name in store.snapshot()["files"]) is (not external)
    finally:
        service.close()


def test_recognized_outer_project_checkpoint_has_no_local_writer(tmp_path, monkeypatch):
    from sciplot_core.plot_engine.edit_entry import bind_edit_entry, edit_entry_owner, edit_entry_session, read_edit_entry
    from sciplot_core.project_lifecycle.repository import FileProjectRepository

    project = tmp_path / "native-project"
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    entry = project / "compatibility" / "native-style"
    saved = {"intent": {"plot": str(project)}, "request": {"idempotency_key": "same"}}
    monkeypatch.setattr(FileProjectRepository, "write", lambda *_: pytest.fail("checkpoint escaped generation owner"))
    with edit_entry_session(entry):
        assert bind_edit_entry(entry, "semantic-style.json", saved) == saved
    assert edit_entry_owner(entry) == "semantic-style.json"
    assert read_edit_entry(entry, "semantic-style.json") == saved
    assert "compatibility/native-style/semantic-style.json" in store.snapshot()["files"]
    with pytest.raises(ValueError):
        read_edit_entry(entry, "semantic-edit.json")


def test_default_checkpoint_exception_and_two_project_scopes_reset(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from sciplot_core.foundation.source_locations import selected_source_resolver
    from sciplot_core.plot_engine.edit_entry import edit_entry_session
    from sciplot_core.project_store.runtime import selected_project_store

    def invoke(name):
        project = tmp_path / name
        project.mkdir()
        store = FileProjectStore(project)
        store.snapshot(import_legacy=True)
        with pytest.raises(RuntimeError, match=name):
            with edit_entry_session(project / "compatibility" / "entry"):
                assert selected_project_store().root == project
                raise RuntimeError(name)
        assert selected_source_resolver() is None
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(invoke, ["A", "B"]))
    assert selected_source_resolver() is None


@pytest.mark.parametrize("protected", ["source", "output", "document", "revision"])
def test_internal_compatibility_exception_never_covers_scientific_or_execution_state(tmp_path, protected):
    from sciplot_core.plot_engine.edit_entry import admit_edit_entry

    root = tmp_path / "project/.sciplot_semantic/figure"
    entry = root / ("revisions/key" if protected == "revision" else "compatibility/key")
    head = {"document": {"scientific": {"data_sources": [{"path": str(tmp_path / "raw.csv")}]}},
            "binding": {"project": str(tmp_path / "project")}}
    if protected == "source":
        head["document"]["scientific"]["data_sources"][0]["path"] = str(root / "compatibility")
    elif protected != "revision":
        head["binding"][protected] = str(root / "compatibility")
    with pytest.raises(ValueError) as failed:
        admit_edit_entry(entry, root, head)
    assert failed.value.reason_code == "task_path_overlap"
    assert not entry.exists()
