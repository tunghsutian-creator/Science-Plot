"""Coherent metadata/member reads preserve physical and attached batch fences."""

from collections import Counter
from copy import deepcopy
import json
import os
from uuid import uuid4

import pytest

from sciplot_core.project_store import FileProjectStore, ProjectStoreError, state
from sciplot_core.project_store.io import StoreIO, sha
from sciplot_core.project_store.resources import ResourceRoot
from sciplot_core.project_lifecycle.attached_repository import AttachedProjectRepository
from sciplot_core.project_lifecycle.attachment_index import Attachment, INDEX, encode, read_index


def project(tmp_path):
    root = tmp_path / "project"
    namespace = ".sciplot_semantic/" + "a" * 32
    semantic = root / namespace
    (semantic / "revisions").mkdir(parents=True)
    (semantic / "head.json").write_bytes(b'{"revision":0}')
    (semantic / "revisions/00000000.json").write_bytes(b'{"value":"old"}')
    store = FileProjectStore(root)
    snapshot = store.snapshot(import_legacy=True)
    entry = {"id": "a" * 32, "namespace": namespace, "origin_root": str(semantic),
             "project_origin": str(root), "plot_id": "plot", "figure_id": "figure"}
    return store, AttachedProjectRepository(Attachment(store, entry)), snapshot


def publish(store, writes):
    snapshot = store.snapshot()
    key = uuid4().hex
    store.reserve(key, key, expected_generation=snapshot["generation"],
                  read_set={name: snapshot["files"].get(name, {}).get("sha256") for name in writes}, write_set=list(writes))
    return store.publish(key, key, writes=writes, result={})


def install_index(store, repository):
    snapshot = store.snapshot()
    value = {"kind": "sciplot_semantic_attachment_index", "version": 1,
             "project_id": snapshot["project_id"], "attachments": {repository.attachment.entry["id"]: repository.attachment.entry}}
    publish(store, {INDEX: encode(value)})
    return value


def inventory(root):
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("projection", [False, True])
def test_bulk_observation_has_one_checked_generation_and_explicit_physical_role(tmp_path, monkeypatch, projection):
    store, repository, snapshot = project(tmp_path)
    prefix = repository.attachment.entry["namespace"]
    names = (prefix + "/head.json", prefix + "/revisions/00000000.json", prefix + "/revisions", prefix + "/missing")
    reads = Counter()
    original = StoreIO.read
    def read(io, name):
        reads[name] += 1
        return original(io, name)
    before = inventory(store.root)
    monkeypatch.setattr(StoreIO, "read", read)
    observed = store.observe_members(names, projection=projection)
    assert observed.head["generation"] == observed.selected["generation"] == snapshot["generation"]
    assert observed.members[names[0]].data == b'{"revision":0}'
    assert observed.members[names[1]].data == b'{"value":"old"}'
    assert observed.members[names[2]].kind == "directory" and observed.members[names[2]].data is None
    assert observed.members[names[3]].kind == "missing"
    assert observed.physical == {}
    assert "projection_status" not in observed.head and "projection_status" not in observed.selected
    if projection:
        assert observed.projection["projection_status"] == "current"
    else:
        assert observed.projection is None
    assert reads["head.json"] == 1
    assert sum(count for name, count in reads.items() if name.startswith("generations/")) == snapshot["sequence"] + 1
    assert inventory(store.root) == before


