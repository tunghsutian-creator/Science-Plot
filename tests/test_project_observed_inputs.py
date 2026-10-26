"""Typed immutable reads narrow writes; ordinary source versions do not."""
from dataclasses import replace
import json
from uuid import uuid4

import pytest

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import InputRead, PreparedFile, PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ProjectRecoveryRequired, ResourceRoot, state
from sciplot_core.project_store.io import digest, sha


def input_store(tmp_path, mounted=False):
    root = tmp_path / "project"
    root.mkdir()
    (root / "native.vsz").write_bytes(b"unchanged native")
    location = tmp_path / "evidence" if mounted else root / "confirmed"
    location.mkdir()
    target = location / "execution.json"
    target.write_bytes(b'{"exact":"immutable input"}')
    target.chmod(0o600)
    store = FileProjectStore(root, locations={"evidence": ResourceRoot(location, ("execution.json",))} if mounted else {})
    before = store.snapshot(import_legacy=True)
    resource = "@evidence/execution.json" if mounted else "confirmed/execution.json"
    source = PreparedSource(uuid4().hex, str(target), sha(target.read_bytes()), target.read_bytes(), mode=0o600)
    return store, before, resource, target, source


def reserve_read(store, before, resource, source, key="register", *, write=False):
    return store.reserve(key, key + "-digest", expected_generation=before["generation"],
        read_set={resource: before["files"][resource]["sha256"]}, write_set=[resource] if write else [],
        metadata={"kind": "synthetic", "input_reads": [InputRead(resource, source.source_id, source.version).to_payload()]})


def prepared_read(store, before, resource, source, *, dynamic=False, both=False, key="typed read"):
    declared = InputRead(resource, source.source_id, source.version)
    mutation = ProjectMutation({}, {}, prepared_sources=(source,), input_reads=(declared,) if dynamic or both else ())
    command = ProjectCommand.create("semantic_record", key, project_id=before["project_id"],
        expected_generation=before["generation"], read_set={resource: before["files"][resource]["sha256"]},
        write_set=[], request={"prepared_digest": mutation.prepared_digest}, input_reads=() if dynamic else (declared,))
    return command, mutation


@pytest.mark.parametrize("mounted", [False, True])
def test_registered_immutable_input_cannot_become_a_later_generic_output(tmp_path, mounted):
    store, before, resource, target, source = input_store(tmp_path, mounted)
    reserve_read(store, before, resource, source)
    old = target.stat()
    store.publish("register", "register-digest", writes={}, result={}, sources=[source.to_storage_payload()])
    observed = store.snapshot()
    with pytest.raises(ProjectConflict):
        store.reserve("overwrite", "overwrite-digest", expected_generation=observed["generation"],
            read_set={resource: observed["files"][resource]["sha256"]}, write_set=[resource], metadata={"kind": "synthetic"})
        store.publish("overwrite", "overwrite-digest", writes={resource: b"forbidden writeback"}, result={})
    assert target.read_bytes() == source.data
    now = target.stat()
    assert (now.st_ino, now.st_mode, now.st_mtime_ns, now.st_ctime_ns) == (old.st_ino, old.st_mode, old.st_mtime_ns, old.st_ctime_ns)
    assert resource in observed["input_resources"]
    assert observed["sources"][source.source_id][source.version]["locator"] == source.locator
    assert store.read_bytes(resource, generation=before["generation"]) == source.data


@pytest.mark.parametrize("mounted", [False, True])
def test_first_input_declaration_cannot_also_write_the_observed_member(tmp_path, mounted):
    store, before, resource, target, source = input_store(tmp_path, mounted)
    with pytest.raises(ProjectConflict):
        reserve_read(store, before, resource, source, write=True)
        store.publish("register", "register-digest", writes={resource: b"different output in same generation"},
                      result={}, sources=[source.to_storage_payload()])
    assert target.read_bytes() == source.data
    assert store.snapshot()["generation"] == before["generation"]


