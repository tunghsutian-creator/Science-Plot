"""Only retired, explicitly produced source scaffolds belong to projection GC."""
import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest

from sciplot_core.project_commands import InputRead, PreparedFile, PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ProjectRecoveryRequired, ResourceRoot, state
from sciplot_core.project_store.io import sha

OLD = "other-products/old-group/table.csv"
NEW = "other-products/new-group/table.csv"
DATA = b"x,y\n1,7\n"


def initial(tmp_path, *, tagged=True, survivor=False):
    project = tmp_path / "project"
    project.mkdir()
    (project / "raw").mkdir()
    (project / "raw/original.csv").write_bytes(b"untouched measurements")
    (project / "user-empty").mkdir()
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    values = {OLD: PreparedFile(DATA, 0o640)}
    if survivor:
        values["other-products/old-group/keep.txt"] = PreparedFile(b"current output", 0o600)
    source = PreparedSource(uuid4().hex, str(project / OLD), sha(DATA), DATA, (), 0o640,
        produced_resource=OLD) if tagged else None
    command = ProjectCommand.create("figure_set", "first", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={name: None for name in values},
        write_set=list(values), request={})
    ProjectCommands(store).execute(command, lambda: ProjectMutation(values, {},
        prepared_sources=(source,) if source else ()))
    return store


def replacement(store):
    before = store.snapshot()
    command = ProjectCommand.create("figure_set", "replace", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={OLD: before["files"][OLD]["sha256"], NEW: None},
        write_set=[OLD, NEW], request={})
    source = PreparedSource("e" * 32, str(store.root / NEW), sha(DATA), DATA, (), 0o640, produced_resource=NEW)
    return command, ProjectMutation({OLD: None, NEW: PreparedFile(DATA, 0o640)}, {}, prepared_sources=(source,))


def test_retired_produced_group_is_removed_but_unknown_empty_directory_is_preserved(tmp_path):
    store = initial(tmp_path)
    command, mutation = replacement(store)
    receipt = ProjectCommands(store).execute(command, lambda: mutation)
    assert receipt["phase"] == "complete"
    assert not (store.root / OLD).parent.exists()
    assert (store.root / NEW).read_bytes() == DATA
    assert (store.root / "user-empty").is_dir()
    assert (store.root / "raw/original.csv").read_bytes() == b"untouched measurements"
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    assert not (cold.root / OLD).parent.exists() and cold.read_bytes(NEW) == DATA
    assert cold.recover()["phase"] == "complete"


def test_finite_file_capability_does_not_grant_parent_directory_retirement(tmp_path):
    project, external = tmp_path / "project", tmp_path / "external"
    project.mkdir()
    (external / "nested").mkdir(parents=True)
    private = external / "nested/private.txt"
    private.write_bytes(b"outside the exact file capability")
    store = FileProjectStore(project, locations={"selected": ResourceRoot(external, ("nested/table.csv",))})
    before = store.snapshot(import_legacy=True)
    name = "@selected/nested/table.csv"
    source = PreparedSource("f" * 32, str(external / "nested/table.csv"), sha(DATA), DATA, (), 0o640, produced_resource=name)
    command = ProjectCommand.create("figure_set", "produce-exact-file", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={name: None}, write_set=[name], request={})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({name: PreparedFile(DATA, 0o640)}, {}, prepared_sources=(source,)))
    before = store.snapshot()
    command = ProjectCommand.create("figure_set", "retire-exact-file", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={name: sha(DATA)}, write_set=[name], request={})
    assert ProjectCommands(store).execute(command, lambda: ProjectMutation({name: None}, {}))["phase"] == "complete"
    assert not (external / "nested/table.csv").exists()
    assert private.read_bytes() == b"outside the exact file capability"
    assert private.parent.is_dir() and external.is_dir()


