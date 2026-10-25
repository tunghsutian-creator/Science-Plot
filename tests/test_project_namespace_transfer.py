"""A fixed ownership fence retires tracked legacy bytes without a second writer."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_commands.resources import MembershipRead, NamespaceMember, NamespaceTransfer, PreparedFile
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ProjectRecoveryRequired, ResourceRoot, state
from sciplot_core.project_store.io import sha
from sciplot_core.project_store.namespace_io import OWNER


def encoded(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def fixture_transfer(tmp_path, *, external=False, relocated=False):
    project = tmp_path / "project"
    project.mkdir()
    old = tmp_path / "legacy" if external else project / ".sciplot_documents/legacy"
    old.mkdir(parents=True)
    (old / "head.json").write_bytes(b'{"revision":1}')
    (old / "state.json").write_bytes(b'{"state":"old"}')
    locations = {"legacy": ResourceRoot(old, ("head.json", "state.json"))} if external else {}
    original = FileProjectStore(project, locations=locations)
    before = original.snapshot(import_legacy=True)
    scientific_origin = str(old)
    if relocated:
        assert not external
        original.export_bundle(tmp_path / "original-bundle")
        original = FileProjectStore.import_bundle(tmp_path / "original-bundle", tmp_path / "relocated")
        project = original.root
        old = project / ".sciplot_documents/legacy"
        before = original.snapshot()
    (old / "head.json").write_bytes(b'{"revision":2}')
    (old / "state.json").write_bytes(b'{"state":"latest legacy authority"}')
    (old / "journal.json").write_bytes(b'{"history":"latest preserved"}')
    identity = uuid4().hex
    backup = old.with_name("history-" + identity)
    backup.mkdir(mode=0o700)
    prefix = "@legacy" if external else ".sciplot_documents/legacy"
    physical_prefix = None if external else backup.relative_to(project).as_posix()
    history = ".sciplot_semantic/" + identity + "/original-history" if external else physical_prefix
    request = {"attachment_id": identity, "origin_root": str(old), "scientific_origin": scientific_origin, "history_root": str(backup),
               "figure_id": "figure-A", "project_path": str(project)}
    owner = {"kind": "sciplot_semantic_owner", "version": 1, "origin_root": str(old), "project": str(project),
        "project_id": before["project_id"], "attachment_id": identity, "history_root": str(backup),
        "figure_id": "figure-A", "role": "redirect"}
    refusal = encoded({"kind": "sciplot_attached_semantic_redirect", "version": 1,
        "project_id": before["project_id"], "attachment_id": identity,
        "original_head_sha256": sha((old / "head.json").read_bytes())})
    redirect, historical = encoded(owner), encoded({**owner, "role": "history"})
    for name, data in (("head.json", refusal), (OWNER, redirect)):
        (backup / name).write_bytes(data)
        (backup / name).chmod(0o600)
    caps = {"legacy": ResourceRoot(old, ("head.json", "state.json", "journal.json", OWNER))} if external else {}
    store = FileProjectStore(project, locations=caps, namespace_backups={identity: backup})
    observed = store.capture_namespace(prefix)["members"]
    descriptor = NamespaceTransfer(prefix, history, identity, sha((old / "head.json").read_bytes()),
        sha(refusal), sha(redirect), sha(historical), tuple(NamespaceMember(name, value["sha256"], value["size"], value["mode"])
        for name, value in sorted(observed.items())), physical_prefix)
    writes = {prefix + "/" + name: None for name in observed}
    writes.update({prefix + "/head.json": PreparedFile(refusal, 0o600), prefix + "/" + OWNER: PreparedFile(redirect, 0o600)})
    for name, value in observed.items():
        writes[history + "/" + name] = PreparedFile(value["data"], value["mode"])
    writes[history + "/" + OWNER] = PreparedFile(historical, 0o600)
    writes["canonical/state.json"] = PreparedFile(b'{"canonical":"latest preserved"}', 0o640)
    mutation = ProjectMutation(writes, {"attachment_id": identity})
    command = ProjectCommand.create("attachment_import", "attach-" + identity, project_id=before["project_id"],
        expected_generation=before["generation"], read_set={name: before["files"].get(name, {}).get("sha256") for name in writes},
        write_set=list(writes), request={**request, "prepared_digest": mutation.prepared_digest},
        read_memberships=[MembershipRead.capture(before["files"], prefix), MembershipRead.capture(before["files"], history)],
        namespace_transfers=[descriptor])
    return original, store, before, old, backup, historical, descriptor, command, mutation


def fence(old, backup, history_owner):
    original_inode = old.stat().st_ino
    (old / OWNER).write_bytes(history_owner)
    (old / OWNER).chmod(0o600)
    temporary = old.with_name("moving-" + uuid4().hex)
    old.rename(temporary)
    backup.rename(old)
    temporary.rename(backup)
    assert backup.stat().st_ino == original_inode


@pytest.mark.parametrize("external", [False, True])
def test_exact_latest_namespace_transfer_keeps_old_history_and_cold_refusal(tmp_path, external):
    original, store, before, old, backup, history_owner, descriptor, command, mutation = fixture_transfer(tmp_path, external=external)
    review = ProjectCommands(store).stage_prepared(command, mutation)
    assert review["phase"] == "needs_review"
    with pytest.raises(ProjectRecoveryRequired, match="original location"):
        store.export_bundle(tmp_path / "premature-bundle")
    assert not (tmp_path / "premature-bundle").exists()
    fence(old, backup, history_owner)
    receipt = ProjectCommands(store).decide(command, decision_id=review["decision_id"], accept=True)
    assert receipt["phase"] == "complete"
    assert json.loads((old / "head.json").read_bytes())["kind"] == "sciplot_attached_semantic_redirect"
    assert (backup / "head.json").read_bytes() == b'{"revision":2}'
    assert original.snapshot()["outside_changes"] == {}
    assert original.read_bytes(descriptor.prefix + "/head.json", generation=before["generation"]) == b'{"revision":1}'
    assert original.read_bytes(descriptor.history_prefix + "/head.json") == b'{"revision":2}'
    assert not (old / "state.json").exists()
    store.export_bundle(tmp_path / "bundle")
    cold = FileProjectStore.import_bundle(tmp_path / "bundle", tmp_path / "cold")
    assert cold.read_bytes(descriptor.history_prefix + "/head.json") == b'{"revision":2}'
    assert json.loads(cold.read_bytes(descriptor.prefix + "/head.json"))["kind"] == "sciplot_attached_semantic_redirect"
    assert cold.snapshot()["outside_changes"] == {}


def test_changed_history_after_fence_never_overwrites_originals_or_publishes(tmp_path):
    _original, store, before, old, backup, history_owner, _descriptor, command, mutation = fixture_transfer(tmp_path)
    review = ProjectCommands(store).stage_prepared(command, mutation)
    fence(old, backup, history_owner)
    (backup / "state.json").write_bytes(b"outside changed historical bytes")
    with pytest.raises(ProjectConflict):
        ProjectCommands(store).decide(command, decision_id=review["decision_id"], accept=True)
    assert (backup / "state.json").read_bytes() == b"outside changed historical bytes"
    assert json.loads((old / "head.json").read_bytes())["kind"] == "sciplot_attached_semantic_redirect"
    assert store.query(command.key)["phase"] == "accepted"
    assert store.read_bytes(".sciplot_documents/legacy/head.json", generation=before["generation"]) == b'{"revision":1}'


@pytest.mark.parametrize("point", ["before_head", "after_head", "after_projection"])
def test_interrupted_transfer_recovers_only_exact_new_generation_without_restoring_old_writer(tmp_path, monkeypatch, point):
    _original, store, before, old, backup, history_owner, descriptor, command, mutation = fixture_transfer(tmp_path, external=True)
    review = ProjectCommands(store).stage_prepared(command, mutation)
    fence(old, backup, history_owner)
    class Interrupted(Exception):
        pass
    def stop(name):
        if name == point:
            raise Interrupted()
    monkeypatch.setattr(state, "boundary", stop)
    with pytest.raises(Interrupted):
        ProjectCommands(store).decide(command, decision_id=review["decision_id"], accept=True)
    assert json.loads((old / "head.json").read_bytes())["kind"] == "sciplot_attached_semantic_redirect"
    assert (backup / "head.json").read_bytes() == b'{"revision":2}'
    if point == "before_head":
        with pytest.raises(ProjectRecoveryRequired, match="original location"):
            store.export_bundle(tmp_path / "pending-bundle")
    monkeypatch.setattr(state, "boundary", lambda _name: None)
    receipt = ProjectCommands(store).resume(command)
    assert receipt["phase"] == "complete"
    assert store.snapshot()["outside_changes"] == {}
    assert store.read_bytes(descriptor.prefix + "/head.json", generation=before["generation"]) == b'{"revision":1}'
    assert (backup / "head.json").read_bytes() == b'{"revision":2}'
    assert json.loads((old / "head.json").read_bytes())["kind"] == "sciplot_attached_semantic_redirect"


@pytest.mark.parametrize("fenced", [False, True])
def test_rejected_bundle_requires_exact_original_inode_and_pre_fence_census(tmp_path, fenced):
    _original, store, _before, old, backup, history_owner, _descriptor, command, mutation = fixture_transfer(tmp_path)
    review = ProjectCommands(store).stage_prepared(command, mutation)
    if fenced:
        fence(old, backup, history_owner)
    receipt = ProjectCommands(store).decide(command, decision_id=review["decision_id"], accept=False)
    assert receipt["phase"] == "rejected"
    if fenced:
        with pytest.raises(ProjectRecoveryRequired, match="rejected ownership"):
            store.export_bundle(tmp_path / "bundle")
        assert not (tmp_path / "bundle").exists()
        assert json.loads((old / "head.json").read_bytes())["kind"] == "sciplot_attached_semantic_redirect"
    else:
        store.export_bundle(tmp_path / "bundle")
        assert (old / "head.json").read_bytes() == b'{"revision":2}'
        assert json.loads((backup / "head.json").read_bytes())["kind"] == "sciplot_attached_semantic_redirect"


@pytest.mark.parametrize("change", ["extra", "foreign-owner", "owner-mode"])
def test_fence_control_changes_never_gain_capability_or_publish(tmp_path, change):
    _original, store, _before, old, backup, history_owner, _descriptor, command, mutation = fixture_transfer(tmp_path, external=True)
    review = ProjectCommands(store).stage_prepared(command, mutation)
    fence(old, backup, history_owner)
    if change == "extra":
        (old / "foreign.json").write_bytes(b"ungranted outside record")
    elif change == "foreign-owner":
        value = json.loads((old / OWNER).read_bytes())
        (old / OWNER).write_bytes(encoded({**value, "project_id": uuid4().hex}))
    else:
        (old / OWNER).chmod(0o644)
    frozen = {path.name: path.read_bytes() for path in old.iterdir()}
    with pytest.raises((ProjectConflict, ProjectRecoveryRequired)):
        ProjectCommands(store).decide(command, decision_id=review["decision_id"], accept=True)
    assert {path.name: path.read_bytes() for path in old.iterdir()} == frozen
    assert (backup / "head.json").read_bytes() == b'{"revision":2}'


def test_extra_old_namespace_member_after_stage_is_not_silently_retired(tmp_path):
    _original, store, _before, old, _backup, _history_owner, _descriptor, command, mutation = fixture_transfer(tmp_path)
    review = ProjectCommands(store).stage_prepared(command, mutation)
    (old / "late.json").write_bytes(b"new legacy record")
    with pytest.raises(ProjectConflict):
        ProjectCommands(store).decide(command, decision_id=review["decision_id"], accept=True)
    assert (old / "late.json").read_bytes() == b"new legacy record"
    assert (old / "head.json").read_bytes() == b'{"revision":2}'


def test_complete_namespace_and_history_never_regain_an_active_store_writer(tmp_path):
    _original, store, _before, old, backup, history_owner, descriptor, command, mutation = fixture_transfer(tmp_path)
    review = ProjectCommands(store).stage_prepared(command, mutation)
    fence(old, backup, history_owner)
    ProjectCommands(store).decide(command, decision_id=review["decision_id"], accept=True)
    before = store.snapshot()
    for prefix in (descriptor.prefix, descriptor.history_prefix):
        resource = prefix + "/head.json"
        attack = ProjectCommand.create("semantic_record", "foreign-write-" + resource,
            project_id=before["project_id"], expected_generation=before["generation"],
            read_set={resource: before["files"][resource]["sha256"]}, write_set=[resource], request={})
        with pytest.raises(ProjectConflict, match="history|retired"):
            ProjectCommands(store).execute(attack, lambda resource=resource: ProjectMutation({resource: b'{"revision":99}'}, {}))
    assert json.loads((old / "head.json").read_bytes())["kind"] == "sciplot_attached_semantic_redirect"
    assert (backup / "head.json").read_bytes() == b'{"revision":2}'


def test_empty_descriptor_attachment_import_still_blocks_pending_portable_old_writer(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    mutation = ProjectMutation({"canonical/head.json": b"frozen semantic record"}, {})
    command = ProjectCommand.create("attachment_import", "untracked external attachment", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"canonical/head.json": None},
        write_set=["canonical/head.json"], request={"prepared_digest": mutation.prepared_digest})
    assert not command.namespace_transfers
    ProjectCommands(store).stage_prepared(command, mutation)
    with pytest.raises(ProjectRecoveryRequired, match="original location"):
        store.export_bundle(tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize("forged", [False, True])
def test_moved_project_preserves_scientific_origin_and_binds_exact_physical_namespace(tmp_path, forged):
    _original, store, _before, old, backup, history_owner, descriptor, command, mutation = fixture_transfer(tmp_path, relocated=True)
    request = json.loads(command.request_json)
    assert request["scientific_origin"] != request["origin_root"]
    if forged:
        command = replace(command, request_json=json.dumps({**request, "origin_root": str(tmp_path / "foreign-namespace")}))
        with pytest.raises(ProjectConflict, match="physical namespace"):
            ProjectCommands(store).stage_prepared(command, mutation)
        assert (old / "head.json").read_bytes() == b'{"revision":2}'
        assert json.loads((backup / "head.json").read_bytes())["kind"] == "sciplot_attached_semantic_redirect"
        return
    review = ProjectCommands(store).stage_prepared(command, mutation)
    fence(old, backup, history_owner)
    assert ProjectCommands(store).decide(command, decision_id=review["decision_id"], accept=True)["phase"] == "complete"
    assert store.snapshot()["outside_changes"] == {}
    assert store.read_bytes(descriptor.history_prefix + "/head.json") == b'{"revision":2}'
