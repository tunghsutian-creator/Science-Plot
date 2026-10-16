"""Existing publication bytes are prerequisites, never a reason to re-export."""

import json
from pathlib import Path
from dataclasses import replace

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.figure_plan import FigureOutcome, FigureTask, ResolvedFigurePlan
from sciplot_core.publish_state import build_publish_state
from sciplot_core.studio_core.rule_readiness import resolve_studio_rule_publication_readiness
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_paper_publication import capture_publication, assert_publication_current


def _finalize(manifest):
    """Use the real publisher's rule and gate projections, not an implied pass."""
    readiness = resolve_studio_rule_publication_readiness(manifest["request"])
    rule = readiness.to_payload()
    projections = {"pending_rule_review": readiness.pending_rule_review,
                   "publication_rule_blocked": readiness.publication_blocked,
                   "autonomous_rule_ready": not readiness.publication_blocked,
                   "rule_readiness": rule}
    manifest.update(projections)
    manifest["result"].update(projections)
    manifest["semantic"] = {"studio_rule_publication_readiness": rule,
                            "publication_rule_ready": not readiness.publication_blocked}
    manifest.update(build_publish_state(
        qa=manifest["qa"], package_contract=manifest["package_contract"],
        delivery_package=manifest["delivery_package"], delivery_verification=manifest["delivery_verification"],
        prerequisite_state="needs_rule_repair" if readiness.publication_blocked else None,
        resolved_figure_plan=manifest.get("resolved_figure_plan")))
    manifest["publish_complete"] = True
    manifest["failure_stage"] = None if manifest["ready_to_use"] else (
        "rule_readiness_gate" if readiness.pending_rule_review else
        "rule_contract_gate" if readiness.publication_blocked else "quality_or_delivery_gate")
    manifest["failure_reason"] = None if manifest["ready_to_use"] else "The original publication remains blocked."


@pytest.fixture
def publication(tmp_path):
    project = tmp_path / "project"
    studio = project / "studio"
    run = project / "runs/studio_1"
    (run / "studio").mkdir(parents=True)
    studio.mkdir()
    request = {"input": str(tmp_path / "raw.csv")}
    for path, value in ((project / "plot_request.json", request), (run / "request_snapshot.json", request)):
        path.write_text(json.dumps(value))
    for folder in (studio, run / "studio"):
        (folder / "document.vsz").write_bytes(b"sealed native fixture; not a scientific acceptance")
        (folder / "spec.json").write_text(json.dumps({"series": []}))
    exports, qa = [], {"status": "passed", "pdfs": [], "tiffs": []}
    for fmt, suffix, key in (("pdf", ".pdf", "pdfs"), ("tiff_300", "_300dpi.tiff", "tiffs")):
        path = run / ("figure" + suffix)
        path.write_bytes(b"audited fixture " + fmt.encode())
        record = {"path": str(path), "sha256": file_sha256(path)}
        exports.append({**record, "format": fmt, "document": str(run / "studio/document.vsz")})
        qa[key].append(record)
    manifest = {"request": request, "qa": qa, "result": {"exports": exports},
                "veusz_document_hashes": {str(run / "studio/document.vsz"): file_sha256(studio / "document.vsz")}}
    task = FigureTask(figure_id="primary", order=1, title="Fixture", x_metric="x", y_metric="y",
                      template="point_line", artifact_stem="figure", document_stem="document")
    manifest["resolved_figure_plan"] = ResolvedFigurePlan(
        rule_id="fixture", selection_policy="fixture", primary_figure_id="primary", tasks=(task,),
        outcomes=(FigureOutcome(figure_id="primary", status="ready", artifacts=(
            str(run / "studio/document.vsz"), str(run / "figure.pdf"), str(run / "figure_300dpi.tiff"))),)).to_payload()
    manifest.update(package_contract={"complete": True}, delivery_package={"complete": True},
                    delivery_verification={"passed": True})
    _finalize(manifest)
    assert manifest["ready_to_use"] is True
    (run / "manifest.json").write_text(json.dumps(manifest))
    selected = {"project": str(project), "figure_id": "primary", "document": str(studio / "document.vsz"),
                "version": {"document_sha256": file_sha256(studio / "document.vsz")}}
    return selected, run


