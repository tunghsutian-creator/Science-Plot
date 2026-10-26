"""Genuine old pending files enter the new owner without repeating native effects."""
import json
from pathlib import Path

import pytest

from sciplot_core import rheology_tts_render as render
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.project_store import FileProjectStore, ProjectConflict, state
from sciplot_core.workflow import native_suite_transactions as native
from native_suite_legacy_fixture import legacy_case
from test_native_suite_project_commands import bound as bound


@pytest.fixture
def legacy(bound, monkeypatch):
    patch = render.patch_tts_display

    def audited_patch(path, candidate, figure, changes, expected):
        result = patch(path, candidate, figure, changes, expected)
        return {**result, "source_document": str(path), "source_document_sha256": expected,
            "baseline_audit": {"status": "passed", "document_sha256": expected},
            "candidate_audit": {"status": "passed", "document_sha256": result["document_sha256"],
                "changed_presentation": {"unrelated_native_state_unchanged": True}}}

    monkeypatch.setattr(render, "patch_tts_display", audited_patch)
    workspace, delivery, source, *_ = bound
    manifest = json.loads((workspace / "suite.json").read_bytes())
    return bound, (workspace, delivery, source, workspace / "A.spec.json", manifest)


@pytest.mark.parametrize("evidence_kind", ["applied", "intent"])
def test_complete_legacy_installed_publication_imports_once(legacy, monkeypatch, evidence_kind):
    bound, suite = legacy
    path, request, record, operation, installed = legacy_case(suite, monkeypatch, evidence_kind)
    historical = {item: item.read_bytes() for item in operation.parent.rglob("*") if item.is_file()}
    calls = []

    def audit(actual, figure):
        calls.append("audit")
        assert Path(actual).read_bytes() == path.read_bytes() and figure["id"] == "A"
        return {"status": "passed", "document": str(actual), "document_sha256": file_sha256(actual)}

    monkeypatch.setattr(render, "audit_tts_document", audit)
    monkeypatch.setattr(render, "patch_tts_display", lambda *a, **kw: pytest.fail("legacy import repeated native edit"))
    monkeypatch.setattr(render, "export_tts_document", lambda *a, **kw: pytest.fail("legacy import repeated native export"))
    decision = {"decision_id": record["decision_id"], "base_revision": request["base_revision"], "accept": False}
    with pytest.raises(EngineError, match="decision cannot be reversed"):
        native.decide_native(path, decision)
    resumed = native.resume_native(path, {key: request[key] for key in ("plot_id", "base_revision", "idempotency_key")})
    assert resumed["status"] == "complete" and resumed["accepted"] is True and resumed["ready_to_use"] is True
    assert calls == ["audit"] and bound[5] == ["patch", "export"]
    assert all(item.read_bytes() == data for item, data in historical.items())
    assert all(file_sha256(Path(name)) == sha for name, sha in installed.items())
    assert native.resume_native(path, {key: request[key] for key in ("plot_id", "base_revision", "idempotency_key")})["replayed"]
    assert calls == ["audit"] and bound[5] == ["patch", "export"]
    store = FileProjectStore(suite[0], locations={"delivery": suite[1]})
    records = store.commands()
    imported, = [item for item in records if item.get("review", {}).get("legacy_decision_id") == record["decision_id"]]
    assert imported["phase"] == "complete" and imported["write_set"] == []
    project_id = store.snapshot()["project_id"]
    # Legacy origins are admitted/audited first. Relocation then carries the
    # typed immutable outcome, never guesses a moved old hashed namespace.
    moved = FileProjectStore.import_bundle(store.export_bundle(suite[0].parent / "legacy-bundle"),
                                           suite[0].parent / "legacy-cold")
    old_paths = (suite[0], suite[1], suite[2])
    for old in old_paths:
        old.rename(old.with_name(old.name + ".offline"))
    current = moved.projection_path("@delivery/editable/A.vsz")
    replay = native.resume_native(current, {key: request[key] for key in ("plot_id", "base_revision", "idempotency_key")})
    assert replay["status"] == "complete" and replay["replayed"] and replay["ready_to_use"]
    copied, = [item for item in moved.commands() if item.get("review", {}).get("legacy_decision_id") == record["decision_id"]]
    assert copied["command_digest"] == imported["command_digest"] and copied["decision_id"] == imported["decision_id"]
    assert copied["generation"] == imported["generation"] and moved.snapshot()["project_id"] == project_id
    assert calls == ["audit"] and bound[5] == ["patch", "export"]
    assert all(not old.exists() for old in old_paths)