@pytest.mark.parametrize("entry", ["bytes", "file", "directory", "missing", "root", "index"])
def test_attached_semantic_read_family_uses_one_observation_without_old_double_call(tmp_path, monkeypatch, entry):
    store, repository, _snapshot = project(tmp_path)
    index = install_index(store, repository)
    calls, original = [], store.observe_members
    def observe(names=(), *, generation=None, projection=True, physical=(), import_legacy=False):
        calls.append((names, generation, projection, physical, import_legacy))
        return original(names, generation=generation, projection=projection, physical=physical, import_legacy=import_legacy)
    def old_snapshot(*, import_legacy=False):
        pytest.fail("semantic read split its coherent observation into legacy calls")
    def old_read_bytes(logical, *, generation=None):
        pytest.fail("semantic read split its coherent observation into legacy calls")
    monkeypatch.setattr(store, "observe_members", observe)
    monkeypatch.setattr(store, "snapshot", old_snapshot)
    monkeypatch.setattr(store, "read_bytes", old_read_bytes)
    root = repository.attachment.root
    if entry == "bytes":
        assert repository._bytes(root / "head.json") == b'{"revision":0}'
    elif entry == "index":
        assert read_index(store) == index
    else:
        path = {"file": root / "head.json", "directory": root / "revisions", "missing": root / "missing", "root": root}[entry]
        assert repository.exists(path) is (entry != "missing")
    logical = INDEX if entry in {"root", "index"} else repository.attachment.logical(
        root / ("head.json" if entry in {"file", "bytes"} else "revisions" if entry == "directory" else "missing"))
    assert calls == [((logical,), None, True, (), False)]


def test_historical_selection_cannot_masquerade_as_current_physical_metadata(tmp_path):
    store, repository, old = project(tmp_path)
    logical = repository.attachment.logical(repository.attachment.root / "head.json")
    publish(store, {logical: b'{"revision":1}'})
    observed = store.observe_members((logical,), generation=old["generation"], physical=(logical,))
    assert observed.head["generation"] != old["generation"]
    assert observed.selected["generation"] == old["generation"]
    assert observed.members[logical].data == b'{"revision":0}'
    assert observed.physical[logical][0] == b'{"revision":1}'
    assert observed.projection["files"][logical]["sha256"] == sha(b'{"revision":1}')
    assert observed.selected["files"][logical]["sha256"] == sha(b'{"revision":0}')
    assert observed.projection["projection_status"] == "current"


def test_nested_generation_mutation_refuses_a_partial_mixed_observation(tmp_path, monkeypatch):
    from sciplot_core.project_store import member_observation

    store, repository, before = project(tmp_path)
    logical = repository.attachment.logical(repository.attachment.root / "head.json")
    original = member_observation._projection
    def advance(io, current):
        projection = original(io, current)
        successor = deepcopy(current)
        successor.update(generation=uuid4().hex, parent=current["generation"], parent_sha256=state.digest(current),
                         sequence=current["sequence"] + 1)
        successor["files"][logical].update(io.put(b'{"revision":1}'))
        state.write_generation(io, successor)
        state.publish_head(io, successor)
        return projection
    with monkeypatch.context() as scoped:
        scoped.setattr(member_observation, "_projection", advance)
        with pytest.raises(ProjectStoreError, match="boundary"):
            store.observe_members((logical,))
    fresh = store.observe_members((logical,))
    assert fresh.head["generation"] != before["generation"]
    assert fresh.head["generation"] == fresh.selected["generation"]
    assert fresh.members[logical].data == b'{"revision":1}'
    assert fresh.projection["projection_status"] == "conflict"


def test_partial_bulk_failure_does_not_publish_or_reuse_captured_bytes(tmp_path, monkeypatch):
    store, repository, old = project(tmp_path)
    names = [repository.attachment.logical(repository.attachment.root / name)
             for name in ("head.json", "revisions/00000000.json")]
    publish(store, {name: b"new" for name in names})
    entry = old["files"][names[1]]
    path = store.root / ".sciplot_store/objects" / entry["sha256"][:2] / entry["sha256"]
    info, data = path.stat(), path.read_bytes()
    path.write_bytes(b"x" * len(data))
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    before = inventory(store.root)
    first_reads = []
    original = StoreIO.get
    def get(io, item):
        if item["sha256"] == old["files"][names[0]]["sha256"]:
            first_reads.append(item["sha256"])
        return original(io, item)
    monkeypatch.setattr(StoreIO, "get", get)
    with pytest.raises(ProjectStoreError, match="identity"):
        store.observe_members(names, generation=old["generation"])
    assert inventory(store.root) == before
    path.write_bytes(data)
    observed = store.observe_members(names, generation=old["generation"])
    assert observed.members[names[0]].data == b'{"revision":0}'
    assert observed.members[names[1]].data == data
    assert len(first_reads) == 2


