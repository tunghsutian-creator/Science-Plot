"""Exercise one rule template through exact-current Studio export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sciplot_core.materials_rules import SemanticRule
from sciplot_core.readiness import (
    rule_contract_sha256,
    rule_semantic_contract_sha256,
    semantic_contract_sha256,
)
from sciplot_core.studio import (
    export_studio_document,
    prepare_studio_document,
    publish_studio_export_run,
)

from sciplot_core.acceptance.fixtures import (
    RULE_ACCEPTANCE_CHECK_IDS,
)

from sciplot_core.acceptance.rule_matrix import (
    _delivery_artifact_passed,
    _manual_edit_probe,
)


def _run_rule_template_acceptance(
    rule: SemanticRule,
    *,
    template: str,
    fixture: Path,
    projects_root: Path,
) -> dict[str, Any]:
    try:
        prepared = prepare_studio_document(
            fixture,
            output_root=projects_root,
            project_name=f"{rule.rule_id} {template} acceptance",
            rule_id=rule.rule_id,
            template=template,
        )
        project_dir = Path(str(prepared["project_dir"]))
        request_path = Path(str(prepared["request"]))
        document_path = Path(str(prepared["document"]))
        marker = _manual_edit_probe(
            document_path,
            rule_id=f"{rule.rule_id}:{template}",
        )
        export_payload = export_studio_document(
            document_path,
            formats=["pdf", "tiff_300"],
        )
        exports = export_payload["exports"]
        studio_run = publish_studio_export_run(
            project_dir=project_dir,
            request_path=request_path,
            document_path=document_path,
            exports=exports,
            export_document_sha256=str(export_payload["document_sha256"]),
        )
        manifest_path = Path(str(studio_run["manifest"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        semantic = (
            manifest.get("semantic")
            if isinstance(manifest.get("semantic"), dict)
            else {}
        )
        accepted_semantic_contract_sha256 = semantic_contract_sha256(semantic)
        current_semantic_contract_sha256 = rule_semantic_contract_sha256(rule)
        current_rule_contract_sha256 = rule_contract_sha256(rule)
        transform = (
            manifest.get("transform_ledger")
            if isinstance(manifest.get("transform_ledger"), dict)
            else {}
        )
        publication_intent = (
            manifest.get("publication_intent")
            if isinstance(manifest.get("publication_intent"), dict)
            else {}
        )
        delivery = (
            manifest.get("delivery_package")
            if isinstance(manifest.get("delivery_package"), dict)
            else {}
        )
        editable_vsz = (
            delivery.get("editable_vsz")
            if isinstance(delivery.get("editable_vsz"), dict)
            else {}
        )
        editable_path = (
            Path(str(editable_vsz.get("path"))) if editable_vsz.get("path") else None
        )
        manual_edit_preserved = bool(
            manifest.get("manual_edit_detected") is True
            and marker in document_path.read_text(encoding="utf-8")
            and editable_path is not None
            and editable_path.exists()
            and marker in editable_path.read_text(encoding="utf-8")
            and editable_vsz.get("hash_matches_export") is True
        )
        exported_formats = {
            str(item.get("format")) for item in exports if isinstance(item, dict)
        }
        checks = {
            "semantic_rule_selected": semantic.get("rule_id") == rule.rule_id,
            "validated_rule_contract_current": (
                accepted_semantic_contract_sha256 == current_semantic_contract_sha256
                and rule_contract_sha256(rule) == current_rule_contract_sha256
            ),
            "vsz_reopen_export": document_path.exists()
            and prepared.get("series_count", 0) > 0
            and {"pdf", "tiff_300"} <= exported_formats,
            "manual_edit_preserved": manual_edit_preserved,
            "canonical_pdf_tiff_pair": _delivery_artifact_passed(
                delivery, "canonical_pdf_tiff_pairs"
            ),
            "qa_passed": manifest.get("qa", {}).get("status") == "passed",
            "delivery_complete": delivery.get("complete") is True,
            "provenance_complete": bool(
                semantic.get("rule_id") == rule.rule_id
                and transform.get("status") == "runtime_recorded"
                and publication_intent.get("kind") == "sciplot_publication_intent"
                and manifest.get("raw_archive", {}).get("path")
            ),
        }
        return {
            "template": template,
            "lifecycle_status": "passed" if all(checks.values()) else "failed",
            "checks": checks,
            "rule_contract_sha256": current_rule_contract_sha256,
            "accepted_rule_contract_sha256": current_rule_contract_sha256,
            "semantic_contract_sha256": current_semantic_contract_sha256,
            "accepted_semantic_contract_sha256": accepted_semantic_contract_sha256,
            "project_dir": str(project_dir),
            "manifest": str(manifest_path),
            "error": None,
        }
    except Exception as exc:
        return {
            "template": template,
            "lifecycle_status": "failed",
            "checks": {
                check_id: False
                for check_id in RULE_ACCEPTANCE_CHECK_IDS
                if check_id != "supported_templates_exercised"
            },
            "rule_contract_sha256": rule_contract_sha256(rule),
            "accepted_rule_contract_sha256": None,
            "semantic_contract_sha256": rule_semantic_contract_sha256(rule),
            "accepted_semantic_contract_sha256": None,
            "project_dir": None,
            "manifest": None,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
