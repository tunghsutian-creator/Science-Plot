"""Run complete QA and persist the evidence report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sciplot_core.publication import resolve_publication_profile

from sciplot_core.qa.artifacts import (
    _canonical_artifacts,
)

from sciplot_core.qa.format_pairing import _required_export_formats
from sciplot_core.qa.pdf_inspection import _pdf_info

from sciplot_core.qa.tiff_inspection import (
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
    required_formats = (
        _required_export_formats(output_dir, profile) if profile else None
    )
    discovered_veusz_documents = _discover_veusz_documents(output_dir, veusz_documents)
    veusz_audit, veusz_audit_error = (
        _run_veusz_audit(discovered_veusz_documents) if profile else (None, None)
    )
    intent = _publication_intent(output_dir)
    publication = (
        _publication_qa(
            profile=profile,
            pdfs=pdf_reports,
            tiffs=tiff_reports,
            required_formats=required_formats,
            veusz_audit=veusz_audit,
            publication_intent=intent,
        )
        if profile and required_formats
        else None
    )
    status = "passed"
    if (
        strict_publication
        and publication is not None
        and publication["status"] != "passed"
    ):
        status = "failed"
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
    if publication is not None:
        if veusz_audit_error:
            publication["veusz_document_audit_error"] = veusz_audit_error
        payload["publication"] = publication
        payload["publication_strict"] = bool(strict_publication)
    return payload
