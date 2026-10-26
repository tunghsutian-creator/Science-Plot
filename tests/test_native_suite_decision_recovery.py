"""Decisions are durable before publication and contradictory retries fail closed."""

import json
from pathlib import Path

import pytest

from sciplot_core import rheology_tts_render
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.project_store import ProjectCommandConflict, state
from sciplot_core.workflow.native_suite_operations import (
    decide_native_object, describe_native_object, patch_native_object, resume_native_object,
)
from test_native_suite_operations import suite as suite, _accept, _request, _saved_command


@pytest.mark.comprehensive
@pytest.mark.parametrize("failure", ["before_publication", "completion_record"])
def test_accepted_decision_survives_failure_and_resumes_without_republication(suite, monkeypatch, failure):
    workspace, delivery, source, prepared, manifest = suite
    native = Path(manifest["documents"][0]["path"])
    described = describe_native_object(native, description={"scope": "summary"})
    request = _request(described, key="accepted-reply-loss")
    preview = patch_native_object(native, request)
    before = file_sha256(native)
    source_before, plan_before = file_sha256(source), file_sha256(prepared)
    boundary, save, publish = state.boundary, state.save_command, state.publish_head
    publications = []

    def counted_publish(*args, **kwargs):
        publications.append(1)
        return publish(*args, **kwargs)

    monkeypatch.setattr(state, "publish_head", counted_publish)
    def interrupt(name):
        if failure == "before_publication" and name == "before_head":
            raise OSError("controlled failure before head publication")
        return boundary(name)

    def lose_completion(io, record):
        if failure == "completion_record" and record["phase"] == "complete":
            raise OSError("controlled loss after publication before completion record")
        return save(io, record)

    monkeypatch.setattr(state, "boundary", interrupt)
    monkeypatch.setattr(state, "save_command", lose_completion)
    with pytest.raises(OSError, match="controlled"):
        decide_native_object(native, _accept(preview))
    saved = _saved_command(workspace, delivery, request)
    assert saved["accepted"] is True and saved["phase"] == "accepted"
    assert saved["decision_id"] == preview["next_step"]["request"]["decision_id"]
    after = file_sha256(native)
    assert (after == before) is (failure == "before_publication")
    monkeypatch.setattr(state, "boundary", boundary)
    monkeypatch.setattr(state, "save_command", save)
    with pytest.raises(ProjectCommandConflict, match="decision cannot be reversed"):
        decide_native_object(native, {**_accept(preview), "accept": False})
    assert file_sha256(native) == after

    def forbidden(_payload):
        pytest.fail("Accepted recovery must use the saved exact candidate, without native execution.")

    monkeypatch.setattr(rheology_tts_render, "_dispatch", forbidden)
    result = resume_native_object(native, {key: request[key] for key in (
        "plot_id", "base_revision", "idempotency_key")})
    assert result["status"] == "complete" and result["ready_to_use"] is True
    assert len(publications) == 1
    assert decide_native_object(native, _accept(preview))["replayed"] is True
    with pytest.raises(ProjectCommandConflict, match="decision cannot be reversed"):
        decide_native_object(native, {**_accept(preview), "accept": False})
    assert file_sha256(source) == source_before and file_sha256(prepared) == plan_before


@pytest.mark.comprehensive
def test_failed_decision_write_does_not_mutate_and_allows_a_real_rejection(suite, monkeypatch):
    workspace, delivery, _source, _prepared, manifest = suite
    native = Path(manifest["documents"][0]["path"])
    described = describe_native_object(native, description={"scope": "summary"})
    request = _request(described, key="decision-write-failure")
    preview = patch_native_object(native, request)
    before = file_sha256(native)
    save = state.save_command

    def fail_decision(io, record):
        if record.get("accepted") is True:
            raise OSError("controlled durable decision write failure")
        return save(io, record)

    monkeypatch.setattr(state, "save_command", fail_decision)
    with pytest.raises(OSError, match="decision write"):
        decide_native_object(native, _accept(preview))
    assert file_sha256(native) == before
    pending = _saved_command(workspace, delivery, request)
    assert "accepted" not in pending and pending["phase"] == "needs_review"
    rejected = decide_native_object(native, {**_accept(preview), "accept": False})
    assert rejected["status"] == "rejected" and file_sha256(native) == before