@pytest.mark.parametrize("foreign", [False, True], ids=["nested-scaffold", "nested-foreign-member"])
def test_nested_output_scaffolds_do_not_turn_a_legal_deletion_into_recursive_cleanup(tmp_path, foreign):
    store = initial(tmp_path)
    nested = "other-products/old-group/sub/deep/table.csv"
    before = store.snapshot()
    source = PreparedSource("c" * 32, str(store.root / nested), sha(DATA), DATA, (), 0o640, produced_resource=nested)
    command = ProjectCommand.create("figure_set", "nested", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={nested: None}, write_set=[nested], request={})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({nested: PreparedFile(DATA, 0o640)}, {}, prepared_sources=(source,)))
    note = store.root / "other-products/old-group/sub/foreign.txt"
    if foreign:
        note.write_bytes(b"not a tracked output")
        identity = note.stat()
    command, mutation = replacement(store)
    reads = dict(command.read_set)
    reads[nested] = sha(DATA)
    command = ProjectCommand.create("figure_set", "retire-nested", project_id=command.project_id,
        expected_generation=command.expected_generation, read_set=reads, write_set=[*command.write_set, nested], request={})
    mutation = ProjectMutation({**mutation.writes, nested: None}, {}, prepared_sources=mutation.prepared_sources)
    assert ProjectCommands(store).execute(command, lambda: mutation)["phase"] == "complete"
    assert not (store.root / OLD).exists() and not (store.root / nested).parent.exists()
    # No directory authority is inferred for the intermediate scaffold or the
    # outer parent containing nested descendants in the old generation.
    assert (store.root / "other-products/old-group/sub").is_dir()
    if foreign:
        assert note.read_bytes() == b"not a tracked output"
        current = note.stat()
        assert (current.st_dev, current.st_ino, current.st_mode, current.st_size, current.st_mtime_ns) == (
            identity.st_dev, identity.st_ino, identity.st_mode, identity.st_size, identity.st_mtime_ns)


def test_directory_projection_rechecks_its_same_io_head_proof_after_the_fault_boundary(tmp_path, monkeypatch):
    from sciplot_core.project_store.io import owned_io

    store = initial(tmp_path)
    command, mutation = replacement(store)
    changed = []

    def reenter(name):
        if name == "before_directory_projection" and not changed:
            changed.append(name)
            current = owned_io(store.root)
            assert current is not None
            current.write("test-observed-metadata.json", {"changed_epoch": True})

    monkeypatch.setattr(state, "boundary", reenter)
    with pytest.raises(ProjectConflict, match="checked history"):
        ProjectCommands(store).execute(command, lambda: mutation)
    assert changed and (store.root / OLD).parent.is_dir()
    assert store.query(command.key)["phase"] != "complete"
    monkeypatch.setattr(state, "boundary", lambda _name: None)
    assert store.recover()["phase"] == "complete"
    assert not (store.root / OLD).parent.exists()


@pytest.mark.parametrize("kind", ["current-member", "no-derived-role", "observed-original"])
def test_projection_does_not_retire_a_directory_without_exact_role_and_retirement_proof(tmp_path, kind):
    store = initial(tmp_path, tagged=kind != "no-derived-role", survivor=kind == "current-member")
    if kind == "observed-original":
        before = store.snapshot()
        item = before["files"][OLD]
        source = PreparedSource("d" * 32, str(store.root / OLD), item["sha256"], DATA, (), item["mode"])
        command = ProjectCommand.create("figure_set", "observe-original", project_id=before["project_id"],
            expected_generation=before["generation"], read_set={OLD: item["sha256"]}, write_set=[], request={},
            input_reads=[InputRead(OLD, source.source_id, source.version)])
        ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}, prepared_sources=(source,)))
    command, mutation = replacement(store)
    if kind == "observed-original":
        with pytest.raises(ProjectConflict, match="original input"):
            ProjectCommands(store).execute(command, lambda: mutation)
        assert (store.root / OLD).read_bytes() == DATA
    else:
        assert ProjectCommands(store).execute(command, lambda: mutation)["phase"] == "complete"
        assert not (store.root / OLD).exists()
    assert (store.root / OLD).parent.is_dir()
    if kind == "current-member":
        assert (store.root / "other-products/old-group/keep.txt").read_bytes() == b"current output"


