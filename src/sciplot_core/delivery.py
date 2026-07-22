from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sciplot_core._utils import existing_file_sha256, slug
from sciplot_core.launchers import (
    inspect_delivery_launcher_contract,
    write_delivery_launcher,
)
from sciplot_core.output_contract import requested_delivery_root
from sciplot_core.plot_data import build_plot_data_exports
from sciplot_core.policy import (
    DELIVERY_DATA_DIR,
    DELIVERY_DIR,
    DELIVERY_LAUNCHER,
    DELIVERY_PDF_DIR,
    DELIVERY_PROJECT_DIR,
    DELIVERY_TIFF_DIR,
    canonical_figure_stem,
)

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
DELIVERY_PACKAGE_CONTRACT_VERSION = 5


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


def _delivery_figure_pairing(figure_records: list[dict[str, Any]]) -> dict[str, Any]:
    pdf_index: dict[str, list[str]] = {}
    tiff_index: dict[str, list[str]] = {}
    invalid_tiff_names: list[str] = []
    for record in figure_records:
        path = Path(str(record["path"]))
        if path.suffix.casefold() == ".pdf":
            pdf_index.setdefault(canonical_figure_stem(path), []).append(str(path))
        elif path.suffix.casefold() in {".tif", ".tiff"}:
            tiff_index.setdefault(canonical_figure_stem(path), []).append(str(path))
            if not path.name.casefold().endswith("_300dpi.tiff"):
                invalid_tiff_names.append(str(path))

    pdf_stems = set(pdf_index)
    tiff_stems = set(tiff_index)
    missing_tiffs = sorted(pdf_stems - tiff_stems)
    orphan_tiffs = sorted(tiff_stems - pdf_stems)
    duplicate_pdfs = {stem: paths for stem, paths in pdf_index.items() if len(paths) != 1}
    duplicate_tiffs = {stem: paths for stem, paths in tiff_index.items() if len(paths) != 1}
    passed = bool(pdf_index) and bool(tiff_index) and not any(
        (missing_tiffs, orphan_tiffs, duplicate_pdfs, duplicate_tiffs, invalid_tiff_names)
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


def _manifest_veusz_documents(manifest: dict[str, Any], output_dir: Path) -> list[Path]:
    values: list[object] = []
    values.extend(manifest.get("veusz_documents", []) if isinstance(manifest.get("veusz_documents"), list) else [])
    values.append(manifest.get("veusz_document"))
    for key in ("result", "studio"):
        payload = manifest.get(key) if isinstance(manifest.get(key), dict) else {}
        values.extend(payload.get("veusz_documents", []) if isinstance(payload.get("veusz_documents"), list) else [])
        values.extend([payload.get("veusz_document"), payload.get("document")])

    def existing_documents(candidates: list[object]) -> list[Path]:
        documents: list[Path] = []
        seen: set[Path] = set()
        for value in candidates:
            if not isinstance(value, str | Path) or not str(value).strip():
                continue
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = output_dir / candidate
            candidate = candidate.resolve()
            if candidate in seen or not candidate.exists() or not candidate.is_file():
                continue
            documents.append(candidate)
            seen.add(candidate)
        return documents

    documents = existing_documents(values)
    if documents:
        return documents
    fallback_values: list[object] = []
    fallback_values.extend(sorted((output_dir / "figures" / "_veusz").glob("**/studio/document.vsz")))
    fallback_values.extend(sorted((output_dir / "studio").glob("*.vsz")))
    return existing_documents(fallback_values)


def _editable_project_name(document: Path, *, index: int) -> str:
    project_root = document.parent.parent
    candidate = project_root.parent.name if project_root.name.startswith(("single", "panel_")) else project_root.name
    if candidate in {"", "_veusz", "figures", "studio"}:
        candidate = document.stem if document.stem not in {"", "document"} else f"figure_{index:02d}"
    return slug(candidate) or f"figure_{index:02d}"


def _copy_project_documents(
    manifest: dict[str, Any],
    *,
    output_dir: Path,
    project_dir: Path,
) -> list[dict[str, Any]]:
    documents = _manifest_veusz_documents(manifest, output_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    used_names: set[str] = set()
    expected_hash = str(manifest.get("exported_document_hash") or "").strip()
    expected_hashes = {
        str(Path(path).expanduser().resolve()): str(value)
        for path, value in (
            manifest.get("veusz_document_hashes", {}).items()
            if isinstance(manifest.get("veusz_document_hashes"), dict)
            else []
        )
        if str(path).strip() and str(value).strip()
    }
    for index, source_document in enumerate(documents, start=1):
        base_name = _editable_project_name(source_document, index=index)
        name = base_name
        suffix = 2
        while name in used_names:
            name = f"{base_name}_{suffix}"
            suffix += 1
        used_names.add(name)
        destination = project_dir / f"{name}.vsz"
        shutil.copy2(source_document, destination)
        source_hash = existing_file_sha256(source_document)
        delivery_hash = existing_file_sha256(destination)
        document_expected_hash = expected_hashes.get(
            str(source_document.resolve()),
            expected_hash,
        )
        hash_matches_export = bool(
            source_hash
            and delivery_hash
            and source_hash == delivery_hash
            and (
                not document_expected_hash
                or delivery_hash == document_expected_hash
            )
        )
        records.append(
            {
                "kind": "sciplot_delivery_project_file",
                "id": name,
                "source": str(source_document),
                "path": str(destination),
                "relative_path": str(destination.relative_to(project_dir.parent)),
                "format": "vsz",
                "source_sha256": source_hash,
                "delivery_sha256": delivery_hash,
                "copy_hash_matches": bool(source_hash and source_hash == delivery_hash),
                "hash_matches_export": hash_matches_export,
                "exists": destination.exists(),
            }
        )
    return records


def _qa_hash_evidence(manifest: dict[str, Any], figure_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    qa_payload = manifest.get("qa") if isinstance(manifest.get("qa"), dict) else {}
    qa_hashes = {
        str(Path(str(report.get("path"))).expanduser().resolve()): str(report.get("sha256"))
        for report_group in (qa_payload.get("pdfs"), qa_payload.get("tiffs"))
        if isinstance(report_group, list)
        for report in report_group
        if isinstance(report, dict) and report.get("path") and report.get("sha256")
    }
    return [
        {
            "source": record["source"],
            "qa_sha256": qa_hashes.get(str(Path(record["source"]).expanduser().resolve())),
            "source_sha256": record.get("source_sha256"),
            "delivery_sha256": record.get("delivery_sha256"),
        }
        for record in figure_records
    ]


def _publication_status(output_dir: Path) -> tuple[bool, list[dict[str, Any]]]:
    present = any((output_dir / filename).exists() for filename in PUBLICATION_ARTIFACT_FILENAMES)
    if not present:
        return False, []
    statuses: list[dict[str, Any]] = []
    for filename in PUBLICATION_ARTIFACT_FILENAMES:
        path = output_dir / filename
        valid_json = False
        valid_contract = False
        if path.exists():
            try:
                import json

                payload = json.loads(path.read_text(encoding="utf-8"))
                valid_json = isinstance(payload, dict)
                valid_contract = valid_json and payload.get("kind") == PUBLICATION_ARTIFACT_KINDS[filename]
            except (OSError, ValueError):
                pass
        statuses.extend(
            [
                {"id": f"{Path(filename).stem}_valid_json", "path": str(path), "exists": valid_json},
                {"id": f"{Path(filename).stem}_valid_contract", "path": str(path), "exists": valid_contract},
            ]
        )
    return True, statuses


def _recorded_file_set(
    records: object,
    *,
    directory: Path,
    suffixes: set[str],
    hash_field: str,
) -> dict[str, Any]:
    live_files = {
        path.resolve()
        for path in directory.iterdir()
        if path.is_file() and path.suffix.casefold() in suffixes
    } if directory.is_dir() else set()
    recorded_files: set[Path] = set()
    invalid: list[dict[str, Any]] = []
    if not isinstance(records, list):
        return {
            "passed": False,
            "live_files": sorted(str(path) for path in live_files),
            "recorded_files": [],
            "invalid": [{"reason": "records_missing"}],
        }
    for record in records:
        if not isinstance(record, dict):
            invalid.append({"reason": "record_not_object"})
            continue
        path_value = record.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            invalid.append({"reason": "path_missing", "record": record})
            continue
        path = Path(path_value).expanduser().resolve()
        expected_hash = str(record.get(hash_field) or "").strip()
        actual_hash = existing_file_sha256(path)
        valid = bool(
            path.parent == directory.resolve()
            and path.suffix.casefold() in suffixes
            and path.is_file()
            and path.stat().st_size > 0
            and expected_hash
            and actual_hash == expected_hash
        )
        if not valid:
            invalid.append(
                {
                    "reason": "file_or_hash_invalid",
                    "path": str(path),
                    "expected_sha256": expected_hash or None,
                    "actual_sha256": actual_hash,
                }
            )
        recorded_files.add(path)
    return {
        "passed": bool(live_files)
        and not invalid
        and live_files == recorded_files,
        "live_files": sorted(str(path) for path in live_files),
        "recorded_files": sorted(str(path) for path in recorded_files),
        "invalid": invalid,
    }


def verify_delivery_package(
    delivery_package: object,
    *,
    expected_root: Path,
) -> dict[str, Any]:
    """Revalidate the persisted minimal delivery against live files and hashes."""

    record = delivery_package if isinstance(delivery_package, dict) else {}
    expected = expected_root.expanduser().resolve()
    path_value = record.get("path")
    recorded_root = (
        Path(path_value).expanduser().resolve()
        if isinstance(path_value, str) and path_value.strip()
        else None
    )
    root_ready = bool(
        recorded_root == expected and expected.is_dir()
    )
    expected_top_level = {
        DELIVERY_DATA_DIR,
        DELIVERY_PDF_DIR,
        DELIVERY_TIFF_DIR,
        DELIVERY_PROJECT_DIR,
        DELIVERY_LAUNCHER,
    }
    actual_top_level = (
        {path.name for path in expected.iterdir()} if expected.is_dir() else set()
    )
    data_check = _recorded_file_set(
        record.get("data_csvs"),
        directory=expected / DELIVERY_DATA_DIR,
        suffixes={".csv"},
        hash_field="sha256",
    )
    figure_records = record.get("figures")
    pdf_records = [
        item
        for item in figure_records
        if isinstance(item, dict)
        and Path(str(item.get("path") or "")).suffix.casefold() == ".pdf"
    ] if isinstance(figure_records, list) else None
    tiff_records = [
        item
        for item in figure_records
        if isinstance(item, dict)
        and Path(str(item.get("path") or "")).suffix.casefold() in {".tif", ".tiff"}
    ] if isinstance(figure_records, list) else None
    pdf_check = _recorded_file_set(
        pdf_records,
        directory=expected / DELIVERY_PDF_DIR,
        suffixes={".pdf"},
        hash_field="delivery_sha256",
    )
    tiff_check = _recorded_file_set(
        tiff_records,
        directory=expected / DELIVERY_TIFF_DIR,
        suffixes={".tif", ".tiff"},
        hash_field="delivery_sha256",
    )
    project_check = _recorded_file_set(
        record.get("project_documents"),
        directory=expected / DELIVERY_PROJECT_DIR,
        suffixes={".vsz"},
        hash_field="delivery_sha256",
    )
    live_figure_records = [
        {"path": path}
        for directory, suffixes in (
            (expected / DELIVERY_PDF_DIR, {".pdf"}),
            (expected / DELIVERY_TIFF_DIR, {".tif", ".tiff"}),
        )
        if directory.is_dir()
        for path in directory.iterdir()
        if path.is_file() and path.suffix.casefold() in suffixes
    ]
    pairing = _delivery_figure_pairing(live_figure_records)
    launcher = expected / DELIVERY_LAUNCHER
    live_launcher_contract = inspect_delivery_launcher_contract(expected)
    recorded_launcher_contract = (
        record.get("launcher_contract")
        if isinstance(record.get("launcher_contract"), dict)
        else {}
    )
    recorded_launcher_path = record.get("open_in_veusz")
    launcher_path_current = bool(
        isinstance(recorded_launcher_path, str)
        and recorded_launcher_path.strip()
        and Path(recorded_launcher_path).expanduser().resolve() == launcher.resolve()
    )
    recorded_launcher_sha256 = str(
        record.get("open_in_veusz_sha256") or ""
    ).strip()
    launcher_hash_current = bool(
        recorded_launcher_sha256
        and recorded_launcher_sha256 == live_launcher_contract.get("content_sha256")
    )
    launcher_structure_current = bool(
        live_launcher_contract.get("ready") is True
        and live_launcher_contract.get("canonical_structure") is True
        and live_launcher_contract.get("required_command_present") is True
    )
    launcher_contract_current = bool(
        recorded_launcher_contract
        and recorded_launcher_contract == live_launcher_contract
    )
    launcher_ready = bool(
        launcher_path_current
        and launcher_hash_current
        and launcher_structure_current
        and launcher_contract_current
    )
    artifacts = record.get("artifacts")
    artifact_records_ready = bool(
        isinstance(artifacts, list)
        and artifacts
        and all(
            isinstance(item, dict)
            and item.get("exists") is True
            and isinstance(item.get("path"), str)
            and Path(str(item["path"])).expanduser().exists()
            for item in artifacts
        )
    )
    checks = {
        "record_kind_current": record.get("kind") == "sciplot_user_delivery_package"
        and record.get("version") == DELIVERY_PACKAGE_CONTRACT_VERSION,
        "recorded_complete": record.get("complete") is True,
        "canonical_root": root_ready,
        "minimal_top_level": actual_top_level == expected_top_level,
        "data_files_current": data_check["passed"],
        "pdf_files_current": pdf_check["passed"],
        "tiff_files_current": tiff_check["passed"],
        "project_files_current": project_check["passed"],
        "canonical_pdf_tiff_pairs": pairing["passed"],
        "launcher_path_current": launcher_path_current,
        "launcher_hash_current": launcher_hash_current,
        "launcher_structure_current": launcher_structure_current,
        "launcher_contract_current": launcher_contract_current,
        "launcher_current": launcher_ready,
        "artifact_records_current": artifact_records_ready,
    }
    return {
        "kind": "sciplot_delivery_verification",
        "version": 1,
        "passed": all(checks.values()),
        "checks": checks,
        "failed_checks": [key for key, passed in checks.items() if not passed],
        "expected_root": str(expected),
        "recorded_root": str(recorded_root) if recorded_root is not None else None,
        "top_level": {
            "expected": sorted(expected_top_level),
            "actual": sorted(actual_top_level),
        },
        "data": data_check,
        "pdf": pdf_check,
        "tiff": tiff_check,
        "project": project_check,
        "pairing": pairing,
        "launcher": live_launcher_contract,
    }


def build_delivery_package(output_dir: Path, *, manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the small user-facing delivery surface.

    Internal manifests, QA reports, raw archives, analysis tables, and
    provenance stay in the run output.  They are intentionally not copied
    into the visible handoff.  New user workflows record that handoff beside
    the source (or at ``--out``); legacy/development callers fall back to
    ``RUN/delivery``.
    """

    output_dir = output_dir.expanduser().resolve()
    delivery_dir = requested_delivery_root(manifest, run_output=output_dir)
    if delivery_dir.exists():
        if not delivery_dir.is_dir() or delivery_dir.is_symlink():
            raise ValueError(
                "The visible SciPlot output must be a dedicated real directory."
            )
        managed_names = {
            DELIVERY_DATA_DIR,
            DELIVERY_PDF_DIR,
            DELIVERY_TIFF_DIR,
            DELIVERY_PROJECT_DIR,
            DELIVERY_LAUNCHER,
        }
        unknown = {path.name for path in delivery_dir.iterdir()} - managed_names
        if unknown:
            raise ValueError(
                "Refusing to replace a non-dedicated SciPlot output directory; "
                f"unexpected entries: {', '.join(sorted(unknown))}."
            )
        for path in delivery_dir.iterdir():
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
    data_dir = delivery_dir / DELIVERY_DATA_DIR
    pdf_dir = delivery_dir / DELIVERY_PDF_DIR
    tiff_dir = delivery_dir / DELIVERY_TIFF_DIR
    project_dir = delivery_dir / DELIVERY_PROJECT_DIR
    for directory in {data_dir, pdf_dir, tiff_dir, project_dir}:
        directory.mkdir(parents=True, exist_ok=True)

    project = _project_slug(output_dir, manifest)
    figure_records: list[dict[str, Any]] = []
    for figure_value in manifest.get("figures", []):
        if not isinstance(figure_value, str):
            continue
        source = Path(figure_value).expanduser()
        suffix = source.suffix.casefold()
        if not source.is_file() or suffix not in {".pdf", ".tif", ".tiff"}:
            continue
        target_dir = pdf_dir if suffix == ".pdf" else tiff_dir
        destination = target_dir / source.name
        shutil.copy2(source, destination)
        source_hash = existing_file_sha256(source)
        delivery_hash = existing_file_sha256(destination)
        figure_records.append(
            {
                "source": str(source),
                "path": str(destination),
                "relative_path": str(destination.relative_to(delivery_dir)),
                "format": "pdf" if suffix == ".pdf" else "tiff",
                "export_format": "pdf" if suffix == ".pdf" else "tiff_300",
                "source_sha256": source_hash,
                "delivery_sha256": delivery_hash,
                "copy_hash_matches": bool(source_hash and source_hash == delivery_hash),
                "exists": destination.exists(),
            }
        )

    data_records = build_plot_data_exports(manifest, destination=data_dir)
    project_records = _copy_project_documents(manifest, output_dir=output_dir, project_dir=project_dir)
    launcher = write_delivery_launcher(delivery_dir)
    launcher_contract = inspect_delivery_launcher_contract(delivery_dir)
    figure_pairing = _delivery_figure_pairing(figure_records)
    qa_hash_evidence = _qa_hash_evidence(manifest, figure_records)
    qa_hashes_match = bool(qa_hash_evidence) and all(
        item["qa_sha256"]
        and item["qa_sha256"] == item["source_sha256"] == item["delivery_sha256"]
        for item in qa_hash_evidence
    )
    project_files_exist = bool(project_records) and all(item["exists"] for item in project_records)
    data_files_exist = bool(data_records) and all(Path(str(item["path"])).exists() for item in data_records)
    qa_payload = manifest.get("qa") if isinstance(manifest.get("qa"), dict) else {}
    qa_passed = qa_payload.get("status") == "passed"
    publication_present, publication_status = _publication_status(output_dir)

    artifact_status: list[dict[str, Any]] = [
        {
            "id": "plot_data_csv",
            "path": str(data_dir),
            "exists": data_files_exist,
            "details": data_records,
        },
        {
            "id": "pdf_exports",
            "path": str(pdf_dir),
            "exists": bool(figure_pairing["pdf_stems"]),
        },
        {
            "id": "tiff_exports",
            "path": str(tiff_dir),
            "exists": bool(figure_pairing["tiff_stems"]),
        },
        {
            "id": "canonical_pdf_tiff_pairs",
            "path": str(delivery_dir),
            "exists": bool(figure_pairing["passed"]),
            "details": figure_pairing,
        },
        {
            "id": "project_files",
            "path": str(project_dir),
            "exists": project_files_exist,
            "details": project_records,
        },
        {
            "id": "open_in_veusz",
            "path": str(launcher),
            "exists": launcher_contract.get("ready") is True
            and bool(project_records),
            "details": launcher_contract,
        },
        {
            "id": "qa_passed",
            "path": str(output_dir / "manifest.json"),
            "exists": qa_passed,
        },
        {
            "id": "qa_artifact_hashes_match_delivery",
            "path": str(delivery_dir),
            "exists": qa_hashes_match,
            "details": qa_hash_evidence,
        },
    ]
    if project_records:
        artifact_status.append(
            {
                "id": "editable_vsz_hash_match",
                "path": str(project_records[0]["path"]),
                "exists": bool(project_records[0]["hash_matches_export"]),
            }
        )
    if publication_present:
        artifact_status.extend(publication_status)
        publication_intent = (
            manifest.get("publication_intent") if isinstance(manifest.get("publication_intent"), dict) else {}
        )
        if publication_intent.get("target_status") == "confirmed":
            artifact_status.append(
                {
                    "id": "publication_qa_passed",
                    "path": str(output_dir / "publication_qa.json"),
                    "exists": (output_dir / "publication_qa.json").exists()
                    and isinstance(manifest.get("publication_qa"), dict)
                    and manifest["publication_qa"].get("status") == "passed",
                }
            )

    project_file = project_records[0]["path"] if project_records else None
    editable_vsz = None
    if project_records:
        first = project_records[0]
        editable_vsz = {
            "kind": "sciplot_delivery_editable_vsz",
            "path": first["path"],
            "relative_path": first["relative_path"],
            "exists": first["exists"],
            "authority": manifest.get("document_authority"),
            "manual_edit_detected": bool(manifest.get("manual_edit_detected")),
            "expected_hash": manifest.get("exported_document_hash") or first["source_sha256"],
            "actual_hash": first["delivery_sha256"],
            "hash_matches_export": first["hash_matches_export"],
        }
    delivery_record: dict[str, Any] = {
        "kind": "sciplot_user_delivery_package",
        "version": DELIVERY_PACKAGE_CONTRACT_VERSION,
        "path": str(delivery_dir),
        "project": project,
        "data_dir": str(data_dir),
        "data_csvs": data_records,
        "pdf_dir": str(pdf_dir),
        "tiff_dir": str(tiff_dir),
        "figures": figure_records,
        "project_dir": str(project_dir),
        "project_file": project_file,
        "project_documents": project_records,
        "open_in_veusz": str(launcher),
        "open_in_veusz_sha256": launcher_contract["content_sha256"],
        "launcher_contract": launcher_contract,
        "editable": str(project_dir),
        "editable_vsz": editable_vsz,
        "editable_vsz_projects": project_records,
        "artifacts": artifact_status,
    }
    delivery_record["complete"] = all(item["exists"] for item in artifact_status)
    verification = verify_delivery_package(
        delivery_record,
        expected_root=delivery_dir,
    )
    delivery_record["verification"] = verification
    delivery_record["complete"] = bool(
        delivery_record["complete"] and verification["passed"]
    )

    return delivery_record


__all__ = [
    "DELIVERY_PACKAGE_CONTRACT_VERSION",
    "build_delivery_package",
    "verify_delivery_package",
]
