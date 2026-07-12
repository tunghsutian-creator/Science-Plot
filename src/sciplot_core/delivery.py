from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._utils import json_safe, slug
from sciplot_core.assisted_cleanup import CLEANUP_REQUEST_FILENAME, CLEANUP_RESULT_FILENAME
from sciplot_core.policy import DELIVERY_DIR, DELIVERY_FIGURES_DIR, DELIVERY_INTERNAL_DIR

PUBLICATION_ARTIFACT_FILENAMES = (
    "publication_intent.json",
    "transform_ledger.json",
    "journal_profile.json",
    "publication_qa.json",
)
PUBLICATION_ARTIFACT_KINDS = {
    "publication_intent.json": "sciplot_publication_intent",
    "transform_ledger.json": "sciplot_transform_ledger",
    "journal_profile.json": "sciplot_publication_profile",
    "publication_qa.json": "sciplot_publication_qa",
}


def _project_slug(output_dir: Path, manifest: dict[str, Any]) -> str:
    request_path = manifest.get("request_path")
    if isinstance(request_path, str) and request_path.strip():
        parent = Path(request_path).expanduser().parent
        if parent.name and parent.name not in {".", ".."}:
            return slug(parent.name)
    input_path = manifest.get("input")
    if isinstance(input_path, str) and input_path.strip():
        return slug(Path(input_path).stem)
    return slug(output_dir.name)


def _copytree_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return True


def _copy_file_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _canonical_figure_stem(path_value: object) -> str:
    stem = Path(str(path_value)).stem
    return re.sub(r"_\d+dpi$", "", stem, flags=re.IGNORECASE).casefold()


def _delivery_figure_pairing(figure_records: list[dict[str, Any]]) -> dict[str, Any]:
    pdf_index: dict[str, list[str]] = {}
    tiff_index: dict[str, list[str]] = {}
    invalid_tiff_names = []
    for record in figure_records:
        path = Path(str(record["path"]))
        if path.suffix.casefold() == ".pdf":
            pdf_index.setdefault(_canonical_figure_stem(path), []).append(str(path))
        elif path.suffix.casefold() in {".tif", ".tiff"}:
            tiff_index.setdefault(_canonical_figure_stem(path), []).append(str(path))
            if not path.name.casefold().endswith("_300dpi.tiff"):
                invalid_tiff_names.append(str(path))

    pdf_stems = set(pdf_index)
    tiff_stems = set(tiff_index)
    missing_tiffs = sorted(pdf_stems - tiff_stems)
    orphan_tiffs = sorted(tiff_stems - pdf_stems)
    duplicate_pdfs = {stem: paths for stem, paths in pdf_index.items() if len(paths) != 1}
    duplicate_tiffs = {stem: paths for stem, paths in tiff_index.items() if len(paths) != 1}
    passed = (
        bool(pdf_index)
        and bool(tiff_index)
        and not any((missing_tiffs, orphan_tiffs, duplicate_pdfs, duplicate_tiffs, invalid_tiff_names))
    )
    return {
        "passed": passed,
        "pdf_stems": sorted(pdf_stems),
        "tiff_stems": sorted(tiff_stems),
        "missing_tiffs": missing_tiffs,
        "orphan_tiffs": orphan_tiffs,
        "duplicate_pdfs": duplicate_pdfs,
        "duplicate_tiffs": duplicate_tiffs,
        "invalid_tiff_names": invalid_tiff_names,
    }


def _editable_vsz_delivery_record(manifest: dict[str, Any], internal_dir: Path) -> dict[str, Any] | None:
    expected_hash = manifest.get("exported_document_hash")
    if not isinstance(expected_hash, str) or not expected_hash.strip():
        return None
    document_value = manifest.get("veusz_document")
    document_name = Path(document_value).name if isinstance(document_value, str) else "document.vsz"
    candidate = internal_dir / "studio" / document_name
    if not candidate.exists():
        documents = sorted((internal_dir / "studio").glob("*.vsz"))
        candidate = documents[0] if documents else candidate
    actual_hash = _sha256(candidate)
    return {
        "kind": "sciplot_delivery_editable_vsz",
        "path": str(candidate),
        "relative_path": str(candidate.relative_to(internal_dir.parent)) if candidate.exists() else None,
        "exists": candidate.exists(),
        "authority": manifest.get("document_authority"),
        "manual_edit_detected": bool(manifest.get("manual_edit_detected")),
        "expected_hash": expected_hash,
        "actual_hash": actual_hash,
        "hash_matches_export": bool(actual_hash and actual_hash == expected_hash),
    }


