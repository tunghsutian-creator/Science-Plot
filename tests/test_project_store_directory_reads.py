"""Directory resources reduce opens only within one fully checked head."""
from collections import Counter
from contextlib import contextmanager, nullcontext
import errno
import os
from pathlib import Path
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from sciplot_core.project_store import FileProjectStore, ProjectStoreError, state
from sciplot_core.project_store import io as store_io
from sciplot_core.project_store import read_directories as resources
from sciplot_core.project_store.io import STORE, StoreIO, directory


@pytest.fixture
def prepared(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "A.bin").write_bytes(b"A")
    (root / "B.bin").write_bytes(b"B")
    store = FileProjectStore(root)
    return store, store.snapshot(import_legacy=True)


def closed(descriptors):
    for descriptor in descriptors:
        with pytest.raises(OSError) as error:
            os.fstat(descriptor)
        assert error.value.errno == errno.EBADF


def held(resources_owner):
    return [item.fd for item in resources_owner.held.values()]


@pytest.mark.parametrize("change", ["none", "before_read", "during_read"])
def test_each_pooled_leaf_keeps_distinct_fresh_credential_checks(prepared, monkeypatch, change):
    store, snapshot = prepared
    original_credentials, original_read = resources._credentials, store_io.read_file
    events, changed = [], [False]

    def credentials():
        events.append("credentials")
        uid, euid, gid, egid, groups = original_credentials()
        return uid, euid, gid, egid, groups + ((-1,) if changed[0] else ())

    def read(*args, **kwargs):
        events.append("read")
        result = original_read(*args, **kwargs)
        if change == "during_read":
            changed[0] = True
        return result

    with StoreIO(store.root, {}).locked() as io:
        with pytest.raises(ProjectStoreError, match="boundary") if change != "none" else nullcontext():
            with resources.reading_directories(io, STORE):
                # Prime the actual structural descriptor, retaining all real
                # opens and permission checks on this platform.
                io.get(snapshot["files"]["A.bin"])
                owner = io._read_directories
                assert owner.reusable and "objects" in owner.held
                monkeypatch.setattr(resources, "_credentials", credentials)
                monkeypatch.setattr(store_io, "read_file", read)
                changed[0] = change == "before_read"
                value = io.get(snapshot["files"]["B.bin"])
                assert value == b"B"
                assert events == ["credentials", "read", "credentials"]
        if change == "before_read":
            assert events == ["credentials"]
        elif change == "during_read":
            assert events == ["credentials", "read", "credentials"]


@pytest.mark.parametrize("kind", ["head", "disabled", "custom_parent"])
def test_unpooled_or_custom_parent_keeps_the_original_outer_credential_guard(prepared, monkeypatch, kind):
    store, snapshot = prepared
    original_credentials = resources._credentials
    changed, callbacks = [False], []

    def credentials():
        uid, euid, gid, egid, groups = original_credentials()
        return uid, euid, gid, egid, groups + ((-1,) if changed[0] else ())

    class CustomParent(resources.DirectoryReads):
        def parent(self, name):
            callbacks.append(name)
            changed[0] = False
            return super().parent(name)

    with StoreIO(store.root, {}).locked() as io:
        with pytest.raises(ProjectStoreError, match="boundary"):
            with resources.reading_directories(io, STORE):
                owner = io._read_directories
                if kind == "disabled":
                    owner.disable()
                elif kind == "custom_parent":
                    owner.__class__ = CustomParent
                monkeypatch.setattr(resources, "_credentials", credentials)
                changed[0] = True
                if kind == "head":
                    io.read("head.json")
                else:
                    io.get(snapshot["files"]["A.bin"])
        assert callbacks == []