def test_plain_legacy_generated_source_read_does_not_freeze_future_regeneration(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    target = root / "derived.csv"
    target.write_bytes(b"x,y\n1,2\n")
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    old = before["files"]["derived.csv"]
    source = PreparedSource(old["file_id"], str(target), old["sha256"], target.read_bytes(), mode=old["mode"])
    store.reserve("ordinary-read", "ordinary-read-digest", expected_generation=before["generation"],
                  read_set={"derived.csv": source.version}, write_set=[], metadata={"kind": "synthetic"})
    store.publish("ordinary-read", "ordinary-read-digest", writes={}, result={}, sources=[source.to_storage_payload()])
    current = store.snapshot()
    assert "derived.csv" not in current.get("input_resources", [])
    new = b"x,y\n1,3\n"
    produced = PreparedSource(source.source_id, source.locator, sha(new), new, mode=source.mode,
                              produced_resource="derived.csv")
    mutation = ProjectMutation({"derived.csv": PreparedFile(new, source.mode)}, {}, prepared_sources=(produced,))
    command = ProjectCommand.create("figure_set", "regenerate", project_id=current["project_id"],
        expected_generation=current["generation"], read_set={"derived.csv": source.version},
        write_set=["derived.csv"], request={})
    assert ProjectCommands(store).execute(command, lambda: mutation)["phase"] == "complete"
    assert target.read_bytes() == new
    assert store.read_bytes("derived.csv", generation=before["generation"]) == source.data


@pytest.mark.parametrize("dynamic,both", [(False, False), (True, False), (False, True)])
def test_static_or_dynamic_input_is_sealed_and_same_declaration_can_coalesce(tmp_path, dynamic, both):
    store, before, resource, target, source = input_store(tmp_path)
    command, mutation = prepared_read(store, before, resource, source, dynamic=dynamic, both=both)
    assert ("input_reads" in command.to_payload()) is not dynamic
    assert ProjectCommand.from_payload(command.to_payload()) == command
    result = ProjectCommands(store).publish_prepared(command, mutation)
    assert result["phase"] == "complete" and store.snapshot()["input_resources"] == [resource]
    assert result["draft"]["input_reads"] == [InputRead(resource, source.source_id, source.version).to_payload()]
    changed = {**result["draft"], "input_reads": []}
    assert digest({"command_digest": command.command_digest, "candidate": changed}) != result["decision_id"]
    assert target.read_bytes() == source.data


def test_old_empty_serialized_fields_and_prepared_digest_remain_unchanged(tmp_path):
    store, before, resource, _target, source = input_store(tmp_path)
    plain = ProjectCommand.create("attachment_import", "plain", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={resource: source.version}, write_set=[], request={})
    old = plain.to_payload()
    assert "input_reads" not in old
    assert ProjectCommand.from_payload(old).to_payload() == old
    assert plain.command_digest == canonical_json_sha256(old, allow_nan=False)
    mutation = ProjectMutation({}, {"old": "result"}, prepared_sources=(source,))
    expected = {"writes": {}, "artifacts": {}, "result": mutation.result, "review": None,
                "sources": [source.descriptor()]}
    assert mutation.prepared_digest == canonical_json_sha256(expected, allow_nan=False)
    declared = InputRead(resource, source.source_id, source.version)
    assert replace(mutation, input_reads=(declared,)).prepared_digest != mutation.prepared_digest
    with pytest.raises(ValueError):
        InputRead.from_payload({**declared.to_payload(), "readonly": True})


def test_identical_declarations_canonicalize_but_conflicting_identity_refuses(tmp_path):
    store, before, resource, _target, source = input_store(tmp_path)
    command, mutation = prepared_read(store, before, resource, source, dynamic=True)
    declared = mutation.input_reads[0]
    single = replace(command, input_reads=(declared,))
    repeated = ProjectCommand.create(single.kind, single.key, project_id=single.project_id,
        expected_generation=single.expected_generation, read_set=dict(single.read_set), write_set=single.write_set,
        request=json.loads(single.request_json), input_reads=(declared, declared))
    assert repeated == single and repeated.command_digest == single.command_digest
    assert replace(mutation, input_reads=(declared, declared)).prepared_digest == mutation.prepared_digest
    foreign = replace(declared, source_id=uuid4().hex)
    with pytest.raises(ValueError, match="disagree"):
        _ = replace(mutation, input_reads=(declared, foreign)).prepared_digest
    with pytest.raises(ValueError, match="disagree"):
        replace(single, input_reads=(declared, foreign))


@pytest.mark.parametrize("fault", ["missing", "identity", "locator", "mode", "version", "size"])
def test_input_declaration_requires_exact_same_batch_captured_source(tmp_path, fault):
    store, before, resource, target, source = input_store(tmp_path)
    reserve_read(store, before, resource, source)
    payload = source.to_storage_payload()
    if fault == "identity":
        payload["source_id"] = uuid4().hex
    elif fault == "locator":
        other = tmp_path / "same-bytes.json"
        other.write_bytes(source.data)
        payload["locator"] = str(other)
    elif fault == "mode":
        payload["mode"] = 0o644
    elif fault == "version":
        payload.update(data=b"not the guarded bytes", version=sha(b"not the guarded bytes"), size=len(b"not the guarded bytes"))
    elif fault == "size":
        payload["size"] += 1
    with pytest.raises(ProjectConflict):
        store.publish("register", "register-digest", writes={}, result={}, sources=[] if fault == "missing" else [payload])
    assert target.read_bytes() == source.data and store.snapshot()["generation"] == before["generation"]


@pytest.mark.parametrize("fault", ["bytes", "mode"])
def test_dynamic_input_is_rechecked_at_head_and_never_restored(tmp_path, monkeypatch, fault):
    store, before, resource, target, source = input_store(tmp_path)
    command, mutation = prepared_read(store, before, resource, source, dynamic=True)
    app = ProjectCommands(store)
    staged = app.stage_prepared(command, mutation)

    def drift(name):
        if name == "before_head":
            target.write_bytes(b"foreign bytes") if fault == "bytes" else target.chmod(0o640)

    monkeypatch.setattr(state, "boundary", drift)
    with pytest.raises(ProjectConflict):
        app.decide(command, decision_id=staged["decision_id"], accept=True)
    assert store.snapshot()["generation"] == before["generation"]
    assert target.read_bytes() == (b"foreign bytes" if fault == "bytes" else source.data)
    assert target.stat().st_mode & 0o777 == (0o600 if fault == "bytes" else 0o640)


def test_typed_input_cannot_be_washed_as_a_produced_output(tmp_path):
    store, before, resource, target, source = input_store(tmp_path)
    command, mutation = prepared_read(store, before, resource, source)
    ProjectCommands(store).publish_prepared(command, mutation)
    current = store.snapshot()
    produced = replace(source, produced_resource=resource)
    writer = ProjectCommand.create("figure_set", "fake output", project_id=current["project_id"],
        expected_generation=current["generation"], read_set={resource: source.version}, write_set=[resource], request={})
    with pytest.raises(ProjectConflict):
        ProjectCommands(store).execute(writer, lambda: ProjectMutation({resource: PreparedFile(source.data, source.mode)}, {},
                                                                     prepared_sources=(produced,)))
    assert target.read_bytes() == source.data and store.snapshot()["generation"] == current["generation"]


@pytest.mark.parametrize("mounted", [False, True])
def test_input_marker_source_identity_and_replay_survive_official_cold_bundle(tmp_path, mounted):
    store, before, resource, target, source = input_store(tmp_path, mounted)
    command, mutation = prepared_read(store, before, resource, source, dynamic=True)
    result = ProjectCommands(store).publish_prepared(command, mutation)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    store.root.rename(tmp_path / "old-project-offline")
    if mounted:
        target.parent.rename(tmp_path / "old-evidence-offline")
    assert cold.snapshot()["input_resources"] == [resource]
    assert cold.snapshot()["sources"][source.source_id][source.version]["locator"] == source.locator
    assert ProjectCommands(cold).resume(command)["generation"] == result["generation"]
    with pytest.raises(ProjectConflict):
        current = cold.snapshot()
        cold.reserve("write cold", "write cold-digest", expected_generation=current["generation"],
                     read_set={resource: source.version}, write_set=[resource], metadata={"kind": "synthetic"})
    assert cold.read_bytes(resource) == source.data


def test_proven_produced_source_can_be_read_then_regenerated_without_implicit_input_role(tmp_path):
    store, _before, _resource, _target, _source = input_store(tmp_path)
    identity = uuid4().hex
    locator = str(store.root / "derived.csv")

    def produce(key, data):
        current = store.snapshot()
        source = PreparedSource(identity, locator, sha(data), data, mode=0o640, produced_resource="derived.csv")
        command = ProjectCommand.create("figure_set", key, project_id=current["project_id"],
            expected_generation=current["generation"], read_set={"derived.csv": current["files"].get("derived.csv", {}).get("sha256")},
            write_set=["derived.csv"], request={})
        receipt = ProjectCommands(store).execute(command, lambda: ProjectMutation(
            {"derived.csv": PreparedFile(data, source.mode)}, {}, prepared_sources=(source,)))
        return receipt, source

    first, source = produce("first output", b"x,y\n1,2\n")
    current = store.snapshot()
    store.reserve("read produced", "read produced-digest", expected_generation=current["generation"],
                  read_set={"derived.csv": source.version}, write_set=[], metadata={"kind": "synthetic"})
    store.publish("read produced", "read produced-digest", writes={}, result={},
                  sources=[replace(source, produced_resource=None).to_storage_payload()])
    assert "derived.csv" not in store.snapshot().get("input_resources", [])
    second, newest = produce("second output", b"x,y\n1,3\n")
    assert second["generation"] != first["generation"]
    assert store.read_bytes("derived.csv") == newest.data
    assert store.read_bytes("derived.csv", generation=first["generation"]) == source.data


def test_explicit_source_adoption_still_updates_an_input_without_installing_original(tmp_path):
    from test_project_source_observations import fixture_observation

    store, before, raw, identity, command, mutation = fixture_observation(tmp_path)
    command = replace(command, input_reads=(InputRead("source.csv", identity, mutation.prepared_sources[0].version),))
    original = raw.stat()
    result = ProjectCommands(store).publish_prepared(command, mutation)
    assert result["phase"] == "complete" and store.snapshot()["input_resources"] == ["source.csv"]
    assert (raw.stat().st_ino, raw.stat().st_mode, raw.stat().st_mtime_ns) == (
        original.st_ino, original.st_mode, original.st_mtime_ns)
    assert store.read_bytes("source.csv", generation=before["generation"]) == b"old input"
    assert raw.read_bytes() == b"new input"


def test_later_input_observation_cannot_regrant_an_old_writer_recovery_rights(tmp_path):
    store, before, resource, target, source = input_store(tmp_path)
    store.reserve("old writer", "old writer-digest", expected_generation=before["generation"],
                  read_set={resource: source.version}, write_set=[resource], metadata={"kind": "synthetic"})
    store.publish("old writer", "old writer-digest", writes={resource: PreparedFile(b"new baseline", source.mode)}, result={})
    current = store.snapshot()
    observed = replace(source, version=sha(b"new baseline"), data=b"new baseline")
    command, mutation = prepared_read(store, current, resource, observed)
    ProjectCommands(store).publish_prepared(command, mutation)
    head = (store.root / ".sciplot_store/head.json").read_bytes()
    record_path = store.root / ".sciplot_store" / state.command_path("old writer")
    record = json.loads(record_path.read_bytes())
    record["phase"] = "accepted"
    record_path.write_text(json.dumps(record))
    target.write_bytes(source.data)
    with pytest.raises(ProjectRecoveryRequired, match="Outside bytes"):
        store.recover()
    assert target.read_bytes() == source.data
    assert (store.root / ".sciplot_store/head.json").read_bytes() == head


def test_first_input_cannot_gain_write_rights_from_a_matching_produced_tag(tmp_path):
    store, before, resource, target, source = input_store(tmp_path)
    head = (store.root / ".sciplot_store/head.json").read_bytes()
    store.reserve("dual role", "dual role-digest", expected_generation=before["generation"],
        read_set={resource: source.version}, write_set=[resource], metadata={"kind": "synthetic"})
    declared = InputRead(resource, source.source_id, source.version)
    with pytest.raises(ProjectConflict, match="cannot be an output"):
        store.publish("dual role", "dual role-digest", writes={resource: PreparedFile(source.data, source.mode)},
            result={}, sources=[replace(source, produced_resource=resource).to_storage_payload()],
            input_reads=[declared.to_payload()])
    assert store.snapshot()["generation"] == before["generation"]
    assert target.read_bytes() == source.data
    assert (store.root / ".sciplot_store/head.json").read_bytes() == head


def test_dynamic_input_cannot_add_unknown_reads_or_output_overlap(tmp_path):
    store, before, resource, target, source = input_store(tmp_path)
    declared = InputRead(resource, source.source_id, source.version)
    command = ProjectCommand.create("figure_set", "dynamic output", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={resource: source.version}, write_set=[resource], request={})
    with pytest.raises(ValueError, match="cannot be an output"):
        ProjectCommands(store).execute(command, lambda: ProjectMutation({resource: source.data}, {},
            prepared_sources=(source,), input_reads=(declared,)))
    assert target.read_bytes() == source.data and store.snapshot()["generation"] == before["generation"]
    command = ProjectCommand.create("figure_set", "unknown read", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={}, write_set=[], request={})
    with pytest.raises(ValueError, match="guarded source read"):
        ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}, prepared_sources=(source,), input_reads=(declared,)))


