"""Fault injection for semantic transactions; fake native writes use real temp bytes."""

from copy import deepcopy
from pathlib import Path
from subprocess import TimeoutExpired

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import DocumentError, seal_document
from sciplot_core.plot_engine import execution
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import commit, digest, load_head, read, transaction_path, write


class SimulatedCrash(BaseException):
    """Bypass normal exception handling as an abruptly terminated process would."""


class FakeBackend:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(exist_ok=True)
        self.raw, self.native = directory / "raw.csv", directory / "document.vsz"
        for path, content in [(self.raw, b"x,y\n1,2\n2,3\n"), (self.native, b"original native state")]:
            if not path.exists():
                path.write_bytes(content)
        self.calls = {"fingerprint": 0, "preview": 0, "apply": 0, "export": 0, "render": 0}
        self.preview_failures = []
        self.export_failures = []
        self.audit = {"status": "passed", "coordinate_check": "passed"}
        self.crash_after_apply = False
        self.export_ready = True

    def initial(self):
        doc = seal_document({"kind": "sciplot_document", "schema_version": 1, "plot_id": "test-plot", "revision": 0,
            "scientific": {"data_sources": [{"path": str(self.raw), "sha256": file_sha256(self.raw)}],
                           "transforms": [], "mappings": {"x": "x", "y": "y"}, "guards": {}, "provenance": {}},
            "presentation": {"objects": {
                "series:E2": {"kind": "series", "label": "E2", "properties": {"style.line.width": "1pt"},
                              "capabilities": {"style.line.width": {"type": "physical_size", "risk": "presentation"}}},
                "title:main": {"kind": "title", "label": "Main title", "properties": {"title.visible": True, "title.text": "Measured data"},
                               "capabilities": {"title.visible": {"type": "boolean", "risk": "presentation"},
                                                "title.text": {"type": "string", "risk": "review"}}},
            }, "layout": {}, "theme": {}, "export_configuration": {"dpi": 300}},
            "coverage": {"mode": "legacy_shadow", "limitations": ["Fake backend only for transaction tests"]}})
        return doc, {"fingerprint": {"files": {str(self.raw): file_sha256(self.raw), str(self.native): file_sha256(self.native)}}}

    def import_project(self, project, figure_id=None, plot_id=None):
        return self.initial()

    def fingerprint(self, binding):
        self.calls["fingerprint"] += 1
        return {"files": {str(path): file_sha256(path) if path.exists() else None for path in (self.raw, self.native)}}

    def preview(self, document, binding, new_document, diff, output):
        self.calls["preview"] += 1
        if self.preview_failures:
            raise self.preview_failures.pop(0)
        output.mkdir(parents=True)
        image = output / "preview.png"
        image.write_bytes(b"fake preview pixels")
        return {"operation_id": digest([binding, new_document]), "scientific_audit": deepcopy(self.audit),
                "preview": {"path": str(image)}, "_document": new_document, "_expected": binding}

    def apply(self, binding, review):
        self.calls["apply"] += 1
        marker = self.directory / "native-commit.json"
        if marker.exists():
            prior = read(marker)
            if prior["operation_id"] == review["operation_id"]:
                assert file_sha256(self.native) == prior["native_sha256"]
                return prior
        assert self.fingerprint(binding) == review["_expected"]["fingerprint"]
        self.native.write_bytes(digest(review["_document"]["presentation"]).encode())
        counter = self.directory / "native-writes.txt"
        counter.write_text(str((int(counter.read_text()) if counter.exists() else 0) + 1))
        result = {"operation_id": review["operation_id"], "native_sha256": file_sha256(self.native)}
        write(marker, result)
        if self.crash_after_apply:
            self.crash_after_apply = False
            raise SimulatedCrash()
        return result

    def refresh_binding(self, binding, apply_result):
        result = deepcopy(binding)
        result["fingerprint"]["files"][str(self.native)] = apply_result["native_sha256"]
        assert self.fingerprint(result) == result["fingerprint"]
        return result

    def export(self, binding):
        self.calls["export"] += 1
        if self.export_failures:
            raise self.export_failures.pop(0)
        artifact = self.directory / "figure.pdf"
        artifact.write_bytes(b"fake native export " + self.native.read_bytes())
        return {"ready_to_use": self.export_ready, "exports": [{"path": str(artifact)}]}

    def render(self, binding, output):
        self.calls["render"] += 1
        output.mkdir(parents=True, exist_ok=True)
        image = output / "preview.png"
        image.write_bytes(b"fake preview pixels")
        return {"preview": {"path": str(image)}}

    @property
    def native_writes(self):
        path = self.directory / "native-writes.txt"
        return int(path.read_text()) if path.exists() else 0


