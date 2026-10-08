"""Complete managed presentation rollback retains its exact frozen scientific state."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.plot_document import seal_document
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine import execution
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.managed_rollback import presentation_diff, rollback_managed
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import active, commit, digest, load_head, read, transaction_path
from sciplot_core.plot_ir import apply_theme
from test_managed_external_mutation import _canonical
from test_plot_engine import FakeBackend, SimulatedCrash


class ManagedFixtureBackend(FakeBackend):
    """The managed transaction fake keeps the authoritative base file immutable."""

    def fingerprint(self, binding):
        self.calls["fingerprint"] += 1
        return {"files": {name: file_sha256(Path(name)) if Path(name).exists() else None
                          for name in binding["fingerprint"]["files"]}}

    def apply(self, binding, review):
        self.calls["apply"] += 1
        assert self.fingerprint(binding) == review["_expected"]["fingerprint"]
        content = digest(review["_document"]["presentation"]).encode()
        candidate = self.directory / (review["operation_id"] + ".vsz")
        if not candidate.exists():
            candidate.write_bytes(content)
            counter = self.directory / "native-writes.txt"
            counter.write_text(str(self.native_writes + 1))
        assert candidate.read_bytes() == content
        self.native = candidate
        return {"document": str(candidate), "native_sha256": file_sha256(candidate)}

    def refresh_binding(self, binding, applied):
        return {"fingerprint": {"files": {str(self.raw): file_sha256(self.raw),
                                          applied["document"]: applied["native_sha256"]}}}


def _history(tmp_path):
    root, original, _binding = _canonical(tmp_path)
    backend = ManagedFixtureBackend(tmp_path / "native")
    _doc, binding = backend.initial()
    commit(root, original, binding, "initial")
    themed = apply_theme(original, {"kind": "sciplot_theme", "schema_version": 1, "theme_id": "talk", "rules": [
        {"target": ["series:A", "series:B"], "property": "style.line.width", "value": "1.2pt"}]})
    themed["revision"] = 1
    commit(root, seal_document(themed), binding, "theme")
    edited = deepcopy(themed)
    edited["revision"] = 2
    edited["presentation"]["objects"]["series:A"]["properties"]["style.line.width"] = "1.4pt"
    commit(root, seal_document(edited), binding, "manual_style")
    return root, original, backend, {"base_revision": 2, "target_revision": 0, "idempotency_key": "restore-paper"}


def test_full_theme_and_manual_style_roll_back_once_through_shared_execution(tmp_path):
    root, original, backend, request = _history(tmp_path)
    before = load_head(root)
    review = rollback_managed(root, request, backend)
    assert review["status"] == "needs_review" and load_head(root) == before
    transaction = read(Path(review["evidence"]))
    assert transaction["rollback_request"] == request
    assert {item["property"] for item in transaction["diff"]} >= {"style.line.width", "theme"}
    assert rollback_managed(root, request, backend)["decision_id"] == review["decision_id"]
    result = PlotService(backend).decide(root, review["next_step"]["request"])
    restored = load_head(root)["document"]
    assert result["status"] == "complete" and restored["revision"] == 3
    assert restored["presentation"] == original["presentation"]
    assert restored["presentation_hash"] == original["presentation_hash"]
    assert restored["scientific_hash"] == original["scientific_hash"]
    assert backend.calls["preview"] == backend.calls["apply"] == backend.calls["export"] == 1
    assert rollback_managed(root, request, backend)["replayed"] is True
    assert backend.calls["apply"] == 1


@pytest.mark.parametrize("conflict", ["stale_revision", "scientific_source", "native", "pending"])
def test_rollback_conflicts_do_not_allocate_another_transaction(tmp_path, conflict):
    root, _original, backend, request = _history(tmp_path)
    if conflict == "stale_revision":
        request["base_revision"] = 1
    elif conflict == "scientific_source":
        source = Path(load_head(root)["document"]["scientific"]["data_sources"][0]["path"])
        source.write_text("changed source")
    elif conflict == "native":
        backend.native.write_text("changed native")
    else:
        rollback_managed(root, {**request, "idempotency_key": "another-review"}, backend)
    before = load_head(root)
    with pytest.raises(EngineError):
        rollback_managed(root, request, backend)
    assert not transaction_path(root, request["idempotency_key"]).exists()
    assert load_head(root) == before


def test_rejects_scientific_history_and_unsupported_target_before_reserving(tmp_path):
    root, original, backend, request = _history(tmp_path)
    current = deepcopy(load_head(root)["document"])
    current["revision"] = 3
    current["scientific"]["guards"]["different"] = True
    commit(root, seal_document(current), load_head(root)["binding"], "new_science")
    with pytest.raises(EngineError) as error:
        rollback_managed(root, {**request, "base_revision": 3}, backend)
    assert error.value.reason_code == "document_scientific_rollback_unsupported"
    assert not transaction_path(root, request["idempotency_key"]).exists()


def test_orphan_review_recovery_restores_pointer_without_new_native_preview(tmp_path, monkeypatch):
    root, _original, backend, request = _history(tmp_path)
    review = rollback_managed(root, request, backend)
    (root / "active.json").unlink()
    resumed = rollback_managed(root, request, backend)
    assert resumed["decision_id"] == review["decision_id"]
    assert active(root)["id"] == review["decision_id"] and backend.calls["preview"] == 1
    with pytest.raises(EngineError) as conflict:
        rollback_managed(root, {**request, "target_revision": 1}, backend)
    assert conflict.value.reason_code == "document_idempotency_conflict"


def test_interrupted_commit_restores_full_presentation_without_second_native_write(tmp_path, monkeypatch):
    root, original, backend, request = _history(tmp_path)
    review = rollback_managed(root, request, backend)
    actual_commit = execution.commit
    def interrupted(*args):
        actual_commit(*args)
        raise SimulatedCrash()
    monkeypatch.setattr(execution, "commit", interrupted)
    with pytest.raises(SimulatedCrash):
        PlotService(backend).decide(root, review["next_step"]["request"])
    monkeypatch.setattr(execution, "commit", actual_commit)
    result = rollback_managed(root, request, backend)
    assert result["status"] == "complete" and result["revision"] == 3
    assert load_head(root)["document"]["presentation"] == original["presentation"]
    assert backend.calls["apply"] == backend.native_writes == 1


def test_diff_retains_full_metadata_and_numeric_representation_changes():
    before = {"objects": {"axis:x": {"properties": {"axis.limits": [0, 1]}, "label": "X"}},
              "theme": {}, "layout": {}, "export_configuration": {"formats": ["pdf"]}}
    after = deepcopy(before)
    after["objects"]["axis:x"]["properties"]["axis.limits"] = [0.0, 1.0]
    after["objects"]["axis:x"]["label"] = "New label"
    after["layout"] = {"size": 60}
    after["export_configuration"] = {"formats": ["pdf", "tiff_300"]}
    assert {item["property"] for item in presentation_diff(before, after)} == {
        "axis.limits", "object.label", "layout", "export_configuration"}


def test_target_compile_failure_leaves_no_reserved_rollback(tmp_path, monkeypatch):
    from sciplot_core.plot_engine import managed_rollback

    root, _original, backend, request = _history(tmp_path)
    before = load_head(root)
    def reject(*_args):
        raise EngineError("managed_layout_invalid", "The target layout lacks a current compiler contract")
    monkeypatch.setattr(managed_rollback, "resolved_ir", reject)
    with pytest.raises(EngineError, match="layout"):
        rollback_managed(root, request, backend)
    assert load_head(root) == before and not transaction_path(root, request["idempotency_key"]).exists()


@pytest.mark.comprehensive
def test_real_managed_rollback_restores_full_template_after_theme_and_manual_style(tmp_path):
    from sciplot_core._paths import REPO_ROOT
    from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
    from sciplot_core.plot_engine.backend_router import BackendRouter
    from sciplot_core.plot_engine.managed_state import resolved_ir

    root, original, binding = _canonical(tmp_path)
    raw = {item["path"]: Path(item["path"]).read_bytes() for item in original["scientific"]["data_sources"]}
    commit(root, original, binding, "initial")
    router = BackendRouter(FakeBackend(tmp_path / "unused-legacy"))
    router.managed.compiler.close()
    router.managed.compiler = ManagedVeuszCompiler(warm=False)
    service = PlotService(router)
    try:
        assert service.export(root)["ready_to_use"] is True
        theme = {"kind": "sciplot_theme", "schema_version": 1, "theme_id": "talk", "rules": [
            {"target": ["series:A", "series:B"], "property": "style.line.width", "value": "1.2pt"}]}
        themed = service.patch(root, {"plot_id": original["plot_id"], "base_revision": 0,
            "idempotency_key": "theme-talk", "intent_class": "presentation", "changes": [
                {"op": "set", "target": ["figure:main"], "property": "theme", "value": theme}]})
        assert themed["status"] == "complete", themed
        edited = service.patch(root, {"plot_id": original["plot_id"], "base_revision": 1,
            "idempotency_key": "local-width", "intent_class": "presentation", "changes": [
                {"op": "set", "target": ["series:A"], "property": "style.line.width", "value": "1.4pt"}]})
        assert edited["status"] == "complete", edited
        request = {"base_revision": 2, "target_revision": 0, "idempotency_key": "restore-template"}
        review = rollback_managed(root, request, router)
        assert review["status"] == "needs_review", review
        restored = service.decide(root, review["next_step"]["request"])
        assert restored["status"] == "complete" and restored["revision"] == 3, restored
        head = load_head(root)
        assert head["document"]["presentation"] == original["presentation"]
        assert head["document"]["presentation_hash"] == original["presentation_hash"]
        assert head["document"]["scientific_hash"] == original["scientific_hash"]
        checked = router.managed.compiler.inspect_ir(resolved_ir(root, original), Path(head["binding"]["document"]))
        assert checked["status"] == "unchanged" and checked["scientific_audit"]["status"] == "passed"
        assert {path: Path(path).read_bytes() for path in raw} == raw
        replay = rollback_managed(root, request, router)
        assert replay["replayed"] and replay["revision"] == 3
        evidence = REPO_ROOT / ".tmp_verify/document_migration_20261007/managed_full_presentation_rollback.json"
        evidence.write_text(json.dumps({"status": "passed", "restored": restored,
            "full_presentation_restored": True, "native_state_matches_original_ir": True,
            "scientific_hash_unchanged": True, "source_bytes_unchanged": True, "idempotent_replay": True}, indent=2))
    finally:
        service.close()
