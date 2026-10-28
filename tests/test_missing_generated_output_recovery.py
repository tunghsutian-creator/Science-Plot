"""Hard exits and later authorities cannot revive an older derived install plan."""
import json
import subprocess
import sys
from uuid import uuid4

import pytest

from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_commands import PreparedSource, InputRead, NativeAdoption
from sciplot_core.project_store import ProjectConflict, ProjectStoreError
from sciplot_core.project_store.generated_outputs import discover
from sciplot_core.project_store import state

from test_missing_generated_outputs import generated as generated, candidate, command_for, sha


@pytest.mark.comprehensive
@pytest.mark.parametrize("boundary", ["before_head", "after_head", "after_projection"])
def test_real_owned_process_exit_recovers_only_saved_fresh_output(generated, tmp_path, boundary):
    store, _original, _missing = generated
    command = command_for(generated)
    effect = tmp_path / "one-private-render.txt"
    script = '''
import json,os,sys
from pathlib import Path
from sciplot_core.project_commands import ProjectCommand,ProjectCommands,ProjectMutation
from sciplot_core.project_store import FileProjectStore,state
root,metadata,boundary,effect=sys.argv[1:]
command=ProjectCommand.from_payload(json.loads(metadata))
def stop(name):
    if name==boundary:os._exit(73)
state.boundary=stop
def produce():
    Path(effect).write_text("one new private render")
    return ProjectMutation({"figure.pdf":b"fresh native export"},{"status":"fresh"})
ProjectCommands(FileProjectStore(Path(root))).execute(command,produce)
'''
    child = subprocess.run([sys.executable, "-c", script, str(store.root), json.dumps(command.to_payload()),
                            boundary, str(effect)], capture_output=True, text=True, timeout=30)
    assert child.returncode == 73, child.stdout + child.stderr
    assert effect.read_text() == "one new private render"
    record = ProjectCommands(store).resume(command)
    assert record["phase"] == "complete" and (store.root / "figure.pdf").read_bytes() == b"fresh native export"
    assert effect.read_text() == "one new private render"


@pytest.mark.parametrize("immutable", [False, True], ids=["source-version", "input-read"])
def test_even_an_export_receipt_cannot_rebuild_a_registered_source_or_immutable_input(generated, immutable):
    store, _original, _missing = generated
    output = store.root / "figure.pdf"
    output.write_bytes(b"old PDF")
    output.chmod(generated[2].mode)
    before = store.snapshot()
    identity = uuid4().hex
    source = PreparedSource(identity, str(output), sha(b"old PDF"), b"old PDF")
    captured = InputRead("figure.pdf", identity, source.version)
    command = ProjectCommand.create("semantic_record", "bind-input", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"figure.pdf": source.version, "observation.json": None},
        write_set=["observation.json"], request={"explicit_input": True}, input_reads=[captured] if immutable else [])
    ProjectCommands(store).execute(command, lambda: ProjectMutation({"observation.json": b"{}"}, {}, prepared_sources=(source,)))
    output.unlink()
    with pytest.raises(ProjectConflict, match="input/source/history"):
        discover(store, ["figure.pdf"])


def test_later_foreign_registered_writer_removes_older_export_ownership(generated):
    store, _original, _missing = generated
    (store.root / "figure.pdf").write_bytes(b"old PDF")
    (store.root / "figure.pdf").chmod(generated[2].mode)
    before = store.snapshot()
    foreign = ProjectCommand.create("save", "another-owner", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"figure.pdf": sha(b"old PDF")},
        write_set=["figure.pdf"], request={"foreign_writer": True})
    ProjectCommands(store).execute(foreign, lambda: ProjectMutation({"figure.pdf": b"old PDF"}, {}))
    (store.root / "figure.pdf").unlink()
    with pytest.raises(ProjectConflict):
        discover(store, ["figure.pdf"])


def test_replaced_parent_blocks_publication_and_preserves_replacement(generated, monkeypatch):
    store, _original, _missing = generated
    command = command_for(generated)
    actual = state.boundary
    backup = store.root.with_name("original-project-preserved")

    def replace_parent(name):
        if name == "before_head":
            store.root.rename(backup)
            store.root.mkdir()
            (store.root / "figure.pdf").write_bytes(b"replacement parent foreign output")
        actual(name)

    monkeypatch.setattr(state, "boundary", replace_parent)
    with pytest.raises((ProjectStoreError, OSError)):
        ProjectCommands(store).execute(command, lambda: candidate(generated))
    assert (store.root / "figure.pdf").read_bytes() == b"replacement parent foreign output"
    assert (backup / "document.vsz").read_bytes() == b"original saved native authority"


