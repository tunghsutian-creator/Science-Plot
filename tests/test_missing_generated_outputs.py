"""One logical old version, one authenticated absent physical output preimage."""
from dataclasses import replace
import hashlib
import json

import pytest

from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation, MembershipRead
from sciplot_core.project_commands import ProjectCommandUnknown
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store import ProjectRecoveryRequired
from sciplot_core.project_store.generated_outputs import discover
from sciplot_core.project_store import state


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def generated(tmp_path, request):
    root = tmp_path / "project"
    root.mkdir()
    native = root / "document.vsz"
    native.write_bytes(b"original saved native authority")
    name = getattr(request, "param", "figure.pdf")
    output = root / name
    output.parent.mkdir(parents=True, exist_ok=True)
    store = FileProjectStore(root)
    initial = store.snapshot(import_legacy=True)
    result = {"document": str(native), "document_sha256": sha(native.read_bytes()),
              "exports": [{"format": "pdf", "path": str(output), "sha256": sha(b"old PDF")}]}
    command = ProjectCommand.create("native_export", "first", project_id=initial["project_id"],
        expected_generation=initial["generation"], read_set={name: None,
        "document.vsz": initial["files"]["document.vsz"]["sha256"]}, write_set=[name],
        request={"document": "document.vsz", "formats": ["pdf"]})
    original = ProjectCommands(store).execute(command, lambda: ProjectMutation({name: b"old PDF"}, result))
    output.unlink()
    missing, = discover(store, [name])
    return store, original, missing


def command_for(generated, *, key="fresh", membership=False):
    store, _original, missing = generated
    before = store.snapshot()
    return ProjectCommand.create("native_export", key, project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"figure.pdf": missing.before_sha256,
        "document.vsz": before["files"]["document.vsz"]["sha256"]}, write_set=["figure.pdf"],
        request={"document": "document.vsz", "formats": ["pdf"], "absence": missing.to_payload()},
        missing_outputs=[missing], read_memberships=[MembershipRead.capture(before["files"])] if membership else [])


def candidate(generated):
    store, _original, _missing = generated
    return ProjectMutation({"figure.pdf": b"fresh native export"}, {"document": str(store.root / "document.vsz"),
        "exports": [{"format": "pdf", "path": str(store.root / "figure.pdf"), "sha256": sha(b"fresh native export")}]})


def test_optional_contract_keeps_old_payload_and_digest_and_requires_exact_declared_output(generated):
    command = command_for(generated)
    assert ProjectCommand.from_payload(command.to_payload()) == command
    old = replace(command, missing_outputs=())
    assert "missing_outputs" not in old.to_payload()
    assert ProjectCommand.from_payload(old.to_payload()).command_digest == old.command_digest != command.command_digest
    for change in ({"kind": "save"}, {"write_set": ()}, {"read_set": (("figure.pdf", None),)},
                   {"missing_outputs": (generated[2], generated[2])}):
        with pytest.raises(ValueError):
            replace(command, **change)
    with pytest.raises(ValueError):
        replace(command, missing_outputs=(), request_json=json.dumps({"idempotency_key": "wrong"}))
    with pytest.raises(ValueError):
        ProjectMutation({"figure.pdf": None}, {}).validate_for(command)


@pytest.mark.parametrize("membership", [False, True])
def test_fresh_output_keeps_old_logical_guard_and_never_reinstalls_completed_receipt(generated, membership):
    store, original, missing = generated
    command = command_for(generated, membership=membership)
    assert dict(command.read_set)["figure.pdf"] == missing.before_sha256
    before = store.snapshot()
    complete = ProjectCommands(store).execute(command, lambda: candidate(generated))
    assert complete["phase"] == "complete" and (store.root / "figure.pdf").read_bytes() == b"fresh native export"
    assert store.read_bytes("figure.pdf", generation=before["generation"]) == b"old PDF"
    assert store.query(original["command_id"])["result"] == original["result"]
    (store.root / "figure.pdf").unlink()
    assert ProjectCommands(store).resume(command)["phase"] == "complete"
    assert not (store.root / "figure.pdf").exists()


