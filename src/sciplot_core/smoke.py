from __future__ import annotations

import copy
import json
import math
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._paths import VENDORED_CORE_ROOT
from sciplot_core._utils import file_sha256, json_safe

RUNTIME_SMOKE_VERSION = 1
EXPECTED_RULE_ID = "ftir_spectrum"
MANUAL_EDIT_MARKER = "# SciPlot runtime smoke manual-edit preservation probe"


def _check(check_id: str, label: str, passed: bool, *, detail: Any = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def _delivery_artifact(delivery: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    artifacts = delivery.get("artifacts") if isinstance(delivery.get("artifacts"), list) else []
    for item in artifacts:
        if isinstance(item, dict) and item.get("id") == artifact_id:
            return item
    return {}


def _package_import_probe() -> dict[str, Any]:
    script = "\n".join(
        [
            "import json",
            "import sys",
            "before = list(sys.path)",
            "import sciplot_core",
            "after = list(sys.path)",
            "print(json.dumps({'added': [item for item in after if item not in before]}))",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "passed": False,
            "returncode": completed.returncode,
            "stderr": completed.stderr.strip(),
        }
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {
            "passed": False,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
        }
    added = [str(item) for item in payload.get("added", [])]
    vendor_root = VENDORED_CORE_ROOT.resolve()
    vendor_added = []
    for item in added:
        try:
            if Path(item).expanduser().resolve() == vendor_root:
                vendor_added.append(item)
        except (OSError, RuntimeError):
            continue
    return {
        "passed": not vendor_added,
        "added_paths": added,
        "vendor_paths_added": vendor_added,
    }


def _write_synthetic_ftir(path: Path) -> dict[str, Any]:
    """Write a deterministic contract fixture; this is never real-data evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[float, float]] = []
    for wavenumber in range(4000, 399, -50):
        transmittance = (
            97.5
            - 30.0 * math.exp(-((wavenumber - 3300.0) / 145.0) ** 2)
            - 18.0 * math.exp(-((wavenumber - 1715.0) / 75.0) ** 2)
            - 12.0 * math.exp(-((wavenumber - 1250.0) / 95.0) ** 2)
            - 8.0 * math.exp(-((wavenumber - 760.0) / 65.0) ** 2)
        )
        rows.append((float(wavenumber), transmittance))
    path.write_text(
        "\n".join(f"{x_value:.1f},{y_value:.6f}" for x_value, y_value in rows) + "\n",
        encoding="utf-8",
    )
    return {
        "kind": "sciplot_generated_contract_fixture",
        "semantic_family": EXPECTED_RULE_ID,
        "path": str(path),
        "sha256": file_sha256(path),
        "point_count": len(rows),
        "real_data_evidence": False,
        "evidence_tier": "generated_synthetic_contract_fixture",
    }


def _run_hash_failure_probe(output_dir: Path, manifest: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    from sciplot_core.delivery import build_delivery_package

    mismatched_manifest = copy.deepcopy(manifest)
    mismatched_manifest["exported_document_hash"] = "0" * 64
    rejected = build_delivery_package(output_dir, manifest=mismatched_manifest)
    hash_gate = _delivery_artifact(rejected, "editable_vsz_hash_match")
    rejected_as_expected = rejected.get("complete") is False and hash_gate.get("exists") is False

    restored = build_delivery_package(output_dir, manifest=manifest)
    restored_successfully = restored.get("complete") is True
    return rejected_as_expected and restored_successfully, {
        "mismatched_delivery_complete": rejected.get("complete"),
        "mismatched_hash_gate": hash_gate,
        "restored_delivery_complete": restored.get("complete"),
    }


def run_runtime_smoke(*, output_root: Path) -> dict[str, Any]:
    """Run a fixture-free end-to-end Studio lifecycle and delivery failure probe."""

    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="runtime_smoke_", dir=resolved_output))
    summary_path = run_root / "runtime_smoke.json"
    checks: list[dict[str, Any]] = []
    fixture: dict[str, Any] | None = None
    manifest_path: Path | None = None
    project_dir: Path | None = None
    error: dict[str, str] | None = None

    try:
        import_probe = _package_import_probe()
        checks.append(
            _check(
                "package_import_isolated",
                "Importing sciplot_core does not activate the migrated compatibility path",
                import_probe.get("passed") is True,
                detail=import_probe,
            )
        )

        from sciplot_core.doctor import doctor_payload
        from sciplot_core.studio import (
            export_studio_document,
            prepare_studio_document,
            publish_studio_export_run,
        )

        doctor = doctor_payload()
        checks.append(
            _check(
                "runtime_ready",
                "Required runtime dependencies and rule registry are ready",
                doctor.get("status") == "ready",
                detail={
                    "status": doctor.get("status"),
                    "ready_rules": (doctor.get("rule_summary") or {}).get("ready"),
                },
            )
        )
        normal_mode = doctor.get("normal_mode") if isinstance(doctor.get("normal_mode"), dict) else {}
        checks.append(
            _check(
                "independent_mode",
                "Normal plotting remains independent and Codex-optional",
                normal_mode.get("frontend_default") == "independent"
                and normal_mode.get("codex_required") is False
                and normal_mode.get("user_switch_required") is False,
                detail=normal_mode,
            )
        )

        fixture_path = run_root / "fixture" / "ftir_runtime_smoke.csv"
        fixture = _write_synthetic_ftir(fixture_path)
        prepared = prepare_studio_document(
            fixture_path,
            output_root=run_root / "projects",
            project_name="Synthetic FTIR runtime smoke",
        )
        project_dir = Path(str(prepared["project_dir"]))
        request_path = Path(str(prepared["request"]))
        document_path = Path(str(prepared["document"]))
        with document_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n{MANUAL_EDIT_MARKER}\n")

        export_payload = export_studio_document(document_path, formats=["pdf", "tiff_300"])
        exports = export_payload.get("exports") if isinstance(export_payload.get("exports"), list) else []
        studio_run = publish_studio_export_run(
            project_dir=project_dir,
            request_path=request_path,
            document_path=document_path,
            exports=exports,
        )
        manifest_path = Path(str(studio_run["manifest"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        semantic = manifest.get("semantic") if isinstance(manifest.get("semantic"), dict) else {}
        transform = manifest.get("transform_ledger") if isinstance(manifest.get("transform_ledger"), dict) else {}
        publication_intent = (
            manifest.get("publication_intent") if isinstance(manifest.get("publication_intent"), dict) else {}
        )
        delivery = manifest.get("delivery_package") if isinstance(manifest.get("delivery_package"), dict) else {}
        editable_vsz = delivery.get("editable_vsz") if isinstance(delivery.get("editable_vsz"), dict) else {}
        editable_path = Path(str(editable_vsz["path"])) if editable_vsz.get("path") else None
        raw_archive_value = (manifest.get("raw_archive") or {}).get("path")
        raw_archive_path = Path(str(raw_archive_value)) if raw_archive_value else None
        exported_formats = {str(item.get("format")) for item in exports if isinstance(item, dict)}
        exports_exist = all(
            isinstance(item, dict) and item.get("exists") is True and int(item.get("size_bytes") or 0) > 0
            for item in exports
        )

        checks.extend(
            [
                _check(
                    "semantic_rule_selected",
                    "Synthetic FTIR input selects the ready FTIR rule",
                    semantic.get("rule_id") == EXPECTED_RULE_ID,
                    detail={"selected": semantic.get("rule_id"), "expected": EXPECTED_RULE_ID},
                ),
                _check(
                    "vsz_reopen_export",
                    "Veusz reopens the canonical VSZ and exports the canonical format pair",
                    document_path.exists()
                    and int(prepared.get("series_count") or 0) > 0
                    and {"pdf", "tiff_300"} <= exported_formats
                    and exports_exist,
                    detail={
                        "document": str(document_path),
                        "series_count": prepared.get("series_count"),
                        "formats": sorted(exported_formats),
                    },
                ),
                _check(
                    "manual_edit_preserved",
                    "A saved VSZ edit is preserved in the editable delivery copy",
                    manifest.get("manual_edit_detected") is True
                    and MANUAL_EDIT_MARKER in document_path.read_text(encoding="utf-8")
                    and editable_path is not None
                    and editable_path.exists()
                    and MANUAL_EDIT_MARKER in editable_path.read_text(encoding="utf-8"),
                    detail={
                        "manual_edit_detected": manifest.get("manual_edit_detected"),
                        "editable_vsz": str(editable_path) if editable_path is not None else None,
                    },
                ),
                _check(
                    "exact_current_vsz_hash",
                    "The current, exported, and delivered editable VSZ hashes match",
                    manifest.get("exported_document_hash") == file_sha256(document_path)
                    and editable_vsz.get("hash_matches_export") is True,
                    detail={
                        "exported_document_hash": manifest.get("exported_document_hash"),
                        "current_document_hash": file_sha256(document_path),
                        "delivery_document_hash": editable_vsz.get("actual_hash"),
                    },
                ),
                _check(
                    "canonical_pdf_tiff_pair",
                    "Delivery contains a canonical PDF and 300 dpi TIFF pair",
                    _delivery_artifact(delivery, "canonical_pdf_tiff_pairs").get("exists") is True,
                    detail=_delivery_artifact(delivery, "canonical_pdf_tiff_pairs"),
                ),
                _check(
                    "qa_and_delivery_hashes",
                    "Artifact QA passes and its hashes match the delivery copies",
                    (manifest.get("qa") or {}).get("status") == "passed"
                    and _delivery_artifact(delivery, "qa_artifact_hashes_match_delivery").get("exists") is True,
                    detail={
                        "qa_status": (manifest.get("qa") or {}).get("status"),
                        "hash_gate": _delivery_artifact(delivery, "qa_artifact_hashes_match_delivery"),
                    },
                ),
                _check(
                    "delivery_complete",
                    "The portable delivery package is complete",
                    delivery.get("complete") is True,
                    detail={"path": delivery.get("path"), "complete": delivery.get("complete")},
                ),
                _check(
                    "runtime_lineage_recorded",
                    "Runtime transform and publication contracts are recorded",
                    transform.get("status") == "runtime_recorded"
                    and publication_intent.get("kind") == "sciplot_publication_intent"
                    and raw_archive_path is not None
                    and raw_archive_path.exists(),
                    detail={
                        "transform_status": transform.get("status"),
                        "publication_kind": publication_intent.get("kind"),
                        "raw_archive": str(raw_archive_path) if raw_archive_path is not None else None,
                    },
                ),
            ]
        )

        failure_probe_passed, failure_probe = _run_hash_failure_probe(
            Path(str(manifest["output"])),
            manifest,
        )
        checks.append(
            _check(
                "delivery_hash_failure_rejected",
                "A mismatched exported VSZ hash makes delivery incomplete",
                failure_probe_passed,
                detail=failure_probe,
            )
        )
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        checks.append(
            _check(
                "runtime_exception",
                "The runtime smoke completed without an exception",
                False,
                detail=error,
            )
        )

    status = "passed" if checks and all(item["status"] == "passed" for item in checks) else "failed"
    payload = {
        "kind": "sciplot_runtime_smoke",
        "version": RUNTIME_SMOKE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "state": "ready" if status == "passed" else "needs_rule_repair",
        "fixture": fixture,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(item["status"] == "passed" for item in checks),
            "failed_ids": [item["id"] for item in checks if item["status"] != "passed"],
        },
        "artifacts": {
            "run_root": str(run_root),
            "project_dir": str(project_dir) if project_dir is not None else None,
            "manifest": str(manifest_path) if manifest_path is not None else None,
            "summary": str(summary_path),
        },
        "error": error,
        "limitations": [
            "The generated FTIR table is a synthetic contract fixture, not real-data evidence.",
            "This smoke proves one representative Studio lifecycle and a delivery hash failure path; "
            "it does not replace the complete ready-rule acceptance matrix.",
            "Lifecycle success and artifact QA do not establish blanket journal compliance.",
        ],
    }
    summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


__all__ = ["run_runtime_smoke"]
