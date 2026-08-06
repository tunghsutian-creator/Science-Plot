from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from sciplot_gui import studio_project
from sciplot_gui import studio_project_status
from sciplot_gui.studio_project_status import qa_status as qa_status_module


class _Document:
    changeset = 7

    def isModified(self) -> bool:
        return False


def test_status_module_has_no_qt_import() -> None:
    module_path = Path(studio_project_status.__file__).resolve()
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert "PyQt6" not in imported_roots
    assert "veusz" not in imported_roots


def test_status_export_aliases_use_the_shared_contract() -> None:
    assert studio_project_status._normalized_export_format("png") == "png_300"
    assert studio_project_status._normalized_export_format("tif_300") == "tiff_300"
    assert studio_project_status._normalized_export_format("tiff300") == "tiff_300"
    assert studio_project_status._normalized_export_format("unknown") == ""


def test_workflow_never_reports_blocked_publish_evidence_as_ready() -> None:
    status = {
        "mode": "project",
        "document_scope": "project_primary",
        "document": {"modified": False},
        "qa": {
            "artifact_qa_current": True,
            "ready_to_use": False,
            "document_hash_current": True,
            "evidence": "runs/studio_001/manifest.json",
            "state": "needs_rule_repair",
        },
        "provenance": {
            "full_project_evidence_current": True,
            "project_delivery_current": True,
            "delivery_scope_known": True,
        },
    }

    workflow = studio_project_status._workflow_status(status)

    assert workflow == {
        "state": "needs_fix",
        "result_ready": False,
        "audit_state": "current",
        "message": "The current export or delivery needs review.",
    }
    status["qa"]["ready_to_use"] = True
    assert studio_project_status._workflow_status(status) == {
        "state": "ready",
        "result_ready": True,
        "audit_state": "current",
        "message": "Exact-current result artifacts are ready.",
    }


def test_managed_rule_readiness_reason_reaches_native_workflow_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reason = (
        "Material rule `swelling_curve` is currently `pending` and is not ready "
        "for production publication. Repair and revalidate the central rule, "
        "then reprepare this Studio project before handoff."
    )
    rule_readiness = {
        "kind": "sciplot_studio_rule_publication_readiness",
        "version": 1,
        "rule_id": "swelling_curve",
        "persisted_pending_rule_review": False,
        "current_rule_readiness": "pending",
        "pending_rule_review": True,
        "blockers": ["current_rule_not_ready"],
    }
    monkeypatch.setattr(
        qa_status_module,
        "_verify_export_artifacts",
        lambda **_kwargs: {
            "status": "passed",
            "current": True,
            "issues": [],
        },
    )
    qa = qa_status_module._qa_status(
        evidence={
            "qa": {"status": "passed"},
            "ready_to_use": False,
            "exported_document_hash": "document-sha",
            "state": "needs_rule_repair",
            "failure_stage": "rule_readiness_gate",
            "failure_reason": reason,
            "rule_readiness": rule_readiness,
        },
        evidence_path=tmp_path / "manifest.json",
        saved_sha256="document-sha",
        modified=False,
        standalone=False,
    )
    status = {
        "mode": "project",
        "document_scope": "project_primary",
        "document": {"modified": False},
        "qa": qa,
        "provenance": {
            "full_project_evidence_current": True,
            "project_delivery_current": True,
            "delivery_scope_known": True,
        },
    }

    assert qa["failure_stage"] == "rule_readiness_gate"
    assert qa["failure_reason"] == reason
    assert qa["rule_readiness"] == rule_readiness
    assert studio_project_status._workflow_status(status) == {
        "state": "needs_fix",
        "result_ready": False,
        "audit_state": "current",
        "message": f"Publication is blocked: {reason}",
    }
    status["workflow"] = studio_project_status._workflow_status(status)
    status["document"] = {
        "path": str(tmp_path / "document.vsz"),
        "modified": False,
        "revision": 1,
        "saved_sha256": "document-sha",
        "live_render_sha256": "render-sha",
    }
    status["source"] = {
        "status": "current",
        "audit_status": "passed",
        "path": str(tmp_path / "source.csv"),
        "sha256": "source-sha",
    }
    status["mapping"] = {
        "status": "current",
        "coverage_status": "complete",
    }
    assert f"Result: needs_fix — Publication is blocked: {reason}" in (
        studio_project_status._status_text(status)
    )

    qa["ready_to_use"] = True
    assert studio_project_status._workflow_status(status)["message"] == (
        "Exact-current result artifacts are ready."
    )