def _write_excel_data(source: Path, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        shutil.copy2(source, destination)
        return {"source": str(source), "converted": False, "sheet": None}
    if source.suffix.lower() in {".csv", ".txt", ".tsv"}:
        separator = "\t" if source.suffix.lower() == ".tsv" else ","
        frame = pd.read_csv(source, header=None, sep=separator)
        with pd.ExcelWriter(destination) as writer:
            frame.to_excel(writer, sheet_name="plot_data", header=False, index=False)
        return {"source": str(source), "converted": True, "sheet": "plot_data"}
    frame = pd.DataFrame({"source_path": [str(source)]})
    with pd.ExcelWriter(destination) as writer:
        frame.to_excel(writer, sheet_name="plot_data", index=False)
    return {"source": str(source), "converted": True, "sheet": "plot_data"}


def _delivery_data_source(manifest: dict[str, Any]) -> Path | None:
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    for key in ("processed_source", "input"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            candidate = Path(value).expanduser()
            if candidate.exists() and candidate.is_file():
                return candidate
    value = manifest.get("input")
    if isinstance(value, str) and value.strip():
        candidate = Path(value).expanduser()
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def build_delivery_package(output_dir: Path, *, manifest: dict[str, Any]) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    delivery_dir = output_dir / DELIVERY_DIR
    if delivery_dir.exists():
        shutil.rmtree(delivery_dir)
    figures_dir = delivery_dir / DELIVERY_FIGURES_DIR
    internal_dir = delivery_dir / DELIVERY_INTERNAL_DIR
    figures_dir.mkdir(parents=True, exist_ok=True)
    internal_dir.mkdir(parents=True, exist_ok=True)

    project = _project_slug(output_dir, manifest)
    sciplot_path = delivery_dir / f"{project}.sciplot"
    data_path = delivery_dir / f"{project}.xlsx"

    figure_records: list[dict[str, Any]] = []
    for figure_value in manifest.get("figures", []):
        if not isinstance(figure_value, str):
            continue
        source = Path(figure_value).expanduser()
        if not source.exists() or not source.is_file():
            continue
        destination = figures_dir / source.name
        shutil.copy2(source, destination)
        source_hash = _sha256(source)
        delivery_hash = _sha256(destination)
        figure_records.append(
            {
                "source": str(source),
                "path": str(destination),
                "relative_path": str(destination.relative_to(delivery_dir)),
                "format": source.suffix.lower().lstrip("."),
                "source_sha256": source_hash,
                "delivery_sha256": delivery_hash,
                "copy_hash_matches": bool(source_hash and source_hash == delivery_hash),
            }
        )

    data_source = _delivery_data_source(manifest)
    data_record: dict[str, Any] | None = None
    if data_source is not None:
        data_record = _write_excel_data(data_source, data_path)
        data_record["path"] = str(data_path)
        data_record["relative_path"] = str(data_path.relative_to(delivery_dir))

    copied_internal: list[str] = []
    for filename in (
        "request_snapshot.json",
        "analysis_report.md",
        "revision_brief.md",
        "review.html",
        "intervention_request.json",
        CLEANUP_REQUEST_FILENAME,
        CLEANUP_RESULT_FILENAME,
        *PUBLICATION_ARTIFACT_FILENAMES,
    ):
        if _copy_file_if_exists(output_dir / filename, internal_dir / filename):
            copied_internal.append(filename)
    for folder in ("tables", "raw", "processed", "_veusz", "studio"):
        if _copytree_if_exists(output_dir / folder, internal_dir / folder):
            copied_internal.append(folder)
    if _copytree_if_exists(output_dir / "figures" / "_veusz", internal_dir / "_veusz"):
        copied_internal.append("_veusz")

    editable_vsz = _editable_vsz_delivery_record(manifest, internal_dir)

    delivery_record = {
        "kind": "sciplot_minimal_delivery_package",
        "version": 1,
        "path": str(delivery_dir),
        "project": project,
        "project_file": str(sciplot_path),
        "excel_data": str(data_path) if data_path.exists() else None,
        "figures": figure_records,
        "internal": str(internal_dir),
        "internal_artifacts": copied_internal,
        "editable_vsz": editable_vsz,
    }
    manifest_payload = json_safe({**manifest, "delivery_package": delivery_record})
    (internal_dir / "manifest.json").write_text(
        json.dumps(manifest_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    copied_internal.insert(0, "manifest.json")

    project_payload = {
        "kind": "sciplot_project",
        "version": 1,
        "project": project,
        "manifest": manifest_payload,
        "delivery_package": delivery_record,
        "data": data_record,
        "figures": figure_records,
        "internal_dir": DELIVERY_INTERNAL_DIR,
    }
    sciplot_path.write_text(json.dumps(project_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    figure_pairing = _delivery_figure_pairing(figure_records)
    artifact_status = [
        {"id": "project_file", "path": str(sciplot_path), "exists": sciplot_path.exists()},
        {"id": "excel_data", "path": str(data_path), "exists": data_path.exists()},
        {"id": "pdf", "path": str(figures_dir), "exists": bool(figure_pairing["pdf_stems"])},
        {"id": "tiff_300", "path": str(figures_dir), "exists": bool(figure_pairing["tiff_stems"])},
        {
            "id": "canonical_pdf_tiff_pairs",
            "path": str(figures_dir),
            "exists": bool(figure_pairing["passed"]),
            "details": figure_pairing,
        },
        {
            "id": "qa_passed",
            "path": str(internal_dir / "manifest.json"),
            "exists": bool(
                isinstance(manifest.get("qa"), dict)
                and manifest["qa"].get("status") == "passed"
                and (internal_dir / "manifest.json").exists()
            ),
        },
    ]
    publication_intent = (
        manifest.get("publication_intent") if isinstance(manifest.get("publication_intent"), dict) else {}
    )
    publication_contract_present = bool(publication_intent) or any(
        (output_dir / filename).exists() for filename in PUBLICATION_ARTIFACT_FILENAMES
    )
    parsed_publication_artifacts: dict[str, dict[str, Any] | None] = {}
    if publication_contract_present:
        for filename in PUBLICATION_ARTIFACT_FILENAMES:
            artifact_path = internal_dir / filename
            parsed = _read_json_object(artifact_path)
            parsed_publication_artifacts[filename] = parsed
            artifact_status.append(
                {
                    "id": f"{Path(filename).stem}_valid_json",
                    "path": str(artifact_path),
                    "exists": parsed is not None,
                }
            )
            artifact_status.append(
                {
                    "id": f"{Path(filename).stem}_valid_contract",
                    "path": str(artifact_path),
                    "exists": bool(
                        isinstance(parsed, dict)
                        and parsed.get("kind") == PUBLICATION_ARTIFACT_KINDS[filename]
                    ),
                }
            )
        copied_ledger = parsed_publication_artifacts.get("transform_ledger.json")
        artifact_status.append(
            {
                "id": "transform_lineage_reviewed",
                "path": str(internal_dir / "transform_ledger.json"),
                "exists": bool(
                    isinstance(copied_ledger, dict)
                    and copied_ledger.get("status") in {"runtime_recorded", "confirmed"}
                ),
            }
        )
        qa_payload = manifest.get("qa") if isinstance(manifest.get("qa"), dict) else {}
        qa_hashes = {
            str(Path(str(report.get("path"))).expanduser().resolve()): str(report.get("sha256"))
            for report_group in (qa_payload.get("pdfs"), qa_payload.get("tiffs"))
            if isinstance(report_group, list)
            for report in report_group
            if isinstance(report, dict) and report.get("path") and report.get("sha256")
        }
        hash_evidence = [
            {
                "source": record["source"],
                "qa_sha256": qa_hashes.get(str(Path(record["source"]).expanduser().resolve())),
                "source_sha256": record.get("source_sha256"),
                "delivery_sha256": record.get("delivery_sha256"),
            }
            for record in figure_records
        ]
        artifact_status.append(
            {
                "id": "qa_artifact_hashes_match_delivery",
                "path": str(figures_dir),
                "exists": bool(hash_evidence)
                and all(
                    evidence["qa_sha256"]
                    and evidence["qa_sha256"] == evidence["source_sha256"] == evidence["delivery_sha256"]
                    for evidence in hash_evidence
                ),
                "details": hash_evidence,
            }
        )

    copied_intent = parsed_publication_artifacts.get("publication_intent.json")
    target_confirmed = publication_intent.get("target_status") == "confirmed" or bool(
        isinstance(copied_intent, dict) and copied_intent.get("target_status") == "confirmed"
    )
    if target_confirmed:
        publication_qa = parsed_publication_artifacts.get("publication_qa.json")
        artifact_status.append(
            {
                "id": "publication_qa_passed",
                "path": str(internal_dir / "publication_qa.json"),
                "exists": bool(isinstance(publication_qa, dict) and publication_qa.get("status") == "passed"),
            }
        )
    if editable_vsz is not None:
        artifact_status.extend(
            [
                {
                    "id": "editable_vsz",
                    "path": str(editable_vsz["path"]),
                    "exists": bool(editable_vsz["exists"]),
                },
                {
                    "id": "editable_vsz_hash_match",
                    "path": str(editable_vsz["path"]),
                    "exists": bool(editable_vsz["hash_matches_export"]),
                },
            ]
        )
    delivery_record = {
        **delivery_record,
        "complete": all(item["exists"] for item in artifact_status),
        "artifacts": artifact_status,
    }
    manifest_payload = json_safe({**manifest, "delivery_package": delivery_record})
    one_step = manifest_payload.get("one_step")
    if isinstance(one_step, dict):
        one_step["delivery_package"] = delivery_record
        figure_qa = one_step.get("figure_qa_report")
        if isinstance(figure_qa, dict):
            figure_qa["delivery_complete"] = bool(delivery_record["complete"])
        if delivery_record["complete"]:
            reasons = [
                str(reason)
                for reason in one_step.get("state_reasons", [])
                if str(reason) != "delivery_package_incomplete"
            ]
            one_step["state_reasons"] = reasons or ["all_programmatic_gates_passed"]
            if one_step.get("state") == "needs_rule_repair" and not reasons:
                one_step["state"] = "ready"
    project_payload["delivery_package"] = delivery_record
    project_payload["manifest"] = manifest_payload
    (internal_dir / "manifest.json").write_text(
        json.dumps(project_payload["manifest"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    sciplot_path.write_text(json.dumps(project_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return delivery_record


__all__ = ["build_delivery_package"]