@pytest.mark.parametrize("fault", ["owner", "digest", "mode", "byte", "parent", "present", "alias", "permission"])
def test_forged_or_late_physical_preimages_reject_before_callback(generated, fault):
    store, _original, missing = generated
    command = command_for(generated)
    if fault == "owner":
        missing = replace(missing, owner_key="foreign")
    elif fault == "digest":
        missing = replace(missing, owner_digest="0" * 64)
    elif fault == "mode":
        missing = replace(missing, mode=0o644)
    elif fault == "byte":
        missing = replace(missing, before_sha256="0" * 64)
    elif fault == "parent":
        missing = replace(missing, parent_identity=(1, 2, 3, 4))
    elif fault == "alias":
        (store.root / "figure.pdf").symlink_to("document.vsz")
    else:
        (store.root / "figure.pdf").write_bytes(b"foreign output")
        if fault == "permission":
            (store.root / "figure.pdf").chmod(0o400)
    if fault == "byte":
        command = replace(command, read_set=tuple((name, missing.before_sha256 if name == "figure.pdf" else value)
                                                for name, value in command.read_set), missing_outputs=(missing,))
    else:
        command = replace(command, missing_outputs=(missing,))
    with pytest.raises((ProjectConflict, OSError)):
        ProjectCommands(store).execute(command, lambda: pytest.fail("Invalid absence ran a producer"))
    assert len(store.commands()) == 1


@pytest.mark.parametrize("boundary", ["before_head", "after_head", "before_projection", "after_projection"])
def test_saved_candidate_fault_boundaries_resume_without_reexecuting_producer(generated, monkeypatch, boundary):
    store, _original, _missing = generated
    command = command_for(generated)
    actual = state.boundary
    calls = []

    def fail(name):
        if name == boundary:
            raise OSError("controlled missing-output boundary")
        actual(name)

    def produce():
        calls.append("render")
        return candidate(generated)

    monkeypatch.setattr(state, "boundary", fail)
    with pytest.raises(OSError, match="controlled missing-output"):
        ProjectCommands(store).execute(command, produce)
    monkeypatch.setattr(state, "boundary", actual)
    assert ProjectCommands(store).resume(command)["phase"] == "complete"
    assert calls == ["render"] and (store.root / "figure.pdf").read_bytes() == b"fresh native export"


@pytest.mark.parametrize("boundary", ["before_head", "before_projection"])
def test_late_foreign_output_is_preserved_at_final_publication_and_install(generated, monkeypatch, boundary):
    store, _original, _missing = generated
    command = command_for(generated)
    actual = state.boundary

    def insert(name):
        if name == boundary:
            (store.root / "figure.pdf").write_bytes(b"late foreign output")
        actual(name)

    monkeypatch.setattr(state, "boundary", insert)
    with pytest.raises(ProjectConflict):
        ProjectCommands(store).execute(command, lambda: candidate(generated))
    assert (store.root / "figure.pdf").read_bytes() == b"late foreign output"


def test_committed_missing_output_does_not_accept_its_old_preimage_during_recovery(generated, monkeypatch):
    store, _original, missing = generated
    command = command_for(generated)
    actual = state.boundary

    def stop(name):
        if name == "after_head":
            raise OSError("head committed before physical install")
        actual(name)

    monkeypatch.setattr(state, "boundary", stop)
    with pytest.raises(OSError, match="head committed"):
        ProjectCommands(store).execute(command, lambda: candidate(generated))
    monkeypatch.setattr(state, "boundary", actual)
    (store.root / "figure.pdf").write_bytes(b"old PDF")
    (store.root / "figure.pdf").chmod(missing.mode)
    with pytest.raises(ProjectRecoveryRequired, match="Outside bytes prevent generation recovery"):
        ProjectCommands(store).resume(command)
    assert (store.root / "figure.pdf").read_bytes() == b"old PDF"