@pytest.mark.parametrize("dynamic", [False, True])
def test_accepted_input_candidate_moves_and_resumes_without_repreparing(tmp_path, dynamic):
    store, before, resource, _target, source = input_store(tmp_path)
    command, mutation = prepared_read(store, before, resource, source, dynamic=dynamic)
    preview = ProjectCommands(store).stage_prepared(command, mutation)
    store.decide(command.key, command.command_digest, decision_id=preview["decision_id"], accept=True)
    assert resource not in store.snapshot().get("input_resources", [])
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "pending-bundle"), tmp_path / "pending-cold")
    store.root.rename(tmp_path / "pending-origin-offline")
    assert ProjectCommands(cold).resume(command)["phase"] == "complete"
    assert cold.snapshot()["input_resources"] == [resource]
    assert cold.read_bytes(resource) == source.data
    assert ProjectCommands(cold).execute(command, lambda: pytest.fail("a sealed input candidate was re-prepared"))["replayed"]


@pytest.mark.parametrize("dynamic", [False, True])
def test_sealed_input_declaration_cannot_be_dropped_or_rebound_by_mutable_hints(tmp_path, dynamic):
    store, before, resource, target, source = input_store(tmp_path)
    command, mutation = prepared_read(store, before, resource, source, dynamic=dynamic)
    staged = ProjectCommands(store).stage_prepared(command, mutation)
    store.decide(command.key, command.command_digest, decision_id=staged["decision_id"], accept=True)
    path = store.root / ".sciplot_store" / state.command_path(command.key)
    record = json.loads(path.read_bytes())
    if dynamic:
        record["draft"].pop("input_reads")
    else:
        record["metadata"].pop("input_reads")
    path.write_text(json.dumps(record))
    with pytest.raises(ProjectConflict):
        ProjectCommands(store).resume(command)
    assert target.read_bytes() == source.data
    assert json.loads((store.root / ".sciplot_store/head.json").read_bytes())["generation"] == before["generation"]