@pytest.fixture
def engine(tmp_path):
    backend = FakeBackend(tmp_path / "backend")
    root = tmp_path / "plot"
    document, binding = backend.initial()
    commit(root, document, binding, "import")
    return PlotService(backend), root, backend


def request(key="edit-1", revision=0, width="0.7pt", changes=None):
    return {"plot_id": "test-plot", "base_revision": revision, "idempotency_key": key,
            "intent_class": "presentation", "changes": changes or [
                {"op": "set", "target": ["series:E2"], "property": "style.line.width", "value": width}]}


def test_safe_patch_automatically_commits_and_exports_once_with_science_preserved(engine):
    service, root, backend = engine
    before = load_head(root)["document"]
    result = service.patch(root, request())
    after = load_head(root)["document"]
    assert result["status"] == "complete" and result["ready_to_use"] is True
    assert result["revision"] == 1 and after["scientific_hash"] == before["scientific_hash"]
    assert backend.native_writes == 1 and backend.calls["preview"] == backend.calls["export"] == 1
    assert backend.raw.read_bytes() == b"x,y\n1,2\n2,3\n"


def test_same_key_replay_and_new_noop_skip_preview_apply_and_export(engine):
    service, root, backend = engine
    service.patch(root, request())
    counts = deepcopy(backend.calls)
    replayed = service.patch(root, request())
    noop = service.patch(root, request(key="noop", revision=1))
    assert replayed["replayed"] and noop["changed"] is False and noop["revision"] == 1
    assert all(backend.calls[name] == counts[name] for name in ("preview", "apply", "export"))


def test_same_key_changed_request_is_rejected_without_backend_work(engine):
    service, root, backend = engine
    service.patch(root, request())
    counts = deepcopy(backend.calls)
    with pytest.raises(EngineError) as error:
        service.patch(root, request(width="2pt"))
    assert error.value.reason_code == "document_idempotency_conflict" and backend.calls == counts


@pytest.mark.parametrize("bad_request,code", [
    (request(revision=7), "document_revision_conflict"),
    (request(changes=[{"op": "set", "target": ["series:E2"], "property": "mapping.x", "value": "y"}]),
     "document_scientific_edit_unsupported"),
])
def test_rejected_requests_have_no_journal_or_backend_work(engine, bad_request, code):
    service, root, backend = engine
    with pytest.raises(DocumentError) as error:
        service.patch(root, bad_request)
    assert error.value.reason_code == code and not (root / "transactions").exists()
    assert not any(backend.calls.values()) and backend.native_writes == 0


def test_source_bytes_change_invalidates_descendants_and_blocks_edits(engine):
    service, root, backend = engine
    original = load_head(root)["document"]
    backend.raw.write_bytes(b"x,y\n1,999\n")
    description = service.describe(root)
    assert description["status"] == "stale" and str(backend.raw) in description["changed_inputs"]
    assert {"compile", "render", "export"} <= set(description["dependencies"]["invalidated"])
    assert description["scientific_hash"] == original["scientific_hash"]
    with pytest.raises(EngineError) as error:
        service.patch(root, request())
    assert error.value.reason_code == "document_inputs_changed" and backend.native_writes == 0


@pytest.mark.parametrize("audit", [{}, {"status": "failed"}, {"status": "unknown"}])
def test_missing_or_failed_native_scientific_audit_cannot_auto_apply(engine, audit):
    service, root, backend = engine
    backend.audit = audit
    result = service.patch(root, request())
    assert result["status"] == "blocked" and result["error"]["reason_code"] == "document_scientific_audit_failed"
    assert result["next_step"]["action"] == "inspect_scientific_audit"
    assert backend.native_writes == 0 and backend.calls["export"] == 0 and load_head(root)["document"]["revision"] == 0


def test_risky_patch_requires_exact_review_decision_then_replays_without_mutation(engine):
    service, root, backend = engine
    changes = [{"op": "set", "target": ["title:main"], "property": "title.text", "value": "Updated interpretation"}]
    result = service.patch(root, request(changes=changes))
    assert result["status"] == "needs_review" and result["scientific_audit"]["status"] == "passed"
    assert Path(result["preview"]["path"]).is_file() and backend.native_writes == 0
    decision = result["next_step"]["request"]
    with pytest.raises(EngineError):
        service.decide(root, {**decision, "decision_id": "unrelated"})
    completed = service.decide(root, decision)
    replayed = service.decide(root, decision)
    assert completed["status"] == "complete" and replayed["replayed"] and backend.native_writes == 1


