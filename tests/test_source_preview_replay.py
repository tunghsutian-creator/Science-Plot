"""A source review reuses only the same immutable candidate and original read set."""
import json
import shutil

import pytest

from test_project_query import project as project
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.studio_core import source_update
from sciplot_core.studio_core.project_command_scope import command_for_binding, project_store
from sciplot_core.project_commands import ProjectCommands
from sciplot_core.studio_core.source_update_commands import source_review_binding, stage_source_update
from sciplot_core.studio_core.source_update_files import file_inventory, project_inventory
from sciplot_core.studio_core.source_update_review import payload_hash


def prepared(project, tmp_path):
    (project / "raw").mkdir()
    (project / "raw/original.csv").write_bytes(b"preserved instrument output")
    candidate = tmp_path / "frozen-source"
    shutil.copytree(project, candidate)
    (candidate / "source/data.csv").write_bytes(b"audited candidate table")
    source = tmp_path / "incoming.csv"
    source.write_bytes(b"confirmed new original source")
    review = {"kind": "sciplot_project_source_update", "version": 1, "status": "ready",
        "project": str(project), "source": str(source), "source_kind": "file", "worksheet": None,
        "source_files": file_inventory(source), "source_tree_sha256": source_tree_sha256(source),
        "annotation_decisions": [], "project_sha256": payload_hash(project_inventory(project)),
        "delivery_sha256": payload_hash(None), "changes": {}, "styles": []}
    return candidate, source, review


@pytest.mark.parametrize("deletion", [False, True])
def test_source_preview_replay_reconstructs_frozen_candidate_without_native_preparation(project, tmp_path, monkeypatch, deletion):
    candidate, source, review = prepared(project, tmp_path)
    if deletion:
        (project / "studio/old-metadata.json").write_bytes(b"old native preparation metadata")
        review["project_sha256"] = payload_hash(project_inventory(project))
    saved = stage_source_update(project, candidate, review)
    before = project_inventory(project)
    monkeypatch.setattr(source_update, "project_figures", lambda root: {"first": (root / "studio/document.vsz", root / "studio/spec.json")})
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *_a, **_kw: pytest.fail("must not reprepare a sealed candidate"))
    monkeypatch.setattr(source_update, "capture_project_styles", lambda *_a: pytest.fail("must not reinspect old native"))
    monkeypatch.setattr(source_update, "_audit_exact_document_data", lambda **_kw: pytest.fail("must not reaudit frozen science"))
    seen = []
    def preview(path, value):
        assert value == saved
        assert (path / "source/data.csv").read_bytes() == b"audited candidate table"
        assert not (path / "studio/old-metadata.json").exists()
        assert not (path / ".sciplot_store").exists()
        seen.append(path)
    assert source_update.preview_project_source_update(project, source, on_candidate=preview) == saved
    assert len(seen) == 1 and not seen[0].exists()
    assert project_inventory(project) == before
    assert len(ProjectCommands(project_store(project)).commands()) == 1


def test_unknown_source_preview_does_not_bypass_its_saved_key(project, tmp_path, monkeypatch):
    _candidate, source, review = prepared(project, tmp_path)
    store = project_store(project, with_snapshot=True)
    snapshot = store.snapshot(import_legacy=True)
    binding, intent, key = source_review_binding(store, snapshot, review)
    command = command_for_binding(store, binding, kind="source_update", key=key, writes=[], request=intent)
    store.reserve(key, command.command_digest, expected_generation=command.expected_generation,
        read_set=dict(command.read_set), write_set=[], metadata=command.to_payload())
    store.mark_applying(key, command.command_digest)
    monkeypatch.setattr(source_update, "project_figures", lambda root: {"first": (root / "studio/document.vsz", root / "studio/spec.json")})
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *_a, **_kw: pytest.fail("must not retry unknown preview"))
    result = source_update.preview_project_source_update(project, source)
    assert result["status"] == "blocked" and "already entered execution" in result["reason"]
    assert len(store.commands()) == 1 and store.query(key)["phase"] == "unknown"