@pytest.mark.parametrize("drift", ["bytes", "mode", "hardlink"])
def test_observation_retains_snapshot_physical_drift_checks_without_changing_saved_bytes(tmp_path, drift):
    store, repository, snapshot = project(tmp_path)
    path = repository.attachment.root / "head.json"
    logical = repository.attachment.logical(path)
    before = path.stat()
    if drift == "bytes":
        path.write_bytes(b'{"revision":9}')
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif drift == "mode":
        path.chmod(before.st_mode ^ 0o100)
    else:
        os.link(path, tmp_path / "outside-link")
    observed = store.observe_members((logical,))
    assert observed.projection["projection_status"] == "conflict"
    assert logical in observed.projection["outside_changes"]
    assert (logical in observed.projection["outside_metadata"]) is (drift == "hardlink")
    assert observed.members[logical].data == b'{"revision":0}'
    assert observed.head["generation"] == snapshot["generation"]


def test_unobserved_physical_member_is_distinct_from_observed_missing_file(tmp_path, monkeypatch):
    store, repository, _snapshot = project(tmp_path)
    logical = repository.attachment.logical(repository.attachment.root / "head.json")
    unregistered = "outside.bin"
    (store.root / unregistered).write_bytes(b"outside bytes confer no member authority")
    (repository.attachment.root / "head.json").unlink()
    calls, original = [], StoreIO.physical
    def physical(io, name, *, owned=True):
        calls.append(name)
        return original(io, name, owned=owned)
    monkeypatch.setattr(StoreIO, "physical", physical)
    observed = store.observe_members((logical, unregistered), projection=False, physical=(logical, unregistered))
    assert observed.projection is None
    assert observed.physical == {logical: None}
    assert observed.members[unregistered].kind == "missing"
    assert observed.members[logical].data == b'{"revision":0}'
    assert calls == [logical]


def test_capability_change_during_observation_cannot_escape_the_checked_window(tmp_path, monkeypatch):
    store, repository, _snapshot = project(tmp_path)
    logical = repository.attachment.logical(repository.attachment.root / "head.json")
    original = StoreIO.get
    def get(io, entry):
        data = original(io, entry)
        io.location_members["foreign"] = ("private.bin",)
        return data
    # checked_head itself consumes objects before constructing its proof. Inject
    # the drift on the selected member read, after that proof has been created.
    from sciplot_core.project_store import member_observation
    original_observe = member_observation.observe
    def observed(io, current, checked, names, *, generation, projection, physical):
        assert generation is None and projection is False and physical == ()
        with monkeypatch.context() as scoped:
            scoped.setattr(StoreIO, "get", get)
            return original_observe(io, current, checked, names, generation=generation, projection=projection, physical=physical)
    monkeypatch.setattr("sciplot_core.project_store.repository.observe", observed)
    with pytest.raises(ProjectStoreError, match="boundary"):
        store.observe_members((logical,), projection=False)


def test_finite_capability_drift_is_rejected_before_consuming_ungranted_member(tmp_path):
    root, resource = tmp_path / "project", tmp_path / "resource"
    root.mkdir()
    resource.mkdir()
    (resource / "a.bin").write_bytes(b"A")
    (resource / "b.bin").write_bytes(b"B")
    store = FileProjectStore(root, locations={"resource": ResourceRoot(resource, ("a.bin", "b.bin"))})
    store.snapshot(import_legacy=True)
    restricted = FileProjectStore(root, locations={"resource": ResourceRoot(resource, ("a.bin",))})
    with pytest.raises(ProjectStoreError, match="capability"):
        restricted.observe_members(("@resource/b.bin",))