def test_rejected_preview_can_never_be_applied_by_resending_original_request(engine):
    service, root, backend = engine
    result = service.patch(root, request(width="1000pt"))
    decision = {**result["next_step"]["request"], "accept": False}
    assert service.decide(root, decision)["status"] == "rejected"
    assert service.patch(root, request(width="1000pt"))["status"] == "rejected"
    assert backend.native_writes == 0
    assert service.patch(root, request(key="new-request"))["status"] == "complete"


def test_crash_after_native_write_restarts_from_native_receipt_without_second_write(engine):
    service, root, backend = engine
    backend.crash_after_apply = True
    with pytest.raises(SimulatedCrash):
        service.patch(root, request())
    saved = read(transaction_path(root, "edit-1"))
    assert saved["phase"] == "applying" and load_head(root)["document"]["revision"] == 0
    restarted = FakeBackend(backend.directory)
    result = PlotService(restarted).patch(root, request())
    assert result["status"] == "complete" and result["revision"] == 1 and restarted.native_writes == 1
    assert restarted.calls["preview"] == 0


def test_crash_after_head_commit_does_not_create_another_revision(engine, monkeypatch):
    service, root, backend = engine
    original_commit = execution.commit

    def crash_after_commit(*args):
        original_commit(*args)
        raise SimulatedCrash()

    monkeypatch.setattr(execution, "commit", crash_after_commit)
    with pytest.raises(SimulatedCrash):
        service.patch(root, request())
    assert load_head(root)["document"]["revision"] == 1
    monkeypatch.setattr(execution, "commit", original_commit)
    assert service.patch(root, request())["status"] == "complete"
    assert backend.native_writes == 1 and len(list((root / "revisions").glob("*.json"))) == 2


def test_export_timeout_retries_locally_once_then_only_export_resumes(engine):
    service, root, backend = engine
    backend.export_failures = [TimeoutExpired("export", 1) for _ in range(3)]
    failed = service.patch(root, request())
    assert failed["commit_status"] == "committed" and failed["export_status"] == "pending"
    assert backend.calls["export"] == 2 and backend.native_writes == 1
    failed_again = service.patch(root, request())
    assert failed_again["status"] == "blocked" and backend.calls["export"] == 3
    completed = service.patch(root, request())
    assert completed["status"] == "complete" and backend.calls["export"] == 4 and backend.native_writes == 1
    assert read(transaction_path(root, "edit-1"))["retry_counts"] == {"export": 1}


def test_unknown_export_error_never_gets_automatic_retry(engine):
    service, root, backend = engine
    backend.export_failures = [RuntimeError("x" * 50000)]
    result = service.patch(root, request())
    assert backend.calls["export"] == 1 and result["status"] == "blocked"
    assert result["next_step"]["action"] == "inspect_diagnostic"
    assert len(str(result)) < 2300 and len(read(Path(result["error"]["diagnostic"]))["message"]) == 50000


def test_missing_artifact_reexports_current_revision_without_reapplying(engine):
    service, root, backend = engine
    first = service.patch(root, request())
    Path(first["exports"][0]["path"]).unlink()
    replayed = service.patch(root, request())
    assert replayed["status"] == "complete" and replayed["revision"] == 1
    assert backend.calls["export"] == 2 and backend.calls["preview"] == 1 and backend.native_writes == 1


def test_historical_replay_never_delivers_new_revision_bytes_as_old_receipt(engine):
    service, root, backend = engine
    service.patch(root, request())
    service.patch(root, request(key="edit-2", revision=1, width="2pt"))
    counts = deepcopy(backend.calls)
    historical = service.patch(root, request())
    assert historical["historical"] and not historical["ready_to_use"] and historical["exports"] == []
    assert historical["current_revision"] == 2 and historical["revision"] == 1 and backend.calls == counts


def test_completed_request_becomes_invalid_when_source_changes(engine):
    service, root, backend = engine
    service.patch(root, request())
    backend.raw.write_bytes(b"source replaced")
    with pytest.raises(EngineError) as error:
        service.patch(root, request())
    assert error.value.reason_code == "document_inputs_changed" and backend.native_writes == 1


def test_preview_timeout_gets_one_local_retry_without_rebuilding_scientific_state(engine):
    service, root, backend = engine
    backend.preview_failures = [TimeoutExpired("preview", 1)]
    assert service.patch(root, request())["status"] == "complete"
    assert backend.calls["preview"] == 2 and backend.native_writes == 1
    assert read(transaction_path(root, "edit-1"))["retry_counts"] == {"preview": 1}


