"""A real failed publication can be repaired without replaying scientific work."""

from pathlib import Path

import pytest

from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import active, load_head, read, transaction_path
from test_figure_document import request_for_figure


def failed_request(tmp_path):
    request = request_for_figure(tmp_path)
    spec = request["template_definition"]["figure_spec"]
    spec["layout"] = {}
    spec["views"][0]["panel_label"] = None
    spec["annotations"] = [{"id": "annotation:wide", "space": "view", "view_id": "view:A",
                            "x": .5, "y": .6, "text": "W" * 20, "visible": True, "style": {}}]
    return request


def width_patch(head, key="correct-width"):
    return {"plot_id": head["document"]["plot_id"], "base_revision": head["document"]["revision"],
            "idempotency_key": key, "intent_class": "presentation", "changes": [
                {"op": "set", "target": ["figure:main"], "property": "layout", "value": {"width_mm": 120}}]}


@pytest.mark.comprehensive
def test_real_qa_failure_width_patch_reviews_then_exports_without_science_reexecution(tmp_path, monkeypatch):
    from sciplot_core.plot_engine import managed_creation

    count = []
    resolve = managed_creation.resolve_science

    def once(*args, **kwargs):
        count.append(1)
        return resolve(*args, **kwargs)

    monkeypatch.setattr(managed_creation, "resolve_science", once)
    request = failed_request(tmp_path)
    source = Path(request["data_binding"]["data_sources"][0]["path"])
    raw = source.read_bytes()
    service = PlotService()
    try:
        failed = service.create(request)
        assert failed["status"] == "blocked" and failed["error"]["reason_code"] == "publication_qa_failed", failed
        root = Path(failed["plot"])
        before = load_head(root)
        old = active(root)
        old_evidence = {Path(item["diagnostic"]): Path(item["diagnostic"]).read_bytes() for item in old["failure_attempts"]}
        response = service.patch(root, width_patch(before))
        assert response["status"] == "needs_review" and response["ready_to_use"] is False, response
        assert response["scientific_hash"] == before["document"]["scientific_hash"]
        successor = active(root)
        frozen = read(transaction_path(root, old["request"]["idempotency_key"]))
        assert frozen["phase"] == old["phase"] and frozen["error"] == old["error"]
        assert frozen["superseded_by"]["id"] == successor["id"]
        assert {key: value for key, value in frozen.items() if key != "superseded_by"} == old
        old_key = {"plot_id": before["document"]["plot_id"], "base_revision": old["request"]["base_revision"],
                   "idempotency_key": old["request"]["idempotency_key"]}
        historical = service.resume(root, old_key)
        assert historical["historical"] and historical["ready_to_use"] is False
        assert active(root)["id"] == successor["id"]
        completed = service.decide(root, response["next_step"]["request"])
        assert completed["ready_to_use"] and completed["revision"] == 1
        assert completed["scientific_hash"] == before["document"]["scientific_hash"] and len(count) == 1
        assert load_head(root)["document"]["scientific"] == before["document"]["scientific"]
        assert source.read_bytes() == raw
        assert all(path.read_bytes() == content for path, content in old_evidence.items())
        current = active(root)["id"]
        assert service.resume(root, old_key)["historical"]
        assert active(root)["id"] == current
        assert all(Path(item["path"]).stat().st_size > 0 for item in completed["exports"])
    finally:
        service.close()


@pytest.mark.comprehensive
@pytest.mark.parametrize("control", ["unknown", "transient", "wrong_action", "nonempty_diff", "noop", "scientific", "source_drift", "native_external"])
def test_other_pending_states_and_nonpresentation_repairs_stay_blocked(tmp_path, control):
    from sciplot_core.plot_engine.errors import EngineError
    from sciplot_core.plot_engine.storage import persist

    request = failed_request(tmp_path)
    service = PlotService()
    try:
        failed = service.create(request)
        root = Path(failed["plot"])
        head, old = load_head(root), active(root)
        patch = width_patch(head)
        if control == "unknown":
            old["error"]["reason_code"] = "backend_failure"
        elif control == "transient":
            old["error"].update(reason_code="worker_timeout", action="retry_same_request")
        elif control == "wrong_action":
            old["error"]["action"] = "inspect_diagnostic"
        elif control == "nonempty_diff":
            old["diff"] = [{"risk": "presentation", "target": "figure:main"}]
        elif control == "noop":
            patch["changes"][0]["value"] = {}
        elif control == "scientific":
            patch.update(intent_class="scientific", changes=[{"op": "set", "target": ["scale:y"],
                         "property": "scale.domain", "value": [0, 25]}])
        elif control == "source_drift":
            source = Path(request["data_binding"]["data_sources"][0]["path"])
            source.write_bytes(source.read_bytes() + b"\nexternal drift")
        else:
            native = Path(head["binding"]["document"])
            native.write_bytes(b"unexpected native user state")
        persist(root, old)
        before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
        with pytest.raises(EngineError) as blocked:
            service.patch(root, patch)
        assert blocked.value.reason_code in {"document_transaction_pending", "document_inputs_changed", "managed_external_mutation"}
        assert not transaction_path(root, patch["idempotency_key"]).exists()
        assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    finally:
        service.close()


@pytest.mark.comprehensive
@pytest.mark.parametrize("window", ["candidate_saved", "old_link_saved"])
def test_interrupted_repair_reservation_resumes_exact_successor_without_old_execution(tmp_path, monkeypatch, window):
    from sciplot_core.plot_engine import publication_repair
    from test_plot_engine import SimulatedCrash

    service = PlotService()
    try:
        failed = service.create(failed_request(tmp_path))
        root = Path(failed["plot"])
        head, old = load_head(root), active(root)
        patch = width_patch(head)
        persist = publication_repair.persist

        def interrupted(path, transaction):
            persist(path, transaction)
            if window == "candidate_saved" and transaction.get("supersedes"):
                raise SimulatedCrash()
            if window == "old_link_saved" and transaction.get("superseded_by"):
                raise SimulatedCrash()

        monkeypatch.setattr(publication_repair, "persist", interrupted)
        with pytest.raises(SimulatedCrash):
            service.patch(root, patch)
        assert active(root)["id"] == old["id"]
        monkeypatch.setattr(publication_repair, "persist", persist)
        result = service.patch(root, patch)
        assert result["status"] == "needs_review", result
        assert active(root)["id"] != old["id"]
        old_key = {"plot_id": head["document"]["plot_id"], "base_revision": old["request"]["base_revision"],
                   "idempotency_key": old["request"]["idempotency_key"]}
        current = active(root)["id"]
        historical = service.resume(root, old_key)
        assert historical["historical"] and historical["ready_to_use"] is False
        assert active(root)["id"] == current and load_head(root) == head
        assert service.decide(root, result["next_step"]["request"])["ready_to_use"]
    finally:
        service.close()