@pytest.mark.parametrize(
    ("mode", "document_scope"),
    [
        ("standalone_vsz", None),
        ("project", "project_secondary_standalone_receipt"),
    ],
)
def test_rule_readiness_reason_does_not_leak_into_standalone_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    document_scope: str,
) -> None:
    monkeypatch.setattr(
        qa_status_module,
        "_verify_export_artifacts",
        lambda **_kwargs: {
            "status": "passed",
            "current": True,
            "issues": [],
        },
    )
    monkeypatch.setattr(
        qa_status_module,
        "_standalone_qa_report_current",
        lambda **_kwargs: True,
    )
    qa = qa_status_module._qa_status(
        evidence={
            "artifact_qa": {"status": "passed"},
            "export_ready": False,
            "document_sha256": "document-sha",
            "failure_stage": "rule_readiness_gate",
            "failure_reason": "primary project reason must not leak",
        },
        evidence_path=tmp_path / "standalone_receipt.json",
        saved_sha256="document-sha",
        modified=False,
        standalone=True,
    )
    status: dict[str, Any] = {
        "mode": mode,
        "document": {"modified": False},
        "qa": qa,
        "provenance": {},
    }
    if document_scope is not None:
        status["document_scope"] = document_scope

    assert qa["failure_stage"] is None
    assert qa["failure_reason"] is None
    assert qa["rule_readiness"] is None
    assert studio_project_status._workflow_status(status)["message"] == (
        "The current export or delivery needs review."
    )
    qa["ready_to_use"] = True
    assert studio_project_status._workflow_status(status)["message"] == (
        "Exact-current result artifacts are ready."
    )


@pytest.mark.parametrize(
    ("stage", "reason"),
    [
        (1, "text"),
        ("rule_readiness_gate", ["not", "text"]),
        ("", "reason"),
        ("rule_readiness_gate", "   "),
    ],
)
def test_managed_failure_metadata_is_not_coerced_into_native_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: object,
    reason: object,
) -> None:
    monkeypatch.setattr(
        qa_status_module,
        "_verify_export_artifacts",
        lambda **_kwargs: {
            "status": "passed",
            "current": True,
            "issues": [],
        },
    )

    qa = qa_status_module._qa_status(
        evidence={
            "qa": {"status": "passed"},
            "ready_to_use": False,
            "exported_document_hash": "document-sha",
            "failure_stage": stage,
            "failure_reason": reason,
            "rule_readiness": {
                "pending_rule_review": True,
            },
        },
        evidence_path=tmp_path / "manifest.json",
        saved_sha256="document-sha",
        modified=False,
        standalone=False,
    )

    assert qa["failure_stage"] is None
    assert qa["failure_reason"] is None
    status = {
        "mode": "project",
        "document_scope": "project_primary",
        "document": {"modified": False},
        "qa": qa,
        "provenance": {
            "full_project_evidence_current": True,
            "project_delivery_current": True,
            "delivery_scope_known": True,
        },
    }
    assert studio_project_status._workflow_status(status)["message"] == (
        "The current export or delivery needs review."
    )


def test_qt_bridge_delegates_to_pure_status_builders(tmp_path: Path) -> None:
    document_path = tmp_path / "document.vsz"
    document_path.write_text("# minimal test document\n", encoding="utf-8")
    expected = studio_project_status.build_studio_project_status(
        document_path=document_path,
        document=_Document(),
        project_dir=None,
        request_path=None,
    )
    actual = studio_project.build_studio_project_status(
        document_path=document_path,
        document=_Document(),
        project_dir=None,
        request_path=None,
    )
    assert actual == expected
    assert studio_project.export_result_message is (
        studio_project_status.export_result_message
    )


def test_qt_bridge_injects_the_live_figure_scope_builder(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    project_dir = tmp_path / "project"
    document_path = project_dir / "studio" / "document.vsz"
    request_path = project_dir / "plot_request.json"
    document_path.parent.mkdir(parents=True)
    document_path.write_text("# minimal test document\n", encoding="utf-8")
    request_path.write_text(
        json.dumps({"input": "missing.csv"}),
        encoding="utf-8",
    )
    calls: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []

    def _resolver(
        *,
        project_dir: Path,
        request: dict[str, Any],
        latest_run: dict[str, Any],
    ) -> tuple[None, str]:
        calls.append((project_dir, request, latest_run))
        return None, "not_applicable"

    monkeypatch.setattr(
        studio_project,
        "_resolve_figure_set_export_scope",
        _resolver,
    )
    status = studio_project.build_studio_project_status(
        document_path=document_path,
        document=_Document(),
        project_dir=project_dir,
        request_path=request_path,
    )
    assert len(calls) == 1
    assert calls[0][0] == project_dir.resolve()
    assert status["provenance"]["figure_set_export_scope_status"] == ("not_applicable")
