"""Every public semantic create surface binds one explicitly selected project."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import anyio
import pytest

from managed_plot_helpers import request_for_source
from test_attached_semantic_repository import SourceAwareManagedBackend
from sciplot_core import cli
from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_protocol import rpc
from sciplot_core.project_lifecycle.attachment_index import INDEX
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.repository import FileProjectRepository, digest
from sciplot_core.project_store import FileProjectStore, ResourceRoot
from sciplot_core.project_store.runtime import project_runtime, selected_project_store


def initialized_project(path):
    path.mkdir()
    (path / "unchanged.txt").write_text("existing project member")
    store = FileProjectStore(path)
    store.snapshot(import_legacy=True)
    return store


def wire_request(tmp_path):
    directory = tmp_path / "sources"
    directory.mkdir()
    return request_for_source(directory)


def public_create(interface, service, request, project, tmp_path, monkeypatch, capsys):
    params = {"request": request, "project": str(project)}
    if interface == "python":
        return service.create(request, project=project)
    if interface == "rpc":
        response = rpc.handle(service, {"jsonrpc": "2.0", "id": 1, "method": "plot.create", "params": params})
        assert "error" not in response, response
        return response["result"]
    def dispatch(method, arguments, **_kwargs):
        assert method == "plot.create" and arguments == params
        return rpc.invoke(service, method, arguments)
    if interface == "cli":
        from sciplot_core.cli.dispatch import plots
        path = tmp_path / "request.json"
        path.write_text(json.dumps(request))
        monkeypatch.setattr(plots, "call", dispatch)
        assert cli.main(["plot", "create", "--request", str(path), "--project", str(project), "--json", "--direct"]) == 0
        return json.loads(capsys.readouterr().out)
    from sciplot_core.mcp_server.server import Adapter
    from sciplot_core.plot_protocol import client
    monkeypatch.setattr(client, "call", dispatch)
    async def invoke():
        result = await Adapter().call("sciplot_plot_create", params)
        assert not result.is_error, result.structured_content
        return result.structured_content
    return anyio.run(invoke)


@pytest.mark.parametrize("interface", ["python", "rpc", "cli", "mcp"])
def test_public_create_attaches_once_and_cold_bundle_keeps_scientific_request(interface, tmp_path, monkeypatch, capsys):
    store = initialized_project(tmp_path / "project")
    request = wire_request(tmp_path)
    original_request = deepcopy(request)
    source = Path(request["data_binding"]["data_sources"][0]["path"])
    raw = source.read_bytes()
    service = PlotService(SourceAwareManagedBackend())
    monkeypatch.setattr(FileProjectRepository, "write", lambda *_: pytest.fail("Attached state escaped the project generation"))
    monkeypatch.setattr(FileProjectRepository, "publish_content", lambda *_: pytest.fail("Attached scientific content escaped the generation"))
    created = public_create(interface, service, request, store.root, tmp_path, monkeypatch, capsys)
    root = Path(created["plot"])
    assert root.parent == store.root / ".sciplot_semantic" and created["ready_to_use"]
    assert selected_source_resolver() is None and selected_project_store() is None
    assert request == original_request and source.read_bytes() == raw
    assert not (source.parent / ".sciplot_documents").exists()
    before = store.snapshot()
    index = json.loads(store.read_bytes(INDEX))
    assert len(index["attachments"]) == 1
    creation = json.loads(store.read_bytes(root.relative_to(store.root).as_posix() + "/managed-creation.json"))
    assert creation["request"] == original_request and "project" not in creation["request"]
    assert creation["request_hash"] == digest(original_request)
    history = {name: store.read_bytes(name) for name in before["files"] if "/revisions/" in name or "/models/" in name}
    bundle = store.export_bundle(tmp_path / "bundle")
    store.root.rename(tmp_path / "project-offline")
    source.parent.rename(tmp_path / "source-offline")
    moved = FileProjectStore.import_bundle(bundle, tmp_path / "moved")
    shutil.rmtree(moved.root / ".sciplot_store/semantic-derived", ignore_errors=True)
    cold = PlotService(SourceAwareManagedBackend())
    opened = cold.open(moved.root, figure_id=created["plot_id"])
    exported = cold.export(Path(opened["plot"]))
    assert opened["plot_id"] == created["plot_id"] and exported["scientific_hash"] == created["scientific_hash"]
    assert {name: moved.read_bytes(name) for name in history} == history
    assert moved.read_bytes("unchanged.txt") == b"existing project member"
    assert not source.exists() and selected_source_resolver() is None


@pytest.mark.parametrize("invalid", [None, "", "relative", {}, []])
def test_rpc_selected_project_shape_and_unknown_envelope_fields_refuse(invalid):
    with pytest.raises(rpc.ProtocolError) as error:
        rpc.validate_params("plot.create", {"request": {}, "project": invalid})
    assert error.value.reason_code == "invalid_rpc_params"
    with pytest.raises(rpc.ProtocolError):
        rpc.validate_params("plot.create", {"request": {}, "project": "/exact/project", "locations": {"foreign": "/"}})


@pytest.mark.parametrize("case", ["missing", "unregistered", "nested", "outside", "symlink"])
def test_invalid_project_or_borrowed_output_cannot_create_or_repair_a_store(tmp_path, monkeypatch, case):
    selected = initialized_project(tmp_path / "selected")
    other = initialized_project(tmp_path / "other")
    request = wire_request(tmp_path)
    project = selected.root
    if case == "missing":
        project = tmp_path / "missing"
    elif case == "unregistered":
        project = tmp_path / "empty"
        project.mkdir()
    elif case == "symlink":
        project = tmp_path / "linked"
        project.symlink_to(selected.root, target_is_directory=True)
    elif case == "outside":
        request["out"] = str(other.root / "new-output")
    else:
        nested = initialized_project(selected.root / "nested")
        request["out"] = str(nested.root / "new-output")
    def files(path):
        return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*") if p.is_file()}
    original = files(selected.root), files(other.root)
    monkeypatch.setattr(FileProjectStore, "recover", lambda *_: pytest.fail("Invalid host selection repaired a project"))
    with pytest.raises((EngineError, ValueError)):
        PlotService(SourceAwareManagedBackend()).create(request, project=project)
    assert (files(selected.root), files(other.root)) == original
    assert not (tmp_path / "missing").exists() and not (tmp_path / "empty/.sciplot_store").exists()
    assert selected_source_resolver() is None


def test_host_scope_preserves_existing_resource_caps_and_resets_after_failure(tmp_path):
    from sciplot_core.plot_engine.selected_project import selected_project_creation
    store = initialized_project(tmp_path / "project")
    external = tmp_path / "explicit-resource"
    external.mkdir()
    (external / "allowed.txt").write_text("exact host file")
    trusted = FileProjectStore(store.root, locations={"delivery": ResourceRoot(external, ("allowed.txt",))})
    with project_runtime(trusted):
        assert selected_project_store() is trusted
        with pytest.raises(RuntimeError), selected_project_creation(store.root, {"template_definition": {}}):
            assert selected_project_store() is trusted
            raise RuntimeError("synthetic downstream failure")
        assert selected_project_store() is trusted and trusted.location_members["delivery"] == ("allowed.txt",)
    assert selected_project_store() is None


def test_no_project_stays_standalone_and_scientific_request_cannot_select_one(tmp_path):
    request = wire_request(tmp_path)
    service = PlotService(SourceAwareManagedBackend())
    created = service.create(request)
    assert ".sciplot_semantic" not in Path(created["plot"]).parts and selected_project_store() is None
    request["project"] = str(tmp_path / "hidden-project")
    with pytest.raises(Exception) as error:
        service.create(request)
    assert getattr(error.value, "reason_code", None) == "plot_invalid_create"
    assert not (tmp_path / "hidden-project").exists()


@pytest.mark.parametrize("mode", ["source_only", "legacy"])
def test_selected_project_does_not_silently_route_to_another_creation_family(tmp_path, mode):
    store = initialized_project(tmp_path / "project")
    request = {"source": str(tmp_path / "raw.csv"), "rule_id": "uvvis_spectrum"}
    if mode == "legacy":
        request = {**wire_request(tmp_path), "mode": "legacy"}
    before = store.snapshot()["generation"]
    with pytest.raises(EngineError) as error:
        PlotService(SourceAwareManagedBackend()).create(request, project=store.root)
    assert error.value.reason_code == "semantic_project_creation_unsupported"
    assert store.snapshot()["generation"] == before and not (tmp_path / ".sciplot_documents").exists()


def test_pending_project_is_not_repaired_or_used_by_public_create(tmp_path, monkeypatch):
    from sciplot_core.project_store import ProjectRecoveryRequired, state
    store = initialized_project(tmp_path / "project")
    before = store.snapshot()
    logical = "unchanged.txt"
    store.reserve("pending", "pending-digest", expected_generation=before["generation"],
                  read_set={logical: before["files"][logical]["sha256"]}, write_set=[logical])
    boundary = state.boundary
    def stop(name):
        if name == "after_head":
            raise RuntimeError("synthetic committed head before projection")
        boundary(name)
    monkeypatch.setattr(state, "boundary", stop)
    with pytest.raises(RuntimeError, match="committed head"):
        store.publish("pending", "pending-digest", writes={logical: b"committed but not installed"}, result={})
    monkeypatch.setattr(state, "boundary", boundary)
    files = {p.relative_to(store.root).as_posix(): p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    monkeypatch.setattr(FileProjectStore, "recover", lambda *_: pytest.fail("Create repaired the pending project"))
    with pytest.raises(ProjectRecoveryRequired):
        PlotService(SourceAwareManagedBackend()).create(wire_request(tmp_path), project=store.root)
    assert {p.relative_to(store.root).as_posix(): p.read_bytes() for p in store.root.rglob("*") if p.is_file()} == files
    assert selected_project_store() is None


def test_selected_project_contexts_are_separate_for_concurrent_host_calls(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sciplot_core.plot_engine.selected_project import selected_project_creation
    stores = [initialized_project(tmp_path / name) for name in ("A", "B")]
    barrier = Barrier(2)
    def select(store):
        with selected_project_creation(store.root, {"template_definition": {}}):
            barrier.wait(timeout=5)
            assert selected_project_store().root == store.root
        assert selected_project_store() is None
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(select, stores))
    assert selected_project_store() is None


@pytest.mark.parametrize("extra", [{"locations": {"foreign": "/"}}, {"project": "relative"}, {"project": None}])
def test_mcp_project_envelope_remains_closed_before_domain_call(tmp_path, monkeypatch, extra):
    from sciplot_core.mcp_server import server
    monkeypatch.setattr(server, "invoke_owner", lambda *_: pytest.fail("Invalid host envelope reached an owner"))
    async def invoke():
        result = await server.Adapter().call("sciplot_plot_create", {"request": wire_request(tmp_path), **extra})
        assert result.is_error and result.structured_content["error"]["code"] == "invalid_arguments"
    anyio.run(invoke)


def test_public_create_restores_scope_and_reuses_one_attached_revision_after_export_failure(tmp_path):
    store = initialized_project(tmp_path / "project")
    request = wire_request(tmp_path)
    backend = SourceAwareManagedBackend()
    backend.fail_export = True
    service = PlotService(backend)
    interrupted = service.create(request, project=store.root)
    assert interrupted["commit_status"] == "committed" and interrupted["export_status"] == "pending"
    assert not interrupted["ready_to_use"] and selected_project_store() is None
    backend.fail_export = False
    resumed = service.create(request, project=store.root)
    assert resumed["ready_to_use"] and resumed["revision"] == interrupted["revision"] == 0
    assert resumed["plot_id"] == interrupted["plot_id"] and resumed["scientific_hash"] == interrupted["scientific_hash"]
    assert len(json.loads(store.read_bytes(INDEX))["attachments"]) == 1
    assert selected_project_store() is None and backend.calls["apply"] == 0


def test_public_create_reuses_admitted_warm_native_delivery_and_finite_snapshot_caps(tmp_path):
    from sciplot_core.project_store.adapters import publish_files
    from sciplot_core.project_lifecycle.store_composition import existing_store
    project = tmp_path / "project"
    project.mkdir()
    delivery = tmp_path / "figures"
    delivery.mkdir()
    (delivery / "existing.pdf").write_bytes(b"existing public native export")
    (project / "plot_request.json").write_text(json.dumps({"delivery_output": str(delivery)}))
    archive = tmp_path / "project.zip"
    archive.write_bytes(b"existing snapshot")
    store = FileProjectStore(project, locations={"delivery": delivery,
        "snapshot": ResourceRoot(tmp_path, (archive.name,))})
    store.snapshot(import_legacy=True)
    publish_files(store, {"@snapshot/project.zip": archive.read_bytes()}, kind="publish")
    before = (delivery / "existing.pdf").read_bytes(), archive.read_bytes()
    request = wire_request(tmp_path)
    created = PlotService(SourceAwareManagedBackend()).create(request, project=project)
    assert created["ready_to_use"] and Path(created["plot"]).is_relative_to(project / ".sciplot_semantic")
    restored = existing_store(project)
    assert restored.locations == {"delivery": delivery, "snapshot": tmp_path}
    assert restored.location_members["snapshot"] == ("project.zip",)
    assert (delivery / "existing.pdf").read_bytes() == before[0] and archive.read_bytes() == before[1]
    assert restored.snapshot()["outside_changes"] == {} and selected_project_store() is None


def test_public_create_rejects_modified_native_capability_request_before_host_factory(tmp_path, monkeypatch):
    from sciplot_core.studio_core import project_command_scope
    project = tmp_path / "project"
    project.mkdir()
    request_path = project / "plot_request.json"
    request_path.write_text(json.dumps({"delivery_output": str(tmp_path / "original-delivery")}))
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    request_path.write_text(json.dumps({"delivery_output": str(tmp_path / "victim-delivery")}))
    monkeypatch.setattr(project_command_scope, "project_store", lambda *_a, **_kw: pytest.fail("Changed native request minted a capability"))
    with pytest.raises(EngineError) as error:
        PlotService(SourceAwareManagedBackend()).create(wire_request(tmp_path), project=project)
    assert error.value.reason_code == "semantic_project_changed"
    assert not (tmp_path / "victim-delivery").exists()
    assert store.snapshot()["generation"] == before["generation"]
    assert selected_project_store() is None
