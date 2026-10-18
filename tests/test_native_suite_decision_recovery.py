"""Decisions are durable before publication and contradictory retries fail closed."""

import json
from pathlib import Path

import pytest

from sciplot_core import rheology_tts_render
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.workflow import native_suite_transactions as transactions
from sciplot_core.workflow import rheology_tts_style_update as style
from sciplot_core.workflow.native_suite_operations import (
    decide_native_object, describe_native_object, patch_native_object, resume_native_object,
)
from test_native_suite_operations import suite as suite, _accept, _request


@pytest.mark.comprehensive
@pytest.mark.parametrize("failure", ["before_publication", "completion_record"])
def test_accepted_decision_survives_failure_and_resumes_without_republication(suite, monkeypatch, failure):
    _workspace, _delivery, source, prepared, manifest = suite
    native = Path(manifest["documents"][0]["path"])
    described = describe_native_object(native, description={"scope": "summary"})
    request = _request(described, key="accepted-reply-loss")
    preview = patch_native_object(native, request)
    record_path = Path(preview["evidence"])
    before = file_sha256(native)
    source_before, plan_before = file_sha256(source), file_sha256(prepared)
    save, apply, publish = transactions.save_operation, style.apply_suite_style, style.publish_files
    publications = []

    def counted_publish(*args, **kwargs):
        publications.append(1)
        return publish(*args, **kwargs)

    monkeypatch.setattr(style, "publish_files", counted_publish)
    if failure == "before_publication":
        def fail_before(*_args, **_kwargs):
            raise OSError("controlled failure before publication")

        monkeypatch.setattr(style, "apply_suite_style", fail_before)
    else:
        def lose_completion(path, record):
            if record["phase"] == "complete":
                raise OSError("controlled loss after publication before completion record")
            return save(path, record)

        monkeypatch.setattr(transactions, "save_operation", lose_completion)
    with pytest.raises(OSError, match="controlled"):
        decide_native_object(native, _accept(preview))
    saved = json.loads(record_path.read_text())
    assert saved["accepted"] is True and saved["phase"] == "prepared"
    after = file_sha256(native)
    assert (after == before) is (failure == "before_publication")
    with pytest.raises(EngineError, match="different decision"):
        decide_native_object(native, {**_accept(preview), "accept": False})
    assert file_sha256(native) == after
    monkeypatch.setattr(transactions, "save_operation", save)
    monkeypatch.setattr(style, "apply_suite_style", apply)

    def forbidden(_payload):
        pytest.fail("Accepted recovery must use the saved exact candidate, without native execution.")

    monkeypatch.setattr(rheology_tts_render, "_dispatch", forbidden)
    result = resume_native_object(native, {key: request[key] for key in (
        "plot_id", "base_revision", "idempotency_key")})
    assert result["status"] == "complete" and result["ready_to_use"] is True
    assert len(publications) == 1
    assert decide_native_object(native, _accept(preview))["replayed"] is True
    with pytest.raises(EngineError, match="different decision"):
        decide_native_object(native, {**_accept(preview), "accept": False})
    assert file_sha256(source) == source_before and file_sha256(prepared) == plan_before


@pytest.mark.comprehensive
def test_failed_decision_write_does_not_mutate_and_allows_a_real_rejection(suite, monkeypatch):
    _workspace, _delivery, _source, _prepared, manifest = suite
    native = Path(manifest["documents"][0]["path"])
    described = describe_native_object(native, description={"scope": "summary"})
    preview = patch_native_object(native, _request(described, key="decision-write-failure"))
    before = file_sha256(native)
    save = transactions.save_operation

    def fail_decision(path, record):
        if record.get("accepted") is True:
            raise OSError("controlled durable decision write failure")
        return save(path, record)

    monkeypatch.setattr(transactions, "save_operation", fail_decision)
    with pytest.raises(OSError, match="decision write"):
        decide_native_object(native, _accept(preview))
    assert file_sha256(native) == before
    assert "accepted" not in json.loads(Path(preview["evidence"]).read_text())
    rejected = decide_native_object(native, {**_accept(preview), "accept": False})
    assert rejected["status"] == "rejected" and file_sha256(native) == before


@pytest.mark.comprehensive
@pytest.mark.parametrize("terminal", ["complete", "rejected"])
def test_older_terminal_records_replay_only_their_truthful_decision(suite, monkeypatch, terminal):
    _workspace, _delivery, _source, _prepared, manifest = suite
    native = Path(manifest["documents"][0]["path"])
    described = describe_native_object(native, description={"scope": "summary"})
    preview = patch_native_object(native, _request(described, key="legacy-terminal"))
    accepted = terminal == "complete"
    decision = {**_accept(preview), "accept": accepted}
    assert decide_native_object(native, decision)["status"] == terminal
    path = Path(preview["evidence"])
    record = json.loads(path.read_text())
    record.pop("accepted")
    path.write_text(json.dumps(record), encoding="utf-8")
    historical = path.read_bytes()

    def forbidden(_payload):
        pytest.fail("Legacy terminal receipt replay must not execute native work.")

    monkeypatch.setattr(rheology_tts_render, "_dispatch", forbidden)
    result = decide_native_object(native, decision)
    assert result["status"] == terminal and result["replayed"] is True
    with pytest.raises(EngineError, match="different decision"):
        decide_native_object(native, {**decision, "accept": not accepted})
    assert path.read_bytes() == historical


@pytest.mark.comprehensive
@pytest.mark.parametrize("evidence_kind", ["applied", "intent"])
def test_older_pending_publication_evidence_cannot_be_rejected_and_resumes(suite, monkeypatch, evidence_kind):
    _workspace, _delivery, _source, _prepared, manifest = suite
    native = Path(manifest["documents"][0]["path"])
    described = describe_native_object(native, description={"scope": "summary"})
    request = _request(described, key="legacy-pending-publication")
    preview = patch_native_object(native, request)
    path = Path(preview["evidence"])
    original = path.read_bytes()
    assert decide_native_object(native, _accept(preview))["status"] == "complete"
    installed = file_sha256(native)
    path.write_bytes(original)  # Model the older version's lost completion/decision record.
    if evidence_kind == "intent":
        (path.parent / "applied.json").unlink()

    def forbidden(*_args, **_kwargs):
        pytest.fail("Exact published legacy acceptance must not repeat native work or publication.")

    monkeypatch.setattr(rheology_tts_render, "_dispatch", forbidden)
    monkeypatch.setattr(style, "publish_files", forbidden)
    with pytest.raises(EngineError, match="different decision"):
        decide_native_object(native, {**_accept(preview), "accept": False})
    assert json.loads(path.read_text())["phase"] == "needs_review"
    result = resume_native_object(native, {key: request[key] for key in (
        "plot_id", "base_revision", "idempotency_key")})
    assert result["status"] == "complete" and result["accepted"] is True
    assert file_sha256(native) == installed
