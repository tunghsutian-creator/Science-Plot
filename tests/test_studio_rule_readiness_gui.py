from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from sciplot_gui import studio_project_status
from sciplot_gui.studio_project_status import qa_status as qa_status_module


_FULL_HASH = "a" * 64
_SEMANTIC_HASH = "b" * 64


def _current_binding() -> dict[str, Any]:
    return {
        "kind": "sciplot_studio_rule_contract_binding",
        "version": 1,
        "rule_id": "swelling_curve",
        "prepared_rule_contract_sha256": _FULL_HASH,
        "prepared_rule_semantic_contract_sha256": _SEMANTIC_HASH,
        "certification_status": "current",
        "certified_rule_contract_sha256": _FULL_HASH,
        "certified_rule_semantic_contract_sha256": _SEMANTIC_HASH,
        "certification_reasons": [],
    }


def _current_contract_snapshot() -> dict[str, Any]:
    return {
        "rule_id": "swelling_curve",
        "semantic_family": "rheology",
        "current_rule_contract_sha256": _FULL_HASH,
        "current_rule_semantic_contract_sha256": _SEMANTIC_HASH,
        "certified_rule_contract_sha256": _FULL_HASH,
        "certified_rule_semantic_contract_sha256": _SEMANTIC_HASH,
        "certified_semantic_family": "rheology",
        "certification_status": "current",
        "certification_reasons": [],
    }


def _v1_pending_readiness() -> dict[str, Any]:
    return {
        "kind": "sciplot_studio_rule_publication_readiness",
        "version": 1,
        "rule_id": "swelling_curve",
        "persisted_pending_rule_review": False,
        "current_rule_readiness": "pending",
        "pending_rule_review": True,
        "blockers": ["current_rule_not_ready"],
    }


def _v1_ready_rule_readiness() -> dict[str, Any]:
    return {
        "kind": "sciplot_studio_rule_publication_readiness",
        "version": 1,
        "rule_id": "swelling_curve",
        "persisted_pending_rule_review": False,
        "current_rule_readiness": "ready",
        "pending_rule_review": False,
        "blockers": [],
    }


def _v2_contract_blocked_readiness() -> dict[str, Any]:
    return {
        "kind": "sciplot_studio_rule_publication_readiness",
        "version": 2,
        "rule_id": "swelling_curve",
        "persisted_pending_rule_review": False,
        "current_rule_readiness": "ready",
        "pending_rule_review": False,
        "publication_blocked": True,
        "rule_contract_evidence": {
            "status": "blocked",
            "prepared": None,
            "current": _current_contract_snapshot(),
        },
        "blockers": ["prepared_rule_contract_binding_missing"],
    }


def _managed_qa(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    readiness: object,
    stage: object,
    reason: object,
    ready_to_use: bool = False,
) -> dict[str, Any]:
    monkeypatch.setattr(
        qa_status_module,
        "_verify_export_artifacts",
        lambda **_kwargs: {
            "status": "passed",
            "current": True,
            "issues": [],
        },
    )
    return qa_status_module._qa_status(
        evidence={
            "qa": {"status": "passed"},
            "ready_to_use": ready_to_use,
            "exported_document_hash": "document-sha",
            "state": "needs_rule_repair",
            "failure_stage": stage,
            "failure_reason": reason,
            "rule_readiness": readiness,
        },
        evidence_path=tmp_path / "manifest.json",
        saved_sha256="document-sha",
        modified=False,
        standalone=False,
    )


def _project_status(
    qa: dict[str, Any],
    *,
    document_scope: str = "project_primary",
) -> dict[str, Any]:
    return {
        "mode": "project",
        "document_scope": document_scope,
        "document": {"modified": False},
        "qa": qa,
        "provenance": {
            "full_project_evidence_current": True,
            "project_delivery_current": True,
            "delivery_scope_known": True,
        },
    }


