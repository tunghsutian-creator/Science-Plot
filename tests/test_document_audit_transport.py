from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.source_coverage import document_audit as audit
from sciplot_core.studio_core import delivery_recovery


@pytest.fixture
def candidate(tmp_path):
    document, spec = tmp_path / "candidate.vsz", tmp_path / "spec.json"
    document.write_bytes(b"exact candidate bytes")
    spec.write_text('{"series":[]}')
    return document, spec


def evidence(document, spec, check_presentation=False):
    return {"kind": "sciplot_veusz_spec_data_audit", "version": 1, "status": "passed",
            "audit_scope": "generated_contract" if check_presentation else "current_scientific_data",
            "document": {"path": str(document.resolve()), "sha256": file_sha256(document)},
            "spec": {"path": str(spec.resolve()), "sha256": file_sha256(spec)},
            "units": [{"id": "curve"}], "unit_count": 1}


@pytest.mark.parametrize("in_process", [False, True])
def test_worker_and_in_process_audit_share_private_snapshots_and_identity_checks(candidate, monkeypatch, in_process):
    document, spec = candidate
    private = []
    def runner(audit_document, audit_spec, *, check_presentation):
        private.extend([audit_document, audit_spec])
        assert audit_document != document and audit_spec != spec
        assert audit_document.read_bytes() == document.read_bytes()
        assert audit_spec.read_bytes() == spec.read_bytes()
        assert audit_document.parent.stat().st_mode & 0o777 == 0o700
        return evidence(audit_document, audit_spec, check_presentation)
    def subprocess_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(runner(
            Path(command[4]), Path(command[5]), check_presentation=False)))
    monkeypatch.setattr(audit.subprocess, "run", subprocess_run)
    result, specification = audit._audit_exact_document_data(
        document_path=document, spec_path=spec, check_presentation=False,
        audit_runner=runner if in_process else None,
    )
    assert result == evidence(document, spec) and specification == {"series": []}
    assert all(not path.exists() for path in private)


def test_current_returned_audit_does_not_start_another_worker(candidate, monkeypatch):
    document, spec = candidate
    original = evidence(document, spec)
    monkeypatch.setattr(audit.subprocess, "run", lambda *a, **k: pytest.fail("redundant worker started"))
    result, _ = audit._audit_exact_document_data(
        document_path=document, spec_path=spec, check_presentation=False, native_audit=original,
    )
    assert result == original and result is not original


@pytest.mark.parametrize("fault", ["document_bytes", "spec_bytes", "document_path", "scope", "status", "units", "count"])
def test_stale_or_incomplete_inline_audit_cannot_pass(candidate, fault):
    document, spec = candidate
    report = evidence(document, spec)
    if fault == "document_bytes":
        document.write_bytes(b"changed after native audit")
    elif fault == "spec_bytes":
        spec.write_text('{"series":[],"changed":true}')
    elif fault == "document_path":
        report["document"]["path"] = str(document.with_name("other.vsz"))
    elif fault == "scope":
        report["audit_scope"] = "generated_contract"
    elif fault == "status":
        report["status"] = "failed"
    elif fault == "units":
        report["units"] = []
    else:
        report["unit_count"] = 2
    with pytest.raises(ValueError):
        audit._audit_exact_document_data(document_path=document, spec_path=spec,
                                         check_presentation=False, native_audit=report)


def test_in_process_audit_rejects_original_drift_while_reading_private_copy(candidate):
    document, spec = candidate
    def runner(private_document, private_spec, **kwargs):
        document.write_bytes(b"concurrent original save")
        assert private_document.read_bytes() == b"exact candidate bytes"
        return evidence(private_document, private_spec)
    with pytest.raises(ValueError, match="changed"):
        audit._audit_exact_document_data(document_path=document, spec_path=spec,
                                         check_presentation=False, audit_runner=runner)


def test_returned_native_audit_does_not_skip_prepared_source_verification(candidate, monkeypatch):
    document, spec = candidate
    source = spec.with_name("prepared.csv")
    source.write_text("x,y\n1,2\n")
    spec.write_text(json.dumps({"series": [{"source_artifacts": [
        {"path": str(source), "sha256": file_sha256(source)},
    ]}]}))
    calls = []
    def prepared(specification, snapshots):
        calls.append((specification, snapshots))
        raise ValueError("prepared scientific values changed")
    monkeypatch.setattr(delivery_recovery, "_verify_prepared_data", prepared)
    with pytest.raises(ValueError, match="prepared scientific values changed"):
        delivery_recovery._audit_candidate(document, spec, native_audit=evidence(document, spec))
    assert len(calls) == 1