def test_inventory_evidence_rejects_added_data_but_ignores_regular_finder_metadata(tmp_path):
    from sciplot_core.plot_engine.current import evidence_current

    delivery = tmp_path / "delivery"
    delivery.mkdir()
    figure = delivery / "figure.pdf"
    figure.write_bytes(b"delivered figure")
    files, inventories = {str(figure): file_sha256(figure)}, {str(delivery): ["figure.pdf"]}
    assert evidence_current(files, inventories)
    (delivery / ".DS_Store").write_bytes(b"finder")
    assert evidence_current(files, inventories)
    (delivery / "unexpected.csv").write_bytes(b"unverified data")
    assert not evidence_current(files, inventories)
    (delivery / "unexpected.csv").unlink()
    figure.unlink()
    figure.symlink_to(delivery / ".DS_Store")
    assert not evidence_current(files, inventories)


def test_large_review_audit_and_diff_remain_exact_in_journal_but_short_in_reply(engine):
    service, root, backend = engine
    backend.audit["full_diagnostics"] = "x" * 50000
    changes = [{"op": "set", "target": ["title:main"], "property": "title.text", "value": "a" * 3000}]
    result = service.patch(root, request(changes=changes))
    assert len(str(result)) < 2300 and result["diff_count"] == 1 and "diff" not in result
    assert result["scientific_hash_changed"] is False and result["presentation_hash_changed"] is True
    stored = read(Path(result["diff_evidence"]["path"]))
    assert stored["diff"][0]["after"] == "a" * 3000
    assert stored["review"]["scientific_audit"]["full_diagnostics"] == "x" * 50000


def test_migrated_typed_style_reuses_frozen_request_without_another_revision(engine, monkeypatch):
    from sciplot_core.plot_engine import compat

    service, root, backend = engine
    monkeypatch.setattr(compat, "PlotService", lambda: service)
    kwargs = {"samples": None, "all_samples": True, "style": {"width": "0.7pt"},
              "figure_id": None, "task_dir": root.parent / "typed-entry"}
    first = compat.migrated_style(root, **kwargs)
    replayed = compat.migrated_style(root, **kwargs)
    assert first["status"] == "complete" and replayed["replayed"]
    assert replayed["revision"] == 1 and backend.native_writes == 1 and backend.calls["preview"] == 1


def test_migrated_typed_style_rejects_different_intent_before_any_native_work(engine, monkeypatch):
    from sciplot_core.plot_engine import compat

    service, root, backend = engine
    monkeypatch.setattr(compat, "PlotService", lambda: service)
    kwargs = {"samples": ["E2"], "all_samples": False, "style": {"width": "0.7pt"},
              "figure_id": None, "task_dir": root.parent / "typed-entry"}
    compat.migrated_style(root, **kwargs)
    counts = deepcopy(backend.calls)
    with pytest.raises(EngineError) as error:
        compat.migrated_style(root, **{**kwargs, "style": {"width": "2pt"}})
    assert error.value.reason_code == "document_idempotency_conflict" and backend.calls == counts


def test_bad_native_preview_preserves_exact_correction_fields_in_short_reply(engine):
    service, root, backend = engine
    issues = [{"path": "/changes/0/value", "constraint": "native_color", "allowed": ["black", "#123456"]}]
    backend.preview_failures = [DocumentError("document_invalid_value", "Use a valid native color.", issues=issues)]
    result = service.patch(root, request())
    assert result["error"]["issues"] == issues and result["error"]["repair"]["action"] == "correct_patch"
    assert result["discard_request"]["accept"] is False and backend.native_writes == 0
    assert service.decide(root, result["discard_request"])["status"] == "rejected"
    assert service.patch(root, request(key="corrected"))["status"] == "complete"


def test_initial_import_snapshot_recovers_without_reimport_after_missing_head(engine, monkeypatch):
    from sciplot_core.plot_engine import service as service_module

    service, root, backend = engine
    original = load_head(root)["document"]
    (root / "head.json").unlink()
    monkeypatch.setattr(service_module, "resolve_project_figure", lambda *_: {"project": str(backend.directory), "figure_id": "primary"})
    monkeypatch.setattr(service_module, "document_root", lambda *_: root)
    monkeypatch.setattr(backend, "import_project", lambda *_: pytest.fail("The durable import snapshot must be reused"))
    recovered = service.open(backend.directory)
    assert recovered["status"] == "current" and recovered["plot_id"] == original["plot_id"]
    assert load_head(root)["document"] == original
