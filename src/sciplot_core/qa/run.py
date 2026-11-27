"""Run complete QA and persist the evidence report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sciplot_core.publication import resolve_publication_profile
from sciplot_core.foundation.json_io import read_json_object

from sciplot_core.qa.artifacts import (
    _canonical_artifacts,
)

from sciplot_core.qa.format_pairing import _required_export_formats
from sciplot_core.qa.additional_exports import additional_export_reports
from sciplot_core.qa.pdf_inspection import _pdf_info

from sciplot_core.qa.raster_inspection import (
    _tiff_info,
)

from sciplot_core.qa.audit_support import (
    _discover_veusz_documents,
    _run_veusz_audit,
    _publication_intent,
)

from sciplot_core.qa.publication_qa import (
    _publication_qa,
)


def run_qa(
    output_dir: Path,
    *,
    goldens_dir: Path | None = None,
    require_all_goldens: bool = False,
    publication_profile: str | Path | dict[str, Any] | None = None,
    strict_publication: bool = False,
    veusz_documents: list[Path] | None = None,
    _managed_native: list[dict[str, Any]] | None = None,
    _export_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if publication_profile is None:
        discovered_profile = output_dir / "journal_profile.json"
        if discovered_profile.exists():
            publication_profile = discovered_profile
    pdfs = _canonical_artifacts(output_dir, (".pdf",))
    if not pdfs:
        raise ValueError(f"No PDF outputs found in {output_dir}.")
    pdf_reports = [_pdf_info(path) for path in pdfs]
    tiff_reports = [
        _tiff_info(path) for path in _canonical_artifacts(output_dir, (".tif", ".tiff"))
    ]
    reports_by_name = {Path(report["path"]).name: report for report in pdf_reports}
    golden_reports: list[dict[str, Any]] = []
    skipped_goldens: list[str] = []
    if goldens_dir is not None and goldens_dir.exists():
        for path in sorted(goldens_dir.glob("*.json")):
            golden = json.loads(path.read_text(encoding="utf-8"))
            if golden.get("kind") == "pdf_media_box":
                filename = str(golden["filename"])
                actual = reports_by_name.get(filename)
                if actual is None:
                    if require_all_goldens:
                        raise ValueError(
                            f"Golden media box target {filename} was not rendered."
                        )
                    skipped_goldens.append(filename)
                    continue
                expected = [float(item) for item in golden["media_box_pt"]]
                observed = [float(item) for item in actual["media_box_pt"]]
                tolerance = float(golden.get("tolerance_pt", 0.5))
                deltas = [
                    abs(left - right)
                    for left, right in zip(observed, expected, strict=True)
                ]
                if any(delta > tolerance for delta in deltas):
                    raise ValueError(
                        f"{filename} media box drifted: observed={observed}, expected={expected}, "
                        f"tolerance_pt={tolerance}."
                    )
            golden_reports.append(golden)
    profile = resolve_publication_profile(publication_profile)
    required_formats = _required_export_formats(output_dir, profile or {})
    additional = additional_export_reports(output_dir, pdf_reports, required=set(required_formats["formats"]))
    if _managed_native is not None and (not _managed_native or any(
            item["scientific_audit"]["status"] != "passed" or item["publication_qa"]["status"] != "passed"
            for item in _managed_native)):
        raise ValueError("Managed publication requires sealed scientific and native QA for each figure.")
    discovered_veusz_documents = _discover_veusz_documents(output_dir, veusz_documents)
    veusz_audit, veusz_audit_error = (
        _run_veusz_audit(discovered_veusz_documents) if profile else (None, None)
    )
    intent = _publication_intent(output_dir)
    exports = _export_artifacts
    if profile and exports is None:
        manifest = read_json_object(output_dir / "manifest.json") or {}
        result = manifest.get("result")
        value = result.get("exports") if isinstance(result, dict) else None
        exports = value if isinstance(value, list) else []
    publication = (
        _publication_qa(
            profile=profile,
            pdfs=pdf_reports,
            tiffs=tiff_reports,
            required_formats=required_formats,
            veusz_audit=veusz_audit,
            publication_intent=intent,
            exports=exports or [],
        )
        if profile and required_formats
        else None
    )
    if strict_publication and publication is None:
        publication = {
            "kind": "sciplot_publication_qa",
            "version": 2,
            "status": "not_evaluated",
            "reason_code": "publication_profile_missing",
            "message": "Strict publication QA requires a profile. Supply --publication-profile or provide journal_profile.json.",
            "checked_constraints_passed": None,
            "coverage_complete": False,
            "journal_compliance_established": False,
        }
    status = (
        "failed" if strict_publication and (publication or {}).get("status") != "passed" else "passed"
    )
    payload = {
        "kind": "sciplot_artifact_qa",
        "version": 2,
        "status": status,
        "pdf_count": len(pdf_reports),
        "pdfs": pdf_reports,
        "tiff_count": len(tiff_reports),
        "tiffs": tiff_reports,
        "goldens_checked": len(golden_reports),
        "goldens_skipped": skipped_goldens,
        "scientific_outcome_agnostic": True,
    }
    for key, reports in additional.items():
        if reports:
            payload[key] = reports
            payload[key[:-1] + "_count"] = len(reports)
    if _managed_native is not None:
        payload["managed_native"] = _managed_native
    if publication is not None:
        if veusz_audit_error:
            publication["veusz_document_audit_error"] = veusz_audit_error
        payload["publication"] = publication
        payload["publication_strict"] = bool(strict_publication)
    return payload