@pytest.mark.parametrize("change", ["foreign-file", "foreign-empty-directory", "symlink", "replacement"])
def test_retired_parent_foreign_or_replaced_namespace_is_not_removed_and_recovery_is_explicit(tmp_path, monkeypatch, change):
    store = initial(tmp_path)
    command, mutation = replacement(store)
    parent = (store.root / OLD).parent
    held = tmp_path / "held-derived-parent"
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "sentinel").write_bytes(b"never touch")
    invoked = []

    def interfere(name):
        if name != "before_directory_projection" or invoked:
            return
        invoked.append(name)
        if change == "foreign-file":
            (parent / "foreign.txt").write_bytes(b"outside data")
        elif change == "foreign-empty-directory":
            (parent / "user-empty").mkdir()
        else:
            parent.rename(held)
            if change == "symlink":
                parent.symlink_to(foreign, target_is_directory=True)
            else:
                parent.mkdir()
                assert parent.stat().st_ino != held.stat().st_ino

    monkeypatch.setattr(state, "boundary", interfere)
    with pytest.raises(ProjectRecoveryRequired):
        ProjectCommands(store).execute(command, lambda: mutation)
    assert invoked and (foreign / "sentinel").read_bytes() == b"never touch"
    assert store.query(command.key)["phase"] != "complete"
    assert (store.root / "raw/original.csv").read_bytes() == b"untouched measurements"
    monkeypatch.setattr(state, "boundary", lambda _name: None)
    if change == "foreign-file":
        (parent / "foreign.txt").unlink()
    elif change == "foreign-empty-directory":
        (parent / "user-empty").rmdir()
    else:
        parent.unlink() if parent.is_symlink() else parent.rmdir()
        held.rename(parent)
    # Only this fixture's explicit interference is removed. Same frozen bytes
    # finish without preparing or executing the scientific command again.
    assert store.recover()["phase"] == "complete"
    assert not parent.exists() and (store.root / NEW).read_bytes() == DATA
    assert store.recover()["phase"] == "complete"


@pytest.mark.comprehensive
@pytest.mark.parametrize("point", ["before_directory_projection", "after_directory_projection"])
def test_hard_exit_during_retired_parent_projection_resumes_the_same_generation_without_callback(tmp_path, point):
    store = initial(tmp_path)
    script = """import json,os,sys
from pathlib import Path
from sciplot_core.project_store import FileProjectStore,state
from sciplot_core.project_commands import ProjectCommands
from test_project_derived_directories import replacement
store=FileProjectStore(Path(sys.argv[1]))
command,mutation=replacement(store)
def fault(name):
    if name==sys.argv[2]:
        print(json.dumps({'pid':os.getpid(),'parent_pid':os.getppid(),'point':name}),flush=True)
        os._exit(73)
state.boundary=fault
ProjectCommands(store).execute(command,lambda:mutation)
"""
    child = subprocess.run([sys.executable, "-c", script, str(store.root), point], capture_output=True, text=True, timeout=30)
    assert child.returncode == 73, child.stdout + child.stderr
    observed = json.loads(child.stdout)
    assert observed["pid"] > 0 and observed["parent_pid"] == os.getpid() and observed["point"] == point
    (tmp_path / "child-original-wait.json").write_text(json.dumps({**observed,
        "returncode": child.returncode, "stderr": child.stderr, "actual_wait_returned": True}))
    receipt = store.query("replace")
    generation = receipt["committed_generation"] if "committed_generation" in receipt else receipt["generation"]
    assert receipt["phase"] != "complete"
    assert store.recover()["phase"] == "complete"
    assert store.snapshot()["generation"] == generation
    assert store.query("replace")["phase"] == "complete"
    assert not (store.root / OLD).parent.exists() and store.read_bytes(NEW) == DATA
    assert (store.root / "raw/original.csv").read_bytes() == b"untouched measurements"
    assert store.recover()["phase"] == "complete"