@pytest.mark.parametrize("accepted", [False, True])
def test_uninstalled_legacy_candidate_retains_decision_and_publishes_once(legacy, monkeypatch, accepted):
    bound, suite = legacy
    path, request, record, operation, before = legacy_case(suite, monkeypatch, "none", installed=False, accepted=accepted)
    history = {item: item.read_bytes() for item in operation.parent.rglob("*") if item.is_file()}
    audits = []

    def audit(actual, figure):
        audits.append(1)
        return {"status": "passed", "document": str(actual), "document_sha256": file_sha256(actual)}

    monkeypatch.setattr(render, "audit_tts_document", audit)
    monkeypatch.setattr(render, "patch_tts_display", lambda *a, **kw: pytest.fail("uninstalled legacy repeated edit"))
    monkeypatch.setattr(render, "export_tts_document", lambda *a, **kw: pytest.fail("uninstalled legacy repeated export"))
    resume = {key: request[key] for key in ("plot_id", "base_revision", "idempotency_key")}
    result = native.resume_native(path, resume)
    assert result["status"] == ("complete" if accepted else "needs_review")
    if not accepted:
        assert all(file_sha256(Path(name)) == sha for name, sha in before.items())
        result = native.decide_native(path, result["next_step"]["request"])
    assert result["status"] == "complete" and result["ready_to_use"] is True
    assert file_sha256(path) == record["presentation_hash"]
    assert audits == [1] and bound[5] == ["patch", "export"]
    assert all(item.read_bytes() == data for item, data in history.items())
    assert native.resume_native(path, resume)["replayed"] and audits == [1]


@pytest.mark.parametrize("fault", ["foreign_png", "traversal"])
def test_uninstalled_legacy_candidate_cannot_read_unadmitted_files(legacy, monkeypatch, fault):
    _bound, suite = legacy
    path, request, record, operation, before = legacy_case(suite, monkeypatch, "none", installed=False)
    foreign = suite[0].parent / "private-unadmitted.png"
    foreign.write_bytes(b"must never enter a native legacy import")
    if fault == "foreign_png":
        changed = json.loads(operation.read_bytes())
        changed["preview_png"] = str(foreign)
        operation.write_text(json.dumps(changed))
    else:
        preview_path = Path(record["preview"])
        preview = json.loads(preview_path.read_bytes())
        name = operation.parent / ".." / ".." / ".." / foreign.name
        preview["candidate_files"][str(name)] = file_sha256(foreign)
        preview_path.write_text(json.dumps(preview))
        (operation.parent / "preview.sha256").write_text(canonical_json_sha256(preview))
    opened = Path.open

    def reject_foreign(self, *args, **kwargs):
        if self.resolve() == foreign:
            pytest.fail("An uninstalled legacy candidate opened an unadmitted file.")
        return opened(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_foreign)
    monkeypatch.setattr(render, "audit_tts_document", lambda *a, **kw: pytest.fail("Invalid legacy must refuse before audit."))
    with pytest.raises(ValueError):
        native.resume_native(path, {key: request[key] for key in ("plot_id", "base_revision", "idempotency_key")})
    assert all(file_sha256(Path(name)) == sha for name, sha in before.items())


def test_legacy_evidence_drift_at_before_head_refuses_import(legacy, monkeypatch):
    bound, suite = legacy
    path, request, _record, operation, installed = legacy_case(suite, monkeypatch, "applied")
    head = (suite[0] / ".sciplot_store/head.json").read_bytes()
    monkeypatch.setattr(render, "audit_tts_document", lambda actual, figure: {
        "status": "passed", "document": str(actual), "document_sha256": file_sha256(actual)})
    boundary = state.boundary

    def drift(name):
        if name == "before_head":
            operation.write_bytes(b'{"foreign":"changed after audit and sealing"}')
        return boundary(name)

    monkeypatch.setattr(state, "boundary", drift)
    with pytest.raises(ProjectConflict, match="source changed before head publication"):
        native.resume_native(path, {key: request[key] for key in ("plot_id", "base_revision", "idempotency_key")})
    assert (suite[0] / ".sciplot_store/head.json").read_bytes() == head
    assert all(file_sha256(Path(name)) == sha for name, sha in installed.items())
    assert operation.read_bytes() == b'{"foreign":"changed after audit and sealing"}'
    assert bound[5] == ["patch", "export"]


@pytest.mark.parametrize("fault", ["intent_seal", "candidate", "foreign_native", "install_set", "mode", "science",
                                   "foreign_png", "operation_changed", "evidence_changed", "foreign_install", "candidate_traversal",
                                   "missing_seal", "rejected_flag", "malformed_map"])
