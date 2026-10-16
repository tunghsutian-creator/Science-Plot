"""Explicit recovery uses the existing journal and never invents a new edit."""

import json
from copy import deepcopy

import pytest
from test_plot_engine import FakeBackend, SimulatedCrash, request
from test_plot_typed_intent import _request
from test_plot_typed_intent_recovery import _engine

from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import commit, load_head


def _bound(document, key="edit-1", base=0):
    return {"plot_id": document["plot_id"], "idempotency_key": key, "base_revision": base}


def _legacy(tmp_path):
    backend = FakeBackend(tmp_path / "backend")
    document, binding = backend.initial()
    root = tmp_path / "plot"
    commit(root, document, binding, "import")
    return PlotService(backend), root, backend, document


def test_lost_review_summary_returns_frozen_decision_without_native_work(tmp_path):
    service, root, backend, document = _legacy(tmp_path)
    edit = request(changes=[{"op": "set", "target": ["title:main"], "property": "title.text", "value": "x" * 4096}])
    reviewed = service.patch(root, edit)
    assert reviewed["status"] == "needs_review"
    before = deepcopy(backend.calls)
    summary = service.describe(root)
    recovery = summary["recovery"]
    assert recovery["phase"] == "needs_review" and recovery["base_revision"] == 0
    assert recovery["current_revision"] == 0 and recovery["transaction_revision"] == 1
    assert recovery["preview"] == reviewed["preview"]
    assert recovery["scientific_audit"] == reviewed["scientific_audit"]
    assert summary["next_step"] == {**reviewed["next_step"], "plot": str(root)}
    assert len(json.dumps(recovery).encode()) < 2500
    assert all(backend.calls[name] == before[name] for name in ("preview", "apply", "export", "render"))
    resumed = service.resume(root, _bound(document))
    assert resumed["status"] == "needs_review" and backend.native_writes == 0
    complete = service.decide(root, summary["next_step"]["request"])
    assert complete["status"] == "complete" and complete["revision"] == 1
    assert service.resume(root, _bound(document))["replayed"] is True
    assert backend.native_writes == 1


@pytest.mark.parametrize("change,code", [
    ({"idempotency_key": "unknown"}, "document_transaction_unknown"),
    ({"plot_id": "wrong-plot"}, "document_identity_conflict"),
    ({"base_revision": 1}, "document_revision_conflict"),
    ({"base_revision": True}, "plot_invalid_resume"),
    ({"changes": []}, "plot_invalid_resume"),
])
def test_resume_binding_mismatch_never_reserves_or_applies(tmp_path, change, code):
    service, root, backend, document = _legacy(tmp_path)
    assert service.patch(root, request())["status"] == "complete"
    before = {str(path): path.read_bytes() for path in root.rglob("*.json")}
    writes = backend.native_writes
    with pytest.raises(ValueError) as failed:
        service.resume(root, {**_bound(document), **change})
    assert failed.value.reason_code == code
    assert backend.native_writes == writes
    assert {str(path): path.read_bytes() for path in root.rglob("*.json")} == before


@pytest.mark.parametrize("drift", ["source", "native"])
def test_review_recovery_refuses_drift_and_summary_cannot_offer_accept(tmp_path, drift):
    service, root, backend, document = _legacy(tmp_path)
    service.patch(root, request(changes=[{"op": "set", "target": ["title:main"], "property": "title.text", "value": "Reviewed"}]))
    path = backend.raw if drift == "source" else backend.native
    path.write_bytes(path.read_bytes() + b"external drift")
    summary = service.describe(root)
    assert summary["status"] == "stale" and summary["recovery"]["continuation_blocked"]
    assert summary["recovery"]["next_step"]["action"] == "resolve_changed_inputs"
    assert summary.get("next_step", {}).get("action") != "plot.decide"
    with pytest.raises(EngineError) as failed:
        service.resume(root, _bound(document))
    assert failed.value.reason_code == "document_inputs_changed"
    assert load_head(root)["document"]["revision"] == 0 and backend.native_writes == 0


def test_explicit_resume_recovers_uncertain_apply_once(tmp_path):
    service, root, backend, document = _legacy(tmp_path)
    backend.crash_after_apply = True
    with pytest.raises(SimulatedCrash):
        service.patch(root, request())
    assert backend.native_writes == 1 and load_head(root)["document"]["revision"] == 0
    complete = PlotService(backend).resume(root, _bound(document))
    assert complete["status"] == "complete" and complete["revision"] == 1
    assert backend.native_writes == 1
    assert complete["scientific_hash"] == document["scientific_hash"]


def test_explicit_resume_export_pending_preserves_committed_semantic_revision(tmp_path):
    service, root, backend, source, _ = _engine(tmp_path)
    document = load_head(root)["document"]
    source_bytes = source.read_bytes()
    backend.export_ready = False
    first = service.intent(root, _request(mode="apply"))
    assert first["status"] == "blocked" and first["commit_status"] == "committed"
    assert first["revision"] == 1 and backend.native_writes == 1
    backend.export_ready = True
    completed = service.resume(root, _bound(document, "same-key"))
    assert completed["status"] == "complete" and completed["revision"] == 1
    assert backend.native_writes == 1 and source.read_bytes() == source_bytes
    assert completed["scientific_hash"] == document["scientific_hash"]


@pytest.mark.parametrize("drift", ["source", "native"])
def test_uncertain_managed_resume_keeps_original_base_guards(tmp_path, monkeypatch, drift):
    service, root, backend, source, native = _engine(tmp_path)
    document = load_head(root)["document"]
    apply = backend.apply

    def crash_after_candidate(binding, review):
        apply(binding, review)
        raise SimulatedCrash()

    monkeypatch.setattr(backend, "apply", crash_after_candidate)
    with pytest.raises(SimulatedCrash):
        service.intent(root, _request(mode="apply"))
    monkeypatch.setattr(backend, "apply", apply)
    path = source if drift == "source" else native
    path.write_bytes(path.read_bytes() + b"external drift")
    result = service.resume(root, _bound(document, "same-key"))
    assert result["status"] == "blocked" and result["error"]["reason_code"] == "document_inputs_changed"
    assert load_head(root)["document"] == document and backend.native_writes == 1


def test_resume_of_historical_key_does_not_claim_current_delivery(tmp_path):
    service, root, backend, document = _legacy(tmp_path)
    service.patch(root, request())
    assert service.patch(root, request(key="later", revision=1, width="0.8pt"))["revision"] == 2
    writes = backend.native_writes
    result = service.resume(root, _bound(document))
    assert result["historical"] and result["ready_to_use"] is False and result["exports"] == []
    assert result["revision"] == 1 and result["current_revision"] == 2
    assert backend.native_writes == writes