def test_source_identity_and_entire_read_witness_are_part_of_the_normalized_intent(project, tmp_path):
    _candidate, source, review = prepared(project, tmp_path)
    store = project_store(project, with_snapshot=True)
    snapshot = store.snapshot(import_legacy=True)
    _binding, _intent, key = source_review_binding(store, snapshot, review)
    same_name = tmp_path / "other" / source.name
    same_name.parent.mkdir()
    same_name.write_bytes(source.read_bytes())
    assert source_review_binding(store, snapshot, {**review, "source": str(same_name)})[2] != key
    newer = json.loads(json.dumps(snapshot))
    newer["files"]["runs/late.json"] = {"sha256": "a" * 64, "size": 4, "mode": 0o644, "file_id": "b" * 32}
    assert source_review_binding(store, newer, review)[2] != key


@pytest.mark.parametrize("change", ["locator", "worksheet", "mapping", "annotations", "read-witness"])
def test_new_source_intent_cannot_read_incoming_data_while_searching_saved_previews(project, tmp_path, monkeypatch, change):
    from sciplot_core.project_commands import ProjectCommand, ProjectMutation
    from sciplot_core.project_store import source_trees
    from sciplot_core.studio_core import source_update_state

    candidate, source, review = prepared(project, tmp_path)
    stage_source_update(project, candidate, review)
    store = project_store(project)
    kwargs = {}
    if change == "locator":
        other = tmp_path / "other" / source.name
        other.parent.mkdir()
        other.write_bytes(source.read_bytes())
        source = other
    elif change == "worksheet":
        kwargs["worksheet"] = "New worksheet"
    elif change == "mapping":
        kwargs["mapping_request"] = {"rule_id": "new-scientific-intent", "template": "curve"}
    elif change == "annotations":
        kwargs["annotation_decisions"] = [{"figure_id": "first", "id": "different", "action": "remove"}]
    else:
        before = store.snapshot()
        command = ProjectCommand.create("style", "fixture-new-current-member", project_id=before["project_id"],
            expected_generation=before["generation"], read_set={"current-note.json": None}, write_set=["current-note.json"], request={})
        ProjectCommands(store).execute(command, lambda: ProjectMutation({"current-note.json": b"{}"}, {}))
    before = project_inventory(project)
    records = store.commands()
    monkeypatch.setattr(source_trees, "observe", lambda *_a, **_k: pytest.fail("new intent read an old declared input before admission"))
    monkeypatch.setattr(source_update, "file_inventory", lambda *_a: pytest.fail("new intent read incoming bytes before admission"))
    monkeypatch.setattr(source_update_state, "file_inventory", lambda *_a: pytest.fail("new intent used a saved preview's input permission"))
    result = source_update.preview_project_source_update(project, source, **kwargs)
    assert result["status"] == "blocked"
    expected = "confirmed experiment and template" if change == "mapping" else "fresh explicit data mapping"
    assert expected in result["reason"]
    assert project_inventory(project) == before and store.commands() == records


def test_exact_unknown_source_preview_is_reported_without_reading_incoming_data(project, tmp_path, monkeypatch):
    from sciplot_core.project_store import source_trees
    from sciplot_core.studio_core import source_update_state

    _candidate, source, review = prepared(project, tmp_path)
    store = project_store(project, with_snapshot=True)
    snapshot = store.snapshot(import_legacy=True)
    binding, intent, key = source_review_binding(store, snapshot, review)
    command = command_for_binding(store, binding, kind="source_update", key=key, writes=[], request=intent)
    store.reserve(key, command.command_digest, expected_generation=command.expected_generation,
        read_set=dict(command.read_set), write_set=[], metadata=command.to_payload())
    store.mark_applying(key, command.command_digest)
    monkeypatch.setattr(source_trees, "observe", lambda *_a, **_k: pytest.fail("unknown operation reread incoming data"))
    monkeypatch.setattr(source_update_state, "file_inventory", lambda *_a: pytest.fail("unknown operation inventoried incoming data"))
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *_a, **_k: pytest.fail("unknown operation reentered preparation"))
    result = source_update.preview_project_source_update(project, source)
    assert result["status"] == "blocked" and "already entered execution" in result["reason"]
    assert len(store.commands()) == 1 and store.query(key)["phase"] == "unknown"