def test_incomplete_or_foreign_legacy_publication_never_imports(legacy, monkeypatch, fault):
    bound, suite = legacy
    path, request, record, operation, _installed = legacy_case(suite, monkeypatch, "intent")
    store = FileProjectStore(suite[0], locations={"delivery": suite[1]})
    head = (suite[0] / ".sciplot_store/head.json").read_bytes()
    preview = json.loads(Path(record["preview"]).read_bytes())
    if fault == "intent_seal":
        (operation.parent / "publication_intents/exact.sha256").write_text("0" * 64)
    elif fault == "missing_seal":
        (operation.parent / "publication_intents/exact.sha256").unlink()
    elif fault == "rejected_flag":
        old = json.loads(operation.read_bytes())
        old["accepted"] = False
        operation.write_text(json.dumps(old))
    elif fault == "malformed_map":
        intent = operation.parent / "publication_intents/exact.json"
        evidence = json.loads(intent.read_bytes())
        evidence["published_files"] = []
        intent.write_text(json.dumps(evidence))
        intent.with_suffix(".sha256").write_text(canonical_json_sha256(evidence))
    elif fault == "candidate":
        Path(preview["candidates"][0]["export"]["document"]).write_bytes(b"unreviewed candidate")
    elif fault == "foreign_native":
        path.write_bytes(b"foreign current native authority")
    elif fault == "mode":
        path.chmod(0o400)
    elif fault in {"foreign_png", "foreign_install", "candidate_traversal"}:
        foreign = suite[0].parent / "unadmitted.png"
        foreign.write_bytes(b"unadmitted unrelated bytes")
        if fault == "foreign_png":
            old = json.loads(operation.read_bytes())
            old["preview_png"] = str(foreign)
            operation.write_text(json.dumps(old))
        else:
            intent = operation.parent / "publication_intents/exact.json"
            evidence = json.loads(intent.read_bytes())
            if fault == "foreign_install":
                evidence["published_files"][str(foreign)] = file_sha256(foreign)
            else:
                traversal = operation.parent / ".." / ".." / ".." / foreign.name
                assert traversal.resolve() == foreign
                preview["candidate_files"][str(traversal)] = file_sha256(foreign)
                Path(record["preview"]).write_text(json.dumps(preview))
                (operation.parent / "preview.sha256").write_text(canonical_json_sha256(preview))
                evidence["preview_sha256"] = canonical_json_sha256(preview)
            intent.write_text(json.dumps(evidence))
            intent.with_suffix(".sha256").write_text(canonical_json_sha256(evidence))
        read = Path.read_bytes
        opened = Path.open

        def forbid_unadmitted(self):
            if self.resolve() == foreign:
                pytest.fail("An arbitrary old preview_png must never be read.")
            return read(self)

        monkeypatch.setattr(Path, "read_bytes", forbid_unadmitted)

        def forbid_unadmitted_open(self, *args, **kwargs):
            if self.resolve() == foreign:
                pytest.fail("An unadmitted legacy file must never be opened.")
            return opened(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", forbid_unadmitted_open)
    elif fault == "install_set":
        intent = operation.parent / "publication_intents/exact.json"
        evidence = json.loads(intent.read_bytes())
        del evidence["published_files"][next(name for name in evidence["published_files"] if name.endswith(".pdf"))]
        intent.write_text(json.dumps(evidence))
        intent.with_suffix(".sha256").write_text(canonical_json_sha256(evidence))
    frozen = {item: (item.read_bytes(), item.stat().st_mode) for item in operation.parent.rglob("*") if item.is_file()}
    native_bytes, native_mode = path.read_bytes(), path.stat().st_mode
    def audit(actual, figure):
        if fault in {"operation_changed", "evidence_changed"}:
            changed = operation if fault == "operation_changed" else operation.parent / "publication_intents/exact.json"
            changed.write_bytes(b'{"concurrent":"foreign evidence"}')
            frozen[changed] = (changed.read_bytes(), changed.stat().st_mode)
        return {"status": "failed" if fault == "science" else "passed", "document": str(actual),
                "document_sha256": file_sha256(actual)}

    monkeypatch.setattr(render, "audit_tts_document", audit)
    monkeypatch.setattr(render, "patch_tts_display", lambda *a, **kw: pytest.fail("invalid legacy repeated edit"))
    monkeypatch.setattr(render, "export_tts_document", lambda *a, **kw: pytest.fail("invalid legacy repeated export"))
    with pytest.raises(ValueError):
        native.resume_native(path, {key: request[key] for key in ("plot_id", "base_revision", "idempotency_key")})
    assert (suite[0] / ".sciplot_store/head.json").read_bytes() == head
    assert path.read_bytes() == native_bytes and path.stat().st_mode == native_mode
    assert all(item.read_bytes() == data and item.stat().st_mode == mode for item, (data, mode) in frozen.items())
    assert bound[5] == ["patch", "export"]
    assert all(item.get("review", {}).get("legacy_decision_id") != record["decision_id"] for item in store.commands())