@pytest.mark.parametrize("abort", [False, True])
def test_batch_overlay_files_virtual_directories_and_partial_failure_preserve_read_set(tmp_path, abort):
    store, repository, snapshot = project(tmp_path)
    root = repository.attachment.root
    old = repository.attachment.logical(root / "revisions/00000000.json")
    new = repository.attachment.logical(root / "new/item.json")
    def edit():
        with repository.storage_batch(root):
            batch = repository._batch.get()
            repository.write(root / "new/item.json", {"value": "new"})
            batch.writes[old] = None
            assert repository.exists(root / "new") and repository.exists(root / "new/item.json")
            assert not repository.exists(root / "revisions/00000000.json")
            assert not repository.exists(root / "revisions")
            missing = repository.attachment.logical(root / "missing.json")
            assert not repository.exists(root / "missing.json")
            assert batch.reads[missing] is None and missing not in batch.directories
            assert repository.json_members(root / "revisions", "*.json") == []
            assert repository.json_members(root / "new", "*.json") == [root / "new/item.json"]
            assert json.loads(repository._bytes(root / "new/item.json")) == {"value": "new"}
            with pytest.raises(FileNotFoundError):
                repository._bytes(root / "revisions/00000000.json")
            assert batch.reads[old] == snapshot["files"][old]["sha256"] and batch.reads[new] is None
            if abort:
                raise RuntimeError("partial semantic read failure")
    if abort:
        with pytest.raises(RuntimeError, match="partial semantic read failure"):
            edit()
    else:
        edit()
    assert repository._batch.get() is None
    current = store.snapshot()
    assert (new in current["files"]) is not abort
    assert (old in current["files"]) is abort
    assert (current["generation"] == snapshot["generation"]) is abort


def test_batch_observes_its_captured_generation_after_a_new_head_without_caching_bytes(tmp_path):
    store, repository, old = project(tmp_path)
    root = repository.attachment.root
    logical = repository.attachment.logical(root / "head.json")
    new = repository.attachment.logical(root / "later/new.json")
    with repository.storage_batch(root):
        publish(store, {logical: b'{"revision":1}', new: b"later"})
        assert repository._bytes(root / "head.json") == b'{"revision":0}'
        assert not repository.exists(root / "later")
        assert repository._batch.get().reads[logical] == old["files"][logical]["sha256"]
    assert repository._bytes(root / "head.json") == b'{"revision":1}'
    assert repository.exists(root / "later")


@pytest.mark.parametrize("change", ["add", "remove"])
def test_batch_directory_observation_keeps_a_membership_cas_against_outside_members(tmp_path, change):
    store, repository, snapshot = project(tmp_path)
    root = repository.attachment.root
    prefix = repository.attachment.logical(root / "revisions")
    with pytest.raises(ProjectStoreError, match="membership"):
        with repository.storage_batch(root):
            assert repository.exists(root / "revisions")
            batch = repository._batch.get()
            assert prefix in batch.directories and prefix not in batch.reads
            repository.write(root / "new.json", {"value": "candidate"})
            if change == "add":
                (root / "revisions/outside.json").write_bytes(b"outside")
            else:
                (root / "revisions/00000000.json").unlink()
    assert store.snapshot()["generation"] == snapshot["generation"]
    assert not (root / "new.json").exists()
    if change == "add":
        assert (root / "revisions/outside.json").read_bytes() == b"outside"
    else:
        assert not (root / "revisions/00000000.json").exists()


