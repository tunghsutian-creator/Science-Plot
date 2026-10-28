"""Real generation guards preserve display dependencies and sparse export facts."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_store import FileProjectStore, ProjectConflict, state
from sciplot_core.workflow import native_suite_transactions as native
from sciplot_core.workflow.rheology_tts_saved_state import _export_receipts
from sciplot_core.workflow.rheology_tts_style_update import apply_suite_style
from test_native_suite_project_commands import bound as bound, request
from test_rheology_tts_presentation_plan import _sealed_style_preview
from test_native_suite_decision_recovery import _assert_modern_pending_recovery


@pytest.mark.parametrize("with_plan", [False, True])
def test_display_intent_dependency_is_sealed_separately_from_scientific_sources(tmp_path, monkeypatch, with_plan):
    fixture, manifest, preview, external = _sealed_style_preview(tmp_path, monkeypatch, with_plan=with_plan)
    workspace, delivery, source, *_ = fixture
    store = FileProjectStore(workspace, locations={"delivery": delivery})
    record, = store.commands()
    before_sources = deepcopy(manifest["sources"])
    raw = source.read_bytes()
    if with_plan:
        binding = {"path": str(external), "sha256": file_sha256(external)}
        assert record["review"]["presentation_plan"] == binding
        assert any(entry["locator"] == binding["path"] and entry["sha256"] == binding["sha256"]
                   for versions in record["draft"]["sources"].values() for entry in versions.values())
    else:
        assert "presentation_plan" not in record["review"]
    result = apply_suite_style(workspace, Path(preview["preview"]))
    assert result["numerical_refit"] is False and result["exact_candidate_export"] is True
    assert json.loads((workspace / "suite.json").read_bytes())["sources"] == before_sources
    assert source.read_bytes() == raw and fixture[5] == ["export"]
    if external is not None:
        external.unlink()
    assert apply_suite_style(workspace, Path(preview["preview"]))["already_applied"] is True
    assert fixture[5] == ["export"]


def test_display_intent_drift_at_before_head_cannot_publish(tmp_path, monkeypatch):
    fixture, _manifest, preview, external = _sealed_style_preview(tmp_path, monkeypatch)
    workspace, delivery, source, documents, *_ = fixture
    head = (workspace / ".sciplot_store/head.json").read_bytes()
    protected = {path: path.read_bytes() for path in [source, workspace / "suite.json",
        delivery / "data/delivery_manifest.json", *(Path(item["path"]) for item in documents)]}
    boundary = state.boundary

    def drift(name):
        if name == "before_head":
            external.write_text("different display intent at publication")
        return boundary(name)

    monkeypatch.setattr(state, "boundary", drift)
    with pytest.raises(ProjectConflict, match="source changed before head publication"):
        apply_suite_style(workspace, Path(preview["preview"]))
    assert (workspace / ".sciplot_store/head.json").read_bytes() == head
    assert all(path.read_bytes() == data for path, data in protected.items())
    record, = FileProjectStore(workspace, locations={"delivery": delivery}).commands()
    assert record["phase"] == "accepted" and record["accepted"] is True
    assert fixture[5] == ["export"]


def test_foreign_native_save_before_head_cannot_mint_a_committed_revision(bound, monkeypatch):
    workspace, delivery, source, documents, _capture, calls, _export = bound
    path = Path(documents[0]["path"])
    req = request(bound)
    preview = native.patch_native(path, req)
    head = (workspace / ".sciplot_store/head.json").read_bytes()
    protected = {item: item.read_bytes() for item in [source, Path(documents[1]["path"]),
        workspace / "suite.json", delivery / "data/delivery_manifest.json",
        *(Path(name) for document in documents for name in document["exports"])]}
    foreign = b"foreign native save after review, before head"
    boundary = state.boundary

    def drift(name):
        if name == "before_head":
            path.write_bytes(foreign)
        return boundary(name)

    monkeypatch.setattr(state, "boundary", drift)
    with pytest.raises(ProjectConflict, match="Outside|changed|differs"):
        native.decide_native(path, preview["next_step"]["request"])
    assert path.read_bytes() == foreign
    assert (workspace / ".sciplot_store/head.json").read_bytes() == head
    assert all(item.read_bytes() == data for item, data in protected.items())
    records = FileProjectStore(workspace, locations={"delivery": delivery}).commands()
    assert len(records) == 2
    inspection, = [item for item in records
                   if item["metadata"]["request"]["adapter"] == "native_display_inspection"
                   and item["metadata"]["request"]["request"] == req]
    record, = [item for item in records
               if item["metadata"]["request"]["adapter"] == "native_display"
               and item["metadata"]["request"]["request"] == req]
    assert inspection["phase"] == "complete" and inspection["write_set"] == []
    assert record["metadata"]["request"]["inspection"] == inspection["command_digest"]
    assert record["expected_generation"] == inspection["generation"]
    assert record["phase"] == "accepted" and record["accepted"] is True
    assert record["result"]["presentation_hash"] != file_sha256(path)
    assert calls == ["patch", "export"]


def test_sparse_export_overlay_preserves_optional_and_explicit_pending_facts(bound):
    workspace, _delivery, _source, *_ = bound
    manifest = json.loads((workspace / "suite.json").read_bytes())
    original = deepcopy(manifest)
    pending = {**deepcopy(manifest["native_result"]["figures"][0]), "exports": []}
    manifest["last_export"] = [pending]
    receipts = _export_receipts(manifest)
    assert set(receipts) == {"A", "B"}
    assert receipts["A"] == pending and receipts["A"]["exports"] == []
    assert receipts["B"] == original["native_result"]["figures"][1]
    assert manifest["native_result"] == original["native_result"]


@pytest.mark.parametrize("evidence_kind", ["applied", "intent"])
def test_modern_pending_recovery_keeps_immutable_decision_and_single_publication(bound, monkeypatch, evidence_kind):
    workspace, delivery, source, *_ = bound
    manifest = json.loads((workspace / "suite.json").read_bytes())
    _assert_modern_pending_recovery((workspace, delivery, source, workspace / "A.spec.json", manifest), monkeypatch, evidence_kind)