@pytest.mark.parametrize("change", ["source-bytes", "source-mode", "source-alias", "project-spec", "delivery", "command-metadata"])
def test_saved_source_preview_refuses_drift_before_exposing_its_frozen_view(project, tmp_path, monkeypatch, change):
    from sciplot_core.project_store.command_records import command_path
    from sciplot_core.studio_core import source_update_replay

    delivery = tmp_path / "visible"
    if change == "delivery":
        request_path = project / "plot_request.json"
        request_path.write_text(json.dumps({**json.loads(request_path.read_bytes()), "delivery_output": str(delivery)}))
        delivery.mkdir()
        (delivery / "visible.pdf").write_bytes(b"original visible delivery")
    candidate, source, review = prepared(project, tmp_path)
    if change == "delivery":
        review["delivery_sha256"] = payload_hash(file_inventory(delivery))
    saved = stage_source_update(project, candidate, review)
    head = (project / ".sciplot_store/head.json").read_bytes()
    if change == "source-bytes":
        source.write_bytes(source.read_bytes() + b" changed")
    elif change == "source-mode":
        source.chmod(0o600 if source.stat().st_mode & 0o777 != 0o600 else 0o644)
    elif change == "source-alias":
        original = source.with_name("same-bytes-foreign.csv")
        source.rename(original)
        source.symlink_to(original)
    elif change == "project-spec":
        (project / "studio/spec.json").write_text("{}")
    elif change == "delivery":
        (delivery / "visible.pdf").write_bytes(b"changed visible delivery")
    else:
        path = project / ".sciplot_store" / command_path(saved["command_key"])
        record = json.loads(path.read_bytes())
        record["metadata"]["request"]["read_witness"] = "a" * 64
        path.write_text(json.dumps(record))
    monkeypatch.setattr(source_update_replay, "frozen_source_candidate", lambda *_a, **_k: pytest.fail("changed witness exposed a frozen preview"))
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *_a, **_k: pytest.fail("changed witness silently reexecuted"))
    result = source_update.preview_project_source_update(project, source)
    assert result["status"] == "blocked"
    assert (project / ".sciplot_store/head.json").read_bytes() == head


def test_source_preview_uses_unchanged_full_read_witness_after_an_unrelated_head_advance(project, tmp_path):
    from sciplot_core.project_commands import ProjectCommand, ProjectMutation

    candidate, source, review = prepared(project, tmp_path)
    saved = stage_source_update(project, candidate, review)
    store = project_store(project)
    before = store.snapshot()
    command = ProjectCommand.create("style", "fixture-no-project-byte-change", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={}, write_set=[], request={})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}))
    after = store.snapshot()
    assert after["generation"] != before["generation"] and after["files"] == before["files"]
    assert source_update.preview_project_source_update(project, source) == saved
    assert store.snapshot()["generation"] == after["generation"] and len(store.commands()) == 2


def test_source_preview_does_not_choose_between_multiple_exact_saved_intents(project, tmp_path, monkeypatch):
    from sciplot_core.project_store import source_trees

    candidate, source, review = prepared(project, tmp_path)
    first = stage_source_update(project, candidate, review)
    source.write_bytes(source.read_bytes() + b" a second confirmed version")
    second_review = {**review, "source_files": file_inventory(source), "source_tree_sha256": source_tree_sha256(source)}
    second = stage_source_update(project, candidate, second_review)
    assert first["command_key"] != second["command_key"]
    monkeypatch.setattr(source_trees, "observe", lambda *_a, **_k: pytest.fail("ambiguous previews guessed an incoming version"))
    result = source_update.preview_project_source_update(project, source)
    assert result["status"] == "blocked" and "multiple exact saved commands" in result["reason"]
    assert len(ProjectCommands(project_store(project)).commands()) == 2