def test_one_head_reuses_only_structural_parents_and_keeps_every_actual_read(tmp_path, monkeypatch):
    from test_project_store_read_windows import publish

    root = tmp_path / "project"
    root.mkdir()
    for index in range(48):
        (root / f"{index:03d}.bin").write_bytes(f"original-{index}".encode())
    (root / "source.csv").write_bytes(b"1,2\n")
    store = FileProjectStore(root)
    store.snapshot(import_legacy=True)
    for revision in range(5):
        publish(store, {f"{revision:03d}.bin": f"revision-{revision}".encode()})
    snapshot = store.snapshot()
    counters = {}
    original_open, original_read, original_get = os.open, StoreIO._read_metadata, StoreIO.get
    @contextmanager
    def no_resources(io, name):
        yield
    for enabled in (False, True):
        opens, reads, gets = Counter(), Counter(), Counter()
        observations = []
        original_resolve = Path.resolve
        def resolve(path, *args, _calls=observations, _resolve=original_resolve, **kwargs):
            _calls.append((sys._getframe(1).f_code, path))
            return _resolve(path, *args, **kwargs)
        def opened(path, flags, mode=0o777, *, dir_fd=None, _counts=opens):
            descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
            _counts[(str(path), bool(flags & os.O_DIRECTORY))] += 1
            return descriptor
        def read(io, name, _counts=reads):
            _counts[name] += 1
            return original_read(io, name)
        def get(io, entry, _counts=gets):
            _counts[entry["sha256"]] += 1
            return original_get(io, entry)
        with StoreIO(store.root, {}).locked() as io, monkeypatch.context() as patch:
            patch.setattr(os, "open", opened)
            patch.setattr(StoreIO, "_read_metadata", read)
            patch.setattr(StoreIO, "get", get)
            patch.setattr(Path, "resolve", resolve)
            if not enabled:
                patch.setattr(state, "reading_directories", no_resources)
            proof = state.checked_head(io)
            assert proof.current["generation"] == snapshot["generation"]
            assert io._read_directories is None
            proof.require(io, proof.current)
            proof.close()
            os.fstat(io.fd)  # Pool teardown did not close the lease/store FD.
        # The guard independently resolves live FDs and final children. Count
        # the Store's ancestor scan by its caller, retaining every observation.
        resolutions = [path for owner, path in observations if owner is resources.DirectoryReads._anchors.__code__]
        assert resolutions == ([store.root] if enabled else [])
        from sciplot_core.verification import private_access, public_input_guard
        if public_input_guard._installed is not None:
            owners = {owner for owner, _path in observations}
            assert private_access._fd_path.__code__ in owners
            assert private_access.ResolvedAccess.resolved_path.__code__ in owners
        counters[enabled] = opens, reads, gets
    before, after = counters[False], counters[True]
    assert before[1:] == after[1:]
    assert before[1]["head.json"] == 1
    assert sum(n for name, n in before[1].items() if name.startswith("generations/")) == 6
    assert sum(n for (name, isdir), n in before[0].items() if not isdir) == sum(
        n for (name, isdir), n in after[0].items() if not isdir)
    assert sum(before[2].values()) == 50
    assert sum(n for (_name, isdir), n in before[0].items() if not isdir) == 57
    prefixes_before = {item: count for item, count in before[0].items()
                       if item[1] and item[0] not in {"objects", "generations"}}
    prefixes_after = {item: count for item, count in after[0].items()
                      if item[1] and item[0] not in {"objects", "generations"}}
    assert prefixes_before == prefixes_after and sum(prefixes_before.values()) == 50
    supported = all(os.access in support for support in (
        os.supports_dir_fd, os.supports_effective_ids, os.supports_follow_symlinks))
    if supported:
        assert after[0][("objects", True)] == after[0][("generations", True)] == 1
        assert before[0][("generations", True)] == 6
        assert sum(before[0].values()) == 163 and sum(after[0].values()) == 109
    else:
        assert before[0] == after[0]


def test_store_canonical_scan_count_keeps_independent_live_fd_and_path_observations(prepared, monkeypatch):
    from sciplot_core.verification.private_access import ResolvedAccess, _fd_path

    store, snapshot = prepared
    observations = []
    original_resolve = Path.resolve
    def resolve(path, *args, **kwargs):
        observations.append((sys._getframe(1).f_code, path))
        return original_resolve(path, *args, **kwargs)
    with StoreIO(store.root, {}).locked() as io, resources.reading_directories(io, STORE):
        with monkeypatch.context() as patch:
            patch.setattr(Path, "resolve", resolve)
            assert _fd_path(io.root_fds[""]).path == store.root
            assert ResolvedAccess(store.root / "A.bin").within((store.root,))
            assert io.get(snapshot["files"]["A.bin"]) == b"A"
        assert [path for owner, path in observations if owner is resources.DirectoryReads._anchors.__code__] == [store.root]
        assert (_fd_path.__code__, store.root) in observations
        owners = {owner for owner, _path in observations}
        assert _fd_path.__code__ in owners
        assert ResolvedAccess.resolved_path.__code__ in owners
        assert len(observations) >= 3