def test_capture_sealed_export_identity_and_full_original_inventory(publication):
    selected, run = publication
    before = {str(path): path.read_bytes() for path in run.rglob("*") if path.is_file()}
    captured = capture_publication(selected)
    assert [record["format"] for record in captured["exports"]] == ["pdf", "tiff_300"]
    assert captured["qa"]["scope"] == "existing_current_sealed_publication"
    assert_publication_current(captured, selected)
    assert before == {str(path): path.read_bytes() for path in run.rglob("*") if path.is_file()}


@pytest.mark.parametrize("change", ["missing_pdf", "edited_pdf", "native", "spec", "request", "qa_failed", "new_file"])
def test_unsealed_or_drifted_publication_blocks_without_repair(publication, change):
    selected, run = publication
    captured = capture_publication(selected)
    if change == "missing_pdf":
        (run / "figure.pdf").unlink()
    elif change == "edited_pdf":
        (run / "figure.pdf").write_bytes(b"external edited publication")
    elif change in {"native", "spec"}:
        (Path(selected["project"]) / "studio" / ("document.vsz" if change == "native" else "spec.json")).write_bytes(b"user changed original")
    elif change == "request":
        (Path(selected["project"]) / "plot_request.json").write_text(json.dumps({"revision": 2}))
    elif change == "qa_failed":
        path = run / "manifest.json"
        value = json.loads(path.read_text())
        value["qa"]["status"] = "failed"
        path.write_text(json.dumps(value))
    else:
        (run / "unrecorded.txt").write_bytes(b"preserve this file")
    before = {str(path): path.read_bytes() for path in Path(selected["project"]).rglob("*") if path.is_file()}
    with pytest.raises(TaskControlError):
        assert_publication_current(captured, selected)
    assert before == {str(path): path.read_bytes() for path in Path(selected["project"]).rglob("*") if path.is_file()}


@pytest.mark.parametrize("change", [
    "publishing", "incomplete", "missing_complete", "nonboolean_complete", "not_ready", "missing_ready",
    "unknown_state", "failure_stage", "failure_reason", "missing_failure_stage", "missing_failure_reason",
    "missing_gates", "contradictory_gates",
    "package_blocked", "delivery_blocked", "verification_blocked", "missing_verification",
    "incomplete_plan", "forged_delivery_ready", "manifest_rule_flag", "result_rule_flag", "semantic_rule_flag",
    "missing_rule_evidence", "unknown_rule",
])
def test_qa_passed_but_unfinished_or_contradictory_publication_never_seals(publication, change):
    selected, run = publication
    path = run / "manifest.json"
    manifest = json.loads(path.read_bytes())
    if change == "publishing":
        manifest.update(state="publishing", ready_to_use=False, publish_complete=False)
        manifest.pop("publish_gates")
    elif change in {"incomplete", "missing_complete", "nonboolean_complete"}:
        if change == "missing_complete":
            manifest.pop("publish_complete")
        else:
            manifest["publish_complete"] = False if change == "incomplete" else "true"
    elif change in {"not_ready", "missing_ready"}:
        if change == "missing_ready":
            manifest.pop("ready_to_use")
        else:
            manifest["ready_to_use"] = False
    elif change == "unknown_state":
        manifest["state"] = "unknown"
    elif change in {"failure_stage", "failure_reason"}:
        manifest[change] = "An original publication gate failed."
    elif change in {"missing_failure_stage", "missing_failure_reason"}:
        manifest.pop(change.removeprefix("missing_"))
    elif change == "missing_gates":
        manifest.pop("publish_gates")
    elif change == "contradictory_gates":
        manifest["publish_gates"]["gates"]["package_contract_complete"] = False
    elif change in {"package_blocked", "delivery_blocked", "verification_blocked", "incomplete_plan"}:
        if change == "incomplete_plan":
            manifest["resolved_figure_plan"] = {"kind": "incomplete_plan"}
        else:
            field, flag = {"package_blocked": ("package_contract", "complete"),
                           "delivery_blocked": ("delivery_package", "complete"),
                           "verification_blocked": ("delivery_verification", "passed")}[change]
            manifest[field][flag] = False
        _finalize(manifest)
        assert manifest["ready_to_use"] is False
    elif change == "missing_verification":
        manifest.pop("delivery_verification")
    elif change == "forged_delivery_ready":
        manifest["delivery_package"]["complete"] = False  # Stored ready/gates still claim success.
    elif change in {"manifest_rule_flag", "result_rule_flag"}:
        record = manifest if change == "manifest_rule_flag" else manifest["result"]
        record["publication_rule_blocked"] = True
    elif change == "semantic_rule_flag":
        manifest["semantic"]["publication_rule_ready"] = False
    elif change == "missing_rule_evidence":
        manifest.pop("rule_readiness")
    else:
        request = {**manifest["request"], "rule_id": "unknown_figure_rule"}
        manifest["request"] = request
        for request_path in (Path(selected["project"]) / "plot_request.json", run / "request_snapshot.json"):
            request_path.write_text(json.dumps(request))
    assert manifest["qa"]["status"] == "passed"
    path.write_text(json.dumps(manifest))
    before = {str(p): p.read_bytes() for p in Path(selected["project"]).rglob("*") if p.is_file()}
    with pytest.raises(TaskControlError) as caught:
        capture_publication(selected)
    assert caught.value.reason_code == "paper_publication_unsealed"
    assert before == {str(p): p.read_bytes() for p in Path(selected["project"]).rglob("*") if p.is_file()}