@pytest.mark.parametrize("generated", ["exports/figure.pdf"], indirect=True)
@pytest.mark.parametrize(("boundary", "foreign"), [("before_head", False), ("before_projection", False), ("before_projection", True)])
def test_nested_parent_replacement_cannot_reuse_an_absence_bound_to_another_directory(generated, monkeypatch, tmp_path, boundary, foreign):
    store, _original, missing = generated
    before = store.snapshot()
    root_identity = store.root.stat().st_ino
    command = ProjectCommand.create("native_export", "nested", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={missing.resource: missing.before_sha256},
        write_set=[missing.resource], request={"nested_output": True}, missing_outputs=[missing])
    parent = (store.root / missing.resource).parent
    actual = state.boundary

    def replace_parent(name):
        if name == boundary:
            parent.rename(tmp_path / "preserved-original-export-parent")
            parent.mkdir()
            if foreign:
                (store.root / missing.resource).write_bytes(b"late foreign nested output")
        actual(name)

    monkeypatch.setattr(state, "boundary", replace_parent)
    with pytest.raises(ProjectConflict) as caught:
        ProjectCommands(store).execute(command, lambda: ProjectMutation({missing.resource: b"fresh render"}, {}))
    if not foreign:
        assert "observed parent changed" in str(caught.value)
    assert store.root.stat().st_ino == root_identity
    assert ((store.root / missing.resource).read_bytes() == b"late foreign nested output" if foreign
            else not (store.root / missing.resource).exists())
    assert (store.root / "document.vsz").read_bytes() == b"original saved native authority"


@pytest.mark.parametrize("generated", ["first/figure.pdf"], indirect=True)
def test_all_missing_output_parents_are_validated_before_any_recovery_install(generated, monkeypatch, tmp_path):
    store, _original, first = generated
    second = store.root / "second/figure.pdf"
    second.parent.mkdir()
    before = store.snapshot()
    producer = ProjectCommand.create("native_export", "second", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"second/figure.pdf": None},
        write_set=["second/figure.pdf"], request={"second_render": True})
    ProjectCommands(store).execute(producer, lambda: ProjectMutation({"second/figure.pdf": b"old second PDF"},
        {"exports": [{"path": str(second), "sha256": sha(b"old second PDF"), "format": "pdf"}]}))
    second.unlink()
    missing = discover(store, [first.resource, "second/figure.pdf"])
    current = store.snapshot()
    command = ProjectCommand.create("native_export", "both-fresh", project_id=current["project_id"],
        expected_generation=current["generation"], read_set={item.resource: item.before_sha256 for item in missing},
        write_set=[item.resource for item in missing], request={"both_render": True}, missing_outputs=missing)
    actual = state.boundary

    def stop(name):
        if name == "after_head":
            raise OSError("committed before installing either output")
        actual(name)

    monkeypatch.setattr(state, "boundary", stop)
    with pytest.raises(OSError, match="committed before"):
        ProjectCommands(store).execute(command, lambda: ProjectMutation({item.resource: b"fresh output" for item in missing}, {}))
    monkeypatch.setattr(state, "boundary", actual)
    second.parent.rename(tmp_path / "second-parent-backup")
    second.parent.mkdir()
    with pytest.raises(ProjectConflict, match="observed parent changed"):
        ProjectCommands(store).resume(command)
    assert not (store.root / first.resource).exists() and not second.exists()


def test_unknown_new_command_cannot_retry_native_or_be_hidden_by_discovery(generated, monkeypatch):
    store, _original, _missing = generated
    command = command_for(generated)
    calls = []

    def unknown():
        calls.append("native started")
        raise OSError("lost render reply")

    with pytest.raises(OSError):
        ProjectCommands(store).execute(command, unknown)
    with pytest.raises(ProjectCommandUnknown):
        ProjectCommands(store).execute(command, lambda: pytest.fail("Unknown native was repeated"))
    assert calls == ["native started"]


def test_early_expected_metadata_guard_rejects_erased_declaration(generated, monkeypatch):
    store, _original, _missing = generated
    command = command_for(generated)
    stage = store.publish

    def erased(*args, **kwargs):
        expected = dict(kwargs["expected_metadata"])
        expected.pop("missing_outputs")
        kwargs["expected_metadata"] = expected
        return stage(*args, **kwargs)

    monkeypatch.setattr(store, "publish", erased)
    with pytest.raises(ProjectConflict, match="metadata differs"):
        ProjectCommands(store).execute(command, lambda: candidate(generated))
    assert not (store.root / "figure.pdf").exists()