@pytest.mark.parametrize("reason", ["false", "unsupported", "unavailable_metadata", "unavailable_name", "unsupported_name", "relative_name", "deleted_name"])
def test_unprovable_reuse_closes_resources_and_keeps_the_original_fresh_result(prepared, monkeypatch, reason):
    store, snapshot = prepared
    with StoreIO(store.root, {}).locked() as io:
        with resources.reading_directories(io, STORE):
            assert io.get(snapshot["files"]["A.bin"]) == b"A"
            owner = io._read_directories
            descriptors = held(owner)
            with monkeypatch.context() as patch:
                if reason == "false":
                    patch.setattr(resources, "_permission", lambda _fd, _name: False)
                elif reason == "unsupported":
                    def unsupported(_fd, _name):
                        raise NotImplementedError("No effective no-follow access probe")
                    patch.setattr(resources, "_permission", unsupported)
                elif reason == "unavailable_metadata":
                    original = os.stat
                    def invisible(path, *, dir_fd=None, follow_symlinks=True):
                        if path == "objects" and dir_fd == io.fd:
                            raise PermissionError(errno.EPERM, "metadata is not observable")
                        return original(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
                    patch.setattr(os, "stat", invisible)
                elif reason in {"unavailable_name", "unsupported_name"}:
                    def missing_name(_descriptor):
                        if reason == "unavailable_name":
                            raise PermissionError(errno.EPERM, "kernel name is not observable")
                        raise NotImplementedError("No supported kernel name observation")
                    patch.setattr(resources, "descriptor_name", missing_name)
                else:
                    patch.setattr(resources, "descriptor_name", lambda _descriptor: "relative" if reason == "relative_name" else str(store.root) + " (deleted)")
                assert io.get(snapshot["files"]["B.bin"]) == b"B"
            assert not owner.reusable and owner.held == {}
            closed(descriptors)
            assert io.get(snapshot["files"]["A.bin"]) == b"A"
        assert io._read_directories is None


def test_platform_without_effective_access_uses_original_directory_reads(prepared, monkeypatch):
    store, snapshot = prepared
    monkeypatch.setattr(os, "supports_effective_ids", set())
    with StoreIO(store.root, {}).locked() as io:
        with resources.reading_directories(io, STORE):
            assert io.get(snapshot["files"]["A.bin"]) == b"A"
            assert io.get(snapshot["files"]["B.bin"]) == b"B"
            assert not io._read_directories.reusable and io._read_directories.held == {}


def test_valid_root_case_spelling_keeps_the_original_fresh_read_result(prepared, monkeypatch):
    store, snapshot = prepared
    spelling = store.root.with_name(store.root.name.upper())
    with monkeypatch.context() as patch:
        if not spelling.exists():
            spelling = store.root
            # On a case-sensitive host, model only the kernel observation's
            # spelling difference. Names, identities, permissions and reads
            # remain actual filesystem operations.
            observe = resources.descriptor_name
            patch.setattr(resources, "descriptor_name", lambda descriptor: observe(descriptor).upper())
        assert spelling.resolve(strict=True) == spelling
        with StoreIO(spelling, {}).locked() as io, resources.reading_directories(io, STORE):
            assert io.get(snapshot["files"]["A.bin"]) == b"A"
            assert io.get(snapshot["files"]["B.bin"]) == b"B"
            assert io._read_directories.root_name == resources.descriptor_name(io.root_fds[""])
            assert io._read_directories.root_name != str(io.root)


def test_a_valid_case_only_ancestor_move_keeps_the_original_no_alias_rule(tmp_path, monkeypatch):
    parent = tmp_path / "lower-parent"
    moved = parent.with_name("LOWER-PARENT")
    root = parent / "project"
    root.mkdir(parents=True)
    (root / "A.bin").write_bytes(b"A")
    (root / "B.bin").write_bytes(b"B")
    store = FileProjectStore(root)
    snapshot = store.snapshot(import_legacy=True)
    with StoreIO(store.root, {}).locked() as io:
        with resources.reading_directories(io, STORE):
            assert io.get(snapshot["files"]["A.bin"]) == b"A"
            parent.rename(moved)
            try:
                with monkeypatch.context() as patch:
                    if not parent.exists():
                        moved.rename(parent)
                        # Isolate the same changed kernel spelling on a
                        # case-sensitive filesystem without bypassing any of
                        # the original resolve/stat/access/read checks.
                        observe = resources.descriptor_name
                        patch.setattr(resources, "descriptor_name", lambda descriptor: observe(descriptor).replace("lower-parent", "LOWER-PARENT"))
                    assert resources.descriptor_name(io.root_fds[""]) != io._read_directories.root_name
                    assert store.root.resolve(strict=True) == store.root
                    assert io.get(snapshot["files"]["B.bin"]) == b"B"
            finally:
                if moved.exists():
                    moved.rename(parent)


@pytest.mark.parametrize("failure", ["missing_prefix", "aliased_prefix", "aliased_leaf", "changed_bytes"])
def test_reused_structural_parents_reopen_and_verify_the_actual_prefix_and_leaf(prepared, failure):
    store, snapshot = prepared
    entry = snapshot["files"]["B.bin"]
    objects = store.root / STORE / "objects"
    prefix = objects / entry["sha256"][:2]
    leaf = prefix / entry["sha256"]
    saved = prefix.with_name(prefix.name + "-saved")
    with StoreIO(store.root, {}).locked() as io:
        with pytest.raises(ProjectStoreError, match="boundary"):
            with resources.reading_directories(io, STORE):
                assert io.get(snapshot["files"]["A.bin"]) == b"A"
                owner = io._read_directories
                descriptors = held(owner)
                if failure in {"missing_prefix", "aliased_prefix"}:
                    prefix.rename(saved)
                    if failure == "aliased_prefix":
                        prefix.symlink_to(saved, target_is_directory=True)
                elif failure == "aliased_leaf":
                    leaf.unlink()
                    leaf.symlink_to(store.root / "B.bin")
                else:
                    before = leaf.stat()
                    leaf.write_bytes(b"X")
                    os.utime(leaf, ns=(before.st_atime_ns, before.st_mtime_ns))
                try:
                    with pytest.raises((OSError, ProjectStoreError)):
                        io.get(entry)
                    assert owner.failed and owner.held == {}
                    closed(descriptors)
                finally:
                    if failure in {"missing_prefix", "aliased_prefix"}:
                        if prefix.is_symlink():
                            prefix.unlink()
                        saved.rename(prefix)
                    elif failure == "aliased_leaf":
                        leaf.unlink()
                        leaf.write_bytes(b"B")
                    else:
                        leaf.write_bytes(b"B")
        os.fstat(io.fd)


def test_resources_from_another_io_cannot_authorize_a_read(prepared):
    store, snapshot = prepared
    with StoreIO(store.root, {}).locked() as io:
        with pytest.raises(ProjectStoreError, match="boundary"):
            with resources.reading_directories(io, STORE):
                assert io.get(snapshot["files"]["A.bin"]) == b"A"
                owner = io._read_directories
                descriptors = held(owner)
                foreign = StoreIO(store.root, {})
                foreign._read_directories = owner
                with pytest.raises(ProjectStoreError, match="another IO"):
                    foreign.get(snapshot["files"]["B.bin"])
                assert owner.failed and owner.held == {}
                closed(descriptors)
        os.fstat(io.fd)


def test_metadata_becomes_unobservable_after_read_replays_the_actual_fresh_read(prepared, monkeypatch):
    store, snapshot = prepared
    original_reader, original_stat = store_io.read_file, os.stat
    key = snapshot["files"]["B.bin"]["sha256"]
    calls = []
    invisible = False
    def read_file(fd, name, *, owned=False):
        nonlocal invisible
        value = original_reader(fd, name, owned=owned)
        if name == key:
            calls.append(name)
            invisible = True
        return value
    def named_stat(path, *, dir_fd=None, follow_symlinks=True):
        if path == "objects" and invisible:
            raise PermissionError(errno.EPERM, "metadata is not observable")
        return original_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
    with StoreIO(store.root, {}).locked() as io, resources.reading_directories(io, STORE):
        assert io.get(snapshot["files"]["A.bin"]) == b"A"
        monkeypatch.setattr(store_io, "read_file", read_file)
        monkeypatch.setattr(os, "stat", named_stat)
        assert io.get(snapshot["files"]["B.bin"]) == b"B"
        assert len(calls) == 2 and io._read_directories.held == {}


def test_removing_directory_read_permission_uses_the_fresh_open_errno(prepared):
    store, snapshot = prepared
    objects = store.root / STORE / "objects"
    mode = objects.stat().st_mode & 0o777
    with StoreIO(store.root, {}).locked() as io:
        try:
            with pytest.raises((PermissionError, ProjectStoreError)):
                with resources.reading_directories(io, STORE):
                    assert io.get(snapshot["files"]["A.bin"]) == b"A"
                    owner = io._read_directories
                    descriptors = held(owner)
                    objects.chmod(0o111)
                    try:
                        with directory(io.fd, ("objects",)):
                            pass
                    except PermissionError as original:
                        with pytest.raises(PermissionError) as error:
                            io.get(snapshot["files"]["B.bin"])
                        assert error.value.errno == original.errno
                    else:
                        with pytest.raises(ProjectStoreError, match="changed"):
                            io.get(snapshot["files"]["B.bin"])
                    closed(descriptors)
                    # A caught refusal cannot restore the invalid pool.
                    raise ProjectStoreError("observed original permission refusal")
        finally:
            objects.chmod(mode)


@pytest.mark.parametrize("change", ["replace", "alias", "mode", "ctime"])
def test_a_cached_parent_cannot_survive_named_directory_drift(prepared, change):
    store, snapshot = prepared
    objects = store.root / STORE / "objects"
    saved = objects.with_name("old-objects")
    with StoreIO(store.root, {}).locked() as io:
        try:
            with pytest.raises((OSError, ProjectStoreError)):
                with resources.reading_directories(io, STORE):
                    assert io.get(snapshot["files"]["A.bin"]) == b"A"
                    owner = io._read_directories
                    descriptors = held(owner)
                    if change in {"replace", "alias"}:
                        objects.rename(saved)
                        if change == "replace":
                            shutil.copytree(saved, objects)
                        else:
                            objects.symlink_to(saved, target_is_directory=True)
                    elif change == "mode":
                        objects.chmod(0o755)
                    else:
                        before = objects.stat()
                        os.utime(objects, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
                    io.get(snapshot["files"]["B.bin"])
        finally:
            closed(descriptors)
            if change in {"replace", "alias"}:
                if objects.is_symlink():
                    objects.unlink()
                else:
                    shutil.rmtree(objects)
                saved.rename(objects)
            else:
                objects.chmod(0o700)
        assert io.get(snapshot["files"]["A.bin"]) == b"A"


def test_an_ancestor_alias_cannot_keep_the_cached_namespace_live(prepared):
    store, snapshot = prepared
    parent = store.root.parent
    moved = parent.with_name(parent.name + "-moved")
    with StoreIO(store.root, {}).locked() as io:
        try:
            with pytest.raises(ProjectStoreError, match="alias"):
                with resources.reading_directories(io, STORE):
                    assert io.get(snapshot["files"]["A.bin"]) == b"A"
                    descriptors = held(io._read_directories)
                    parent.rename(moved)
                    parent.symlink_to(moved, target_is_directory=True)
                    io.get(snapshot["files"]["B.bin"])
        finally:
            parent.unlink()
            moved.rename(parent)
            closed(descriptors)


@pytest.mark.parametrize("boundary", ["write", "existing_put", "fence", "backups", "members", "roots", "locations", "epoch", "lease"])
def test_mutation_fence_and_capability_boundaries_immediately_end_directory_resources(prepared, boundary):
    store, snapshot = prepared
    with StoreIO(store.root, {}).locked() as io:
        with pytest.raises(ProjectStoreError, match="boundary"):
            with resources.reading_directories(io, STORE):
                assert io.get(snapshot["files"]["A.bin"]) == b"A"
                owner = io._read_directories
                descriptors = held(owner)
                if boundary == "write":
                    io.write("diagnostic.json", {"generated": True})
                elif boundary == "existing_put":
                    io.put(b"A")
                elif boundary == "fence":
                    with io.validation_fence():
                        assert owner.failed and owner.held == {}
                elif boundary == "backups":
                    io.namespace_backups["changed"] = store.root
                elif boundary == "members":
                    io.location_members["changed"] = ("A.bin",)
                elif boundary == "roots":
                    io.root_fds["changed"] = io.fd
                elif boundary == "locations":
                    io.locations["changed"] = store.root
                elif boundary == "epoch":
                    io.validation_epoch += 1
                else:
                    io.lease_epoch += 1
                if boundary in {"write", "existing_put", "fence"}:
                    assert owner.failed and owner.held == {}
                    closed(descriptors)
                io.get(snapshot["files"]["B.bin"])
        closed(descriptors)
        io.namespace_backups.pop("changed", None)
        io.location_members.pop("changed", None)
        io.root_fds.pop("changed", None)
        io.locations.pop("changed", None)


@pytest.mark.parametrize("owner", ["thread", "process"])
def test_directory_resources_are_private_to_their_process_and_thread(prepared, monkeypatch, owner):
    store, snapshot = prepared
    with StoreIO(store.root, {}).locked() as io:
        with pytest.raises(ProjectStoreError, match="boundary"):
            with resources.reading_directories(io, STORE):
                io.get(snapshot["files"]["A.bin"])
                descriptors = held(io._read_directories)
                if owner == "thread":
                    with ThreadPoolExecutor(max_workers=1) as worker:
                        worker.submit(io.get, snapshot["files"]["B.bin"]).result()
                else:
                    process = os.getpid()
                    with monkeypatch.context() as patch:
                        patch.setattr(resources.os, "getpid", lambda: process + 1)
                        io.get(snapshot["files"]["B.bin"])
        closed(descriptors)


def test_scope_exit_and_caught_blob_failure_close_only_resource_descriptors(prepared):
    from test_project_store_read_windows import corrupt_object

    store, snapshot = prepared
    with StoreIO(store.root, {}).locked() as io:
        with resources.reading_directories(io, STORE):
            io.get(snapshot["files"]["A.bin"])
            owner = io._read_directories
            descriptors = held(owner)
        closed(descriptors)
        assert owner.failed
        assert io._read_directories is None
        with pytest.raises(ProjectStoreError, match="boundary"):
            owner.parent("objects")
        os.fstat(io.fd)
        with pytest.raises(ProjectStoreError, match="boundary"):
            with resources.reading_directories(io, STORE):
                io.get(snapshot["files"]["A.bin"])
                owner = io._read_directories
                descriptors = held(owner)
                corrupt_object(store, snapshot["files"]["B.bin"])
                with pytest.raises(ProjectStoreError, match="identity"):
                    io.get(snapshot["files"]["B.bin"])
                assert owner.failed and owner.held == {}
                closed(descriptors)
        os.fstat(io.fd)


def test_reacquiring_the_same_io_cannot_reuse_an_escaped_resource_scope(prepared):
    store, snapshot = prepared
    io = StoreIO(store.root, {})
    with io.locked():
        scope = resources.reading_directories(io, STORE)
        scope.__enter__()
        io.get(snapshot["files"]["A.bin"])
        descriptors = held(io._read_directories)
    closed(descriptors)
    try:
        with io.locked(), pytest.raises(ProjectStoreError, match="boundary"):
            io.get(snapshot["files"]["B.bin"])
    finally:
        with pytest.raises(ProjectStoreError, match="boundary"):
            scope.__exit__(None, None, None)
    assert io._read_directories is None


def test_a_full_head_proof_does_not_keep_any_directory_resource_alive(prepared, monkeypatch):
    store, snapshot = prepared
    seen = []
    original = resources.DirectoryReads.parent
    def parent(pool, name):
        descriptor = original(pool, name)
        seen.append(descriptor)
        return descriptor
    monkeypatch.setattr(resources.DirectoryReads, "parent", parent)
    with StoreIO(store.root, {}).locked() as io:
        proof = state.checked_head(io)
        assert proof.current["generation"] == snapshot["generation"]
        assert io._read_directories is None
        closed(set(seen))
        proof.require(io, proof.current)
        assert not any(isinstance(value, resources.DirectoryReads) for value in vars(proof).values())
        proof.close()


def test_failure_during_a_nested_read_closes_each_pool_without_owning_the_lease(prepared):
    store, snapshot = prepared
    with StoreIO(store.root, {}).locked() as io:
        with pytest.raises(ProjectStoreError, match="boundary"):
            with resources.reading_directories(io, STORE):
                io.get(snapshot["files"]["A.bin"])
                outer = held(io._read_directories)
                with pytest.raises(RuntimeError, match="nested actual failure"):
                    with resources.reading_directories(io, STORE):
                        io.get(snapshot["files"]["B.bin"])
                        inner = held(io._read_directories)
                        raise RuntimeError("nested actual failure")
                closed(inner)
                io.get(snapshot["files"]["A.bin"])
        closed(outer)
        os.fstat(io.fd)