def test_v2_contract_gate_reason_reaches_native_workflow_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reason = (
        "This rule-bearing Studio project has no prepare-time rule-contract "
        "binding. Reprepare it with the current certified rule before handoff."
    )
    readiness = _v2_contract_blocked_readiness()

    qa = _managed_qa(
        tmp_path,
        monkeypatch,
        readiness=readiness,
        stage="rule_contract_gate",
        reason=reason,
    )

    assert qa["rule_readiness"] == readiness
    assert studio_project_status._workflow_status(_project_status(qa)) == {
        "state": "needs_fix",
        "result_ready": False,
        "audit_state": "current",
        "message": f"Publication is blocked: {reason}",
    }


def test_v1_pending_rule_gate_remains_compatible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reason = "The current material rule still requires central review."
    readiness = _v1_pending_readiness()

    qa = _managed_qa(
        tmp_path,
        monkeypatch,
        readiness=readiness,
        stage="rule_readiness_gate",
        reason=reason,
    )

    assert qa["rule_readiness"] == readiness
    assert studio_project_status._workflow_status(_project_status(qa))["message"] == (
        f"Publication is blocked: {reason}"
    )


def test_v1_rule_bearing_ready_receipt_requires_fresh_v2_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qa = _managed_qa(
        tmp_path,
        monkeypatch,
        readiness=_v1_ready_rule_readiness(),
        stage=None,
        reason=None,
        ready_to_use=True,
    )

    assert qa["rule_readiness"] is None
    assert qa["ready_to_use"] is False
    assert (
        studio_project_status._workflow_status(_project_status(qa))["message"]
        == "The current export or delivery needs review."
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: {"pending_rule_review": True},
        lambda payload: {**payload, "kind": "unmanaged"},
        lambda payload: {**payload, "version": True},
        lambda payload: {**payload, "unsupported": "field"},
        lambda payload: {**payload, "publication_blocked": False},
        lambda payload: {
            **payload,
            "rule_contract_evidence": {
                **payload["rule_contract_evidence"],
                "unsupported": "field",
            },
        },
        lambda payload: {
            **payload,
            "rule_contract_evidence": {
                **payload["rule_contract_evidence"],
                "current": {
                    **payload["rule_contract_evidence"]["current"],
                    "certification_status": "missing",
                },
            },
        },
    ],
)
def test_malformed_managed_rule_evidence_is_not_copied_or_displayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutator: Any,
) -> None:
    malformed = mutator(deepcopy(_v2_contract_blocked_readiness()))

    qa = _managed_qa(
        tmp_path,
        monkeypatch,
        readiness=malformed,
        stage="rule_contract_gate",
        reason="must not be displayed",
    )

    assert qa["rule_readiness"] is None
    assert studio_project_status._workflow_status(_project_status(qa))["message"] == (
        "The current export or delivery needs review."
    )


@pytest.mark.parametrize(
    ("readiness", "stage"),
    [
        (_v1_pending_readiness(), "rule_contract_gate"),
        (_v2_contract_blocked_readiness(), "rule_readiness_gate"),
    ],
)
def test_managed_rule_reason_requires_the_matching_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    readiness: dict[str, Any],
    stage: str,
) -> None:
    qa = _managed_qa(
        tmp_path,
        monkeypatch,
        readiness=readiness,
        stage=stage,
        reason="mismatched managed gate",
    )

    assert qa["rule_readiness"] == readiness
    assert studio_project_status._workflow_status(_project_status(qa))["message"] == (
        "The current export or delivery needs review."
    )


def test_v2_rule_reason_does_not_leak_into_secondary_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qa = _managed_qa(
        tmp_path,
        monkeypatch,
        readiness=_v2_contract_blocked_readiness(),
        stage="rule_contract_gate",
        reason="primary project reason must not leak",
    )

    assert (
        studio_project_status._workflow_status(
            _project_status(
                qa,
                document_scope="project_secondary_standalone_receipt",
            )
        )["message"]
        == "The current export or delivery needs review."
    )
