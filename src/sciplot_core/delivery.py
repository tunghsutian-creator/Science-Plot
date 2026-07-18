from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from sciplot_core._utils import existing_file_sha256, slug
from sciplot_core.launchers import portable_sciplot_prelude
from sciplot_core.plot_data import build_plot_data_exports
from sciplot_core.policy import (
    DELIVERY_DATA_DIR,
    DELIVERY_DIR,
    DELIVERY_LAUNCHER,
    DELIVERY_PDF_DIR,
    DELIVERY_PROJECT_DIR,
    DELIVERY_TIFF_DIR,
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


def _canonical_figure_stem(path_value: object) -> str:
    stem = Path(str(path_value)).stem
    return re.sub(r"_\d+dpi$", "", stem, flags=re.IGNORECASE).casefold()


def _delivery_figure_pairing(figure_records: list[dict[str, Any]]) -> dict[str, Any]:
    pdf_index: dict[str, list[str]] = {}
    tiff_index: dict[str, list[str]] = {}
    invalid_tiff_names: list[str] = []
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


def _write_executable(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o755)


def _write_delivery_launcher(delivery_dir: Path) -> Path:
    launcher = delivery_dir / DELIVERY_LAUNCHER
    _write_executable(
        launcher,
        [
            *portable_sciplot_prelude(directory_var="DELIVERY_DIR"),
            "",
            'documents=("${DELIVERY_DIR}"/project/*.vsz(N))',
            'if (( ${#documents[@]} == 0 )); then',
            '  die "No Veusz project files found in ${DELIVERY_DIR}/project"',
            "fi",
            'if [[ "${1:-}" == "--check" ]]; then',
            '  for DOCUMENT in "${documents[@]}"; do',
            '    "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke',
            "  done",
            "  exit 0",
            "fi",
            'if (( $# > 0 )); then',
            '  DOCUMENT="$1"',
            '  [[ "${DOCUMENT}" = /* ]] || DOCUMENT="${DELIVERY_DIR}/project/${DOCUMENT}"',
            "elif (( ${#documents[@]} == 1 )); then",
            '  DOCUMENT="${documents[1]}"',
            "else",
            '  print "Select a figure to edit in Veusz:"',
            '  for index in {1..${#documents[@]}}; do',
            '    print "${index}) ${documents[$index]:t:r}"',
            "  done",
            '  while true; do',
            '    read "choice?> "',
            '    if [[ "${choice}" = <-> ]] && (( choice >= 1 && choice <= ${#documents[@]} )); then',
            '      DOCUMENT="${documents[$choice]}"',
            "      break",
            "    fi",
            '    print -u2 "Enter a number from 1 to ${#documents[@]}."',
            "  done",
            "fi",
            'if [[ ! -f "${DOCUMENT}" ]]; then',
            '  print -u2 "Veusz document not found: ${DOCUMENT}"',
            "  exit 1",
            "fi",
            'if [[ "${SCIPLOT_LAUNCH_DRY_RUN:-0}" == "1" ]]; then',
            '  print -r -- "${DOCUMENT}"',
            "  exit 0",
            "fi",
            'exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --advanced-editor',
        ],
    )
    return launcher


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
        hash_matches_export = bool(
            source_hash
            and delivery_hash
            and source_hash == delivery_hash
            and (not expected_hash or delivery_hash == expected_hash)
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


def build_minimal_user_delivery(
    destination: Path,
    *,
    figures: list[tuple[str, Path]],
    data_files: list[tuple[str, Path]],
    veusz_documents: list[tuple[str, Path]],
) -> dict[str, Any]:
    """Build the same four-group handoff used by the normal export path."""

    resolved_destination = destination.expanduser().resolve()
    if resolved_destination.exists():
        shutil.rmtree(resolved_destination)
    data_dir = resolved_destination / DELIVERY_DATA_DIR
    pdf_dir = resolved_destination / DELIVERY_PDF_DIR
    tiff_dir = resolved_destination / DELIVERY_TIFF_DIR
    project_dir = resolved_destination / DELIVERY_PROJECT_DIR
    for directory in (data_dir, pdf_dir, tiff_dir, project_dir):
        directory.mkdir(parents=True, exist_ok=True)

    def copy_named(
        records: list[tuple[str, Path]],
        target_dir: Path,
        *,
        allowed_suffixes: set[str] | None = None,
    ) -> list[Path]:
        copied: list[Path] = []
        used_names: set[str] = set()
        for name, source in records:
            if not name or Path(name).name != name:
                raise ValueError(f"Minimal delivery artifact needs a plain filename: {name!r}")
            if allowed_suffixes is not None and Path(name).suffix.casefold() not in allowed_suffixes:
                suffixes = ", ".join(sorted(allowed_suffixes))
                raise ValueError(f"Minimal delivery artifact {name!r} must use one of: {suffixes}")
            if name in used_names:
                raise ValueError(f"Duplicate minimal delivery filename: {name}")
            resolved_source = source.expanduser().resolve()
            if not resolved_source.is_file():
                raise FileNotFoundError(resolved_source)
            destination_path = target_dir / name
            shutil.copy2(resolved_source, destination_path)
            copied.append(destination_path)
            used_names.add(name)
        return copied

    copied_pdf = copy_named(
        [(name, path) for name, path in figures if path.suffix.casefold() == ".pdf"],
        pdf_dir,
        allowed_suffixes={".pdf"},
    )
    copied_tiff = copy_named(
        [(name, path) for name, path in figures if path.suffix.casefold() in {".tif", ".tiff"}],
        tiff_dir,
        allowed_suffixes={".tif", ".tiff"},
    )
    copied_data = copy_named(data_files, data_dir, allowed_suffixes={".csv"})
    copied_documents = copy_named(veusz_documents, project_dir, allowed_suffixes={".vsz"})
    if not copied_documents:
        raise ValueError("Minimal delivery needs at least one editable Veusz document.")
    launcher = _write_delivery_launcher(resolved_destination)
    return {
        "kind": "sciplot_user_delivery_package",
        "version": 3,
        "root": str(resolved_destination),
        "pdf": [str(path) for path in copied_pdf],
        "tiff": [str(path) for path in copied_tiff],
        "data": [str(path) for path in copied_data],
        "project": [str(path) for path in copied_documents],
        "launcher": str(launcher),
        "file_count": len(copied_pdf) + len(copied_tiff) + len(copied_data) + len(copied_documents) + 1,
    }


def build_delivery_package(output_dir: Path, *, manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the small user-facing delivery surface.

    Internal manifests, QA reports, raw archives, analysis tables, and
    provenance stay in the run output.  They are intentionally not copied
    into ``delivery/``.
    """

    output_dir = output_dir.expanduser().resolve()
    delivery_dir = output_dir / DELIVERY_DIR
    if delivery_dir.exists():
        shutil.rmtree(delivery_dir)
    data_dir = delivery_dir / DELIVERY_DATA_DIR
    pdf_dir = delivery_dir / DELIVERY_PDF_DIR
    tiff_dir = delivery_dir / DELIVERY_TIFF_DIR
    project_dir = delivery_dir / DELIVERY_PROJECT_DIR
    for directory in (data_dir, pdf_dir, tiff_dir, project_dir):
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
    launcher = _write_delivery_launcher(delivery_dir)
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
            "exists": launcher.exists() and bool(project_records),
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
        "version": 3,
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
        "editable": str(project_dir),
        "editable_vsz": editable_vsz,
        "editable_vsz_projects": project_records,
        "artifacts": artifact_status,
    }
    delivery_record["complete"] = all(item["exists"] for item in artifact_status)

    one_step = manifest.get("one_step")
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
    return delivery_record


__all__ = ["build_delivery_package"]