@pytest.mark.comprehensive
@pytest.mark.parametrize("terminal", ["complete", "rejected"])
def test_older_terminal_records_replay_only_their_truthful_decision(suite, monkeypatch, terminal):
    workspace, delivery, _source, _prepared, manifest = suite
    native = Path(manifest["documents"][0]["path"])
    described = describe_native_object(native, description={"scope": "summary"})
    request = _request(described, key="terminal-current")
    preview = patch_native_object(native, request)
    accepted = terminal == "complete"
    decision = {**_accept(preview), "accept": accepted}
    assert decide_native_object(native, decision)["status"] == terminal
    # Import a distinct genuine legacy receipt. Immutable new command evidence
    # must never be edited to simulate an older schema.
    from sciplot_core.workflow.native_suite_objects import require_object
    from sciplot_core.workflow.native_suite_storage import operation_path

    saved = _saved_command(workspace, delivery, request)
    legacy_request = {**request, "idempotency_key": "legacy-terminal"}
    record = {**saved["result"], "kind": "sciplot_native_display_operation", "version": 1,
              "request": legacy_request, "phase": terminal, "decision_id": "legacy-" + saved["decision_id"]}
    path = operation_path(require_object(native), legacy_request["idempotency_key"])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    decision = {"decision_id": record["decision_id"], "base_revision": request["base_revision"], "accept": accepted}
    historical = path.read_bytes()

    def forbidden(_payload):
        pytest.fail("Legacy terminal receipt replay must not execute native work.")

    monkeypatch.setattr(rheology_tts_render, "_dispatch", forbidden)
    result = decide_native_object(native, decision)
    assert result["status"] == terminal and result["replayed"] is True
    with pytest.raises(EngineError, match="decision cannot be reversed"):
        decide_native_object(native, {**decision, "accept": not accepted})
    assert path.read_bytes() == historical


@pytest.mark.comprehensive
@pytest.mark.parametrize("evidence_kind", ["applied", "intent"])
def test_older_pending_publication_evidence_cannot_be_rejected_and_resumes(suite, monkeypatch, evidence_kind):
    workspace, delivery, source, prepared, manifest = suite
    native = Path(manifest["documents"][0]["path"])
    described = describe_native_object(native, description={"scope": "summary"})
    request = _request(described, key="legacy-pending-publication")
    preview = patch_native_object(native, request)
    before = file_sha256(native)
    scientific = (file_sha256(source), file_sha256(prepared))
    boundary, save, publish = state.boundary, state.save_command, state.publish_head
    publications = []

    def counted_publish(*args, **kwargs):
        publications.append(1)
        return publish(*args, **kwargs)

    def interrupt(name):
        if evidence_kind == "intent" and name == "before_head":
            raise OSError("controlled durable " + evidence_kind)
        return boundary(name)

    def lose_completion(io, record):
        if evidence_kind == "applied" and record["phase"] == "complete":
            raise OSError("controlled durable " + evidence_kind)
        return save(io, record)

    monkeypatch.setattr(state, "publish_head", counted_publish)
    monkeypatch.setattr(state, "boundary", interrupt)
    monkeypatch.setattr(state, "save_command", lose_completion)
    with pytest.raises(OSError, match="controlled durable"):
        decide_native_object(native, _accept(preview))
    pending = _saved_command(workspace, delivery, request)
    assert pending["phase"] == "accepted" and pending["accepted"] is True
    assert (file_sha256(native) == before) is (evidence_kind == "intent")
    monkeypatch.setattr(state, "boundary", boundary)
    monkeypatch.setattr(state, "save_command", save)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Exact accepted recovery must not repeat native work.")

    monkeypatch.setattr(rheology_tts_render, "_dispatch", forbidden)
    with pytest.raises(ProjectCommandConflict, match="decision cannot be reversed"):
        decide_native_object(native, {**_accept(preview), "accept": False})
    assert _saved_command(workspace, delivery, request)["accepted"] is True
    result = resume_native_object(native, {key: request[key] for key in (
        "plot_id", "base_revision", "idempotency_key")})
    assert result["status"] == "complete" and result["accepted"] is True
    complete = _saved_command(workspace, delivery, request)
    assert complete["draft"] == pending["draft"] and complete["decision_id"] == pending["decision_id"]
    assert file_sha256(native) == complete["result"]["presentation_hash"] != before
    assert len(publications) == 1
    assert (file_sha256(source), file_sha256(prepared)) == scientific