@pytest.mark.parametrize("rule_case", ["pending_review", "unbound_rule_contract"])
def test_canonical_rule_blocker_survives_passed_qa_and_finished_publication(publication, rule_case):
    selected, run = publication
    path = run / "manifest.json"
    manifest = json.loads(path.read_bytes())
    request = {**manifest["request"], **({"pending_rule_review": True} if rule_case == "pending_review"
                                      else {"rule_id": "rheology_stress_relaxation"})}
    manifest["request"] = request
    for request_path in (Path(selected["project"]) / "plot_request.json", run / "request_snapshot.json"):
        request_path.write_text(json.dumps(request))
    _finalize(manifest)
    assert manifest["publish_complete"] is True and manifest["qa"]["status"] == "passed"
    assert manifest["publication_rule_blocked"] is True and manifest["ready_to_use"] is False
    assert manifest["failure_stage"] == ("rule_readiness_gate" if rule_case == "pending_review" else "rule_contract_gate")
    path.write_text(json.dumps(manifest))
    before = {str(p): p.read_bytes() for p in Path(selected["project"]).rglob("*") if p.is_file()}
    with pytest.raises(TaskControlError, match="complete current sealed publication"):
        capture_publication(selected)
    assert before == {str(p): p.read_bytes() for p in Path(selected["project"]).rglob("*") if p.is_file()}


def test_replay_checks_current_canonical_rule_without_changing_original_bytes(publication, monkeypatch):
    selected, run = publication
    captured = capture_publication(selected)
    original = resolve_studio_rule_publication_readiness(json.loads((run / "manifest.json").read_bytes())["request"])
    blocked = replace(original, publication_blocked=True, blockers=("current_rule_certification_stale",))
    monkeypatch.setattr("sciplot_core.task_paper_publication.resolve_studio_rule_publication_readiness", lambda _: blocked)
    before = {str(p): p.read_bytes() for p in Path(selected["project"]).rglob("*") if p.is_file()}
    with pytest.raises(TaskControlError):
        assert_publication_current(captured, selected)
    assert before == {str(p): p.read_bytes() for p in Path(selected["project"]).rglob("*") if p.is_file()}