def test_audited_native_adoption_and_missing_generated_output_publish_together(generated):
    store, _original, missing = generated
    before = store.snapshot()
    native = store.root / "document.vsz"
    native.write_bytes(b"audited exact manually saved native")
    command = ProjectCommand.create("native_import", "adopt-and-export", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"document.vsz": before["files"]["document.vsz"]["sha256"],
        "figure.pdf": missing.before_sha256}, write_set=["document.vsz", "figure.pdf"], request={"manual_save_export": True},
        native_adoptions=[NativeAdoption("document.vsz", before["files"]["document.vsz"]["sha256"],
            sha(native.read_bytes()), "a" * 64)], missing_outputs=[missing])
    result = ProjectCommands(store).execute(command, lambda: ProjectMutation(
        {"document.vsz": native, "figure.pdf": b"fresh native export"}, {"audited_native": sha(native.read_bytes())}))
    assert result["phase"] == "complete"
    assert native.read_bytes() == b"audited exact manually saved native"
    assert (store.root / "figure.pdf").read_bytes() == b"fresh native export"


def test_official_cold_project_uses_its_current_bound_output_owner(generated, tmp_path):
    store, _original, _missing = generated
    (store.root / "figure.pdf").write_bytes(b"old PDF")
    (store.root / "figure.pdf").chmod(generated[2].mode)
    bundle = store.export_bundle(tmp_path / "project.zip")
    cold = type(store).import_bundle(bundle, tmp_path / "cold")
    store.root.rename(tmp_path / "old-offline")
    (cold.root / "figure.pdf").unlink()
    missing, = discover(cold, ["figure.pdf"])
    current = cold.snapshot()
    command = ProjectCommand.create("native_export", "cold-fresh", project_id=current["project_id"],
        expected_generation=current["generation"], read_set={"figure.pdf": missing.before_sha256},
        write_set=["figure.pdf"], request={"cold_export": True}, missing_outputs=[missing])
    assert ProjectCommands(cold).execute(command, lambda: ProjectMutation({"figure.pdf": b"new cold export"}, {}))["phase"] == "complete"
    assert (cold.root / "figure.pdf").read_bytes() == b"new cold export"


@pytest.mark.parametrize("generated", ["exports/figure.pdf"], indirect=True)
def test_a_descendant_delete_never_needs_the_old_missing_outputs_parent(generated, monkeypatch):
    store, _original, missing = generated
    before = store.snapshot()
    command = ProjectCommand.create("native_export", "fresh-nested", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={missing.resource: missing.before_sha256},
        write_set=[missing.resource], request={"nested": True}, missing_outputs=[missing])
    actual = state.boundary

    def stop(name):
        if name == "after_head":
            raise OSError("saved accepted receipt")
        actual(name)

    monkeypatch.setattr(state, "boundary", stop)
    with pytest.raises(OSError, match="saved accepted"):
        ProjectCommands(store).execute(command, lambda: ProjectMutation({missing.resource: b"fresh output"}, {}))
    receipt_path = store.root / ".sciplot_store" / state.command_path(command.key)
    original_accepted = receipt_path.read_bytes()
    monkeypatch.setattr(state, "boundary", actual)
    ProjectCommands(store).resume(command)
    current = store.snapshot()
    deletion = ProjectCommand.create("save", "later-delete", project_id=current["project_id"],
        expected_generation=current["generation"], read_set={missing.resource: sha(b"fresh output")},
        write_set=[missing.resource], request={"delete_output": True})
    ProjectCommands(store).execute(deletion, lambda: ProjectMutation({missing.resource: None}, {}))
    (store.root / missing.resource).parent.rmdir()
    head = (store.root / ".sciplot_store/head.json").read_bytes()
    receipt_path.write_bytes(original_accepted)
    assert store.recover()["phase"] == "complete"
    assert not (store.root / missing.resource).parent.exists()
    assert (store.root / ".sciplot_store/head.json").read_bytes() == head