@pytest.mark.parametrize("conflict", ["observed", "inherited"])
def test_batch_membership_merge_rejects_conflicts_without_overwriting_prepared_guards(tmp_path, conflict):
    from sciplot_core.project_commands import MembershipRead, SourceTreeRead
    from sciplot_core.project_lifecycle.errors import EngineError
    from sciplot_core.project_lifecycle.prepared_admission import PreparedReads

    store, repository, snapshot = project(tmp_path)
    root = repository.attachment.root
    prefix = repository.attachment.logical(root / "revisions")
    expected = MembershipRead.capture(snapshot["files"], prefix)
    foreign = MembershipRead.capture({}, prefix)
    assert expected != foreign
    with pytest.raises(EngineError, match="prepared membership"):
        with repository.storage_batch(root):
            batch = repository._batch.get()
            batch.prepared = PreparedReads((), (foreign,) if conflict == "observed" else (foreign, expected),
                                           SourceTreeRead(str(tmp_path), "0" * 64), {})
            assert repository.exists(root / "revisions")
            repository.write(root / "new.json", {"value": "candidate"})
    assert store.snapshot()["generation"] == snapshot["generation"]
    assert store.commands() == ()


@pytest.mark.parametrize("present", [False, True])
def test_read_index_honors_explicit_historical_presence_and_bytes(tmp_path, monkeypatch, present):
    store, repository, initial = project(tmp_path)
    first = install_index(store, repository) if present else None
    old = store.snapshot() if present else initial
    latest = {"kind": "sciplot_semantic_attachment_index", "version": 1,
              "project_id": old["project_id"], "attachments": {}} if present else install_index(store, repository)
    if present:
        publish(store, {INDEX: encode(latest)})
    calls, original = [], store.observe_members
    def observe(names=(), *, generation=None, projection=True, physical=(), import_legacy=False):
        calls.append((names, generation, projection, physical, import_legacy))
        return original(names, generation=generation, projection=projection, physical=physical, import_legacy=import_legacy)
    monkeypatch.setattr(store, "observe_members", observe)
    empty = {"kind": "sciplot_semantic_attachment_index", "version": 1,
             "project_id": old["project_id"], "attachments": {}}
    assert read_index(store, old) == (first if present else empty)
    assert calls == ([((INDEX,), old["generation"], False, (), False)] if present else [])
    assert read_index(store) == latest
    assert calls[-1] == ((INDEX,), None, True, (), False)


def test_native_request_bootstrap_observes_only_its_admitted_file_before_binding_host_caps(tmp_path, monkeypatch):
    from sciplot_core.project_lifecycle import store_composition
    from sciplot_core.studio_core import project_command_scope

    root, delivery = tmp_path / "project", tmp_path / "delivery"
    root.mkdir()
    delivery.mkdir()
    request = root / "plot_request.json"
    request.write_bytes(b"{}")
    (delivery / "file.bin").write_bytes(b"external publication")
    store = FileProjectStore(root, locations={"delivery": delivery})
    snapshot = store.snapshot(import_legacy=True)
    bootstrap = FileProjectStore(root)  # The request has not granted delivery yet.
    calls, original = [], bootstrap.observe_members
    def observe(names=(), *, generation=None, projection=True, physical=(), import_legacy=False):
        calls.append((names, generation, projection, physical, import_legacy))
        result = original(names, generation=generation, projection=projection, physical=physical, import_legacy=import_legacy)
        assert result.projection is None and result.head["generation"] == snapshot["generation"]
        assert result.physical == {"plot_request.json": (b"{}", request.stat().st_mode & 0o7777)}
        return result
    physical_reads, original_physical = [], StoreIO.physical
    def physical(io, name, *, owned=True):
        physical_reads.append((name, owned))
        return original_physical(io, name, owned=owned)
    monkeypatch.setattr(bootstrap, "observe_members", observe)
    monkeypatch.setattr(StoreIO, "physical", physical)
    monkeypatch.setattr(store_composition, "store_for_project", lambda project: bootstrap)
    factories = []
    def factory(project):
        assert project == root and len(calls) == 1
        factories.append(project)
        return store
    monkeypatch.setattr(project_command_scope, "project_store", factory)
    assert store_composition.existing_store(root) is store
    assert calls == [(("plot_request.json",), None, False, ("plot_request.json",), False)]
    assert physical_reads == [("plot_request.json", True)]
    assert factories == [root]
