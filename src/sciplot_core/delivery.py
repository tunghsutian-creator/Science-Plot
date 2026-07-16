from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._paths import REPO_ROOT
from sciplot_core._utils import existing_file_sha256, json_safe, read_json_object, slug
from sciplot_core.assisted_cleanup import CLEANUP_REQUEST_FILENAME, CLEANUP_RESULT_FILENAME
from sciplot_core.policy import (
    DELIVERY_DIR,
    DELIVERY_EDITABLE_DIR,
    DELIVERY_FIGURES_DIR,
    DELIVERY_INTERNAL_DIR,
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
    actual_hash = existing_file_sha256(candidate)
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
        candidate = f"figure_{index:02d}"
    return slug(candidate)


def _write_executable(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o755)


def build_minimal_user_delivery(
    destination: Path,
    *,
    figures: list[tuple[str, Path]],
    data_files: list[tuple[str, Path]],
    veusz_documents: list[tuple[str, Path]],
) -> dict[str, Any]:
    """Build a deliberately small handoff: figures, data, VSZs, one launcher.

    The ordinary delivery package remains the provenance-complete contract.
    This helper is for an explicitly curated user handoff where QA records,
    manifests, specs, logs, and per-document launchers would be clutter.
    """
    resolved_destination = destination.expanduser().resolve()
    if resolved_destination.exists():
        shutil.rmtree(resolved_destination)
    figures_dir = resolved_destination / "figures"
    data_dir = resolved_destination / "data"
    veusz_dir = resolved_destination / "veusz"
    for directory in (figures_dir, data_dir, veusz_dir):
        directory.mkdir(parents=True, exist_ok=True)

    def copy_named(records: list[tuple[str, Path]], target_dir: Path) -> list[Path]:
        copied: list[Path] = []
        used_names: set[str] = set()
        for name, source in records:
            if not name or Path(name).name != name:
                raise ValueError(f"Minimal delivery artifact needs a plain filename: {name!r}")
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

    copied_figures = copy_named(figures, figures_dir)
    copied_data = copy_named(data_files, data_dir)
    copied_documents = copy_named(veusz_documents, veusz_dir)
    if not copied_documents:
        raise ValueError("Minimal delivery needs at least one editable Veusz document.")

    launcher = resolved_destination / "Open_in_Veusz.command"
    _write_executable(
        launcher,
        [
            "#!/bin/zsh",
            "set -euo pipefail",
            'DELIVERY_DIR="${0:A:h}"',
            "unset QT_QPA_PLATFORM || true",
            'documents=("${DELIVERY_DIR}"/veusz/*.vsz(N))',
            'if (( ${#documents[@]} == 0 )); then',
            '  print -u2 "No Veusz documents found in ${DELIVERY_DIR}/veusz"',
            "  exit 1",
            "fi",
            'if (( $# > 0 )); then',
            '  DOCUMENT="$1"',
            '  [[ "${DOCUMENT}" = /* ]] || DOCUMENT="${DELIVERY_DIR}/veusz/${DOCUMENT}"',
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
            f'cd "{REPO_ROOT}"',
            'exec skill/scripts/sciplot studio "${DOCUMENT}" --advanced-editor',
        ],
    )
    return {
        "kind": "sciplot_minimal_user_delivery",
        "root": str(resolved_destination),
        "figures": [str(path) for path in copied_figures],
        "data": [str(path) for path in copied_data],
        "veusz_documents": [str(path) for path in copied_documents],
        "launcher": str(launcher),
        "file_count": len(copied_figures) + len(copied_data) + len(copied_documents) + 1,
    }


def _write_editable_launchers(project_dir: Path) -> tuple[Path, Path, Path]:
    open_veusz = project_dir / "Open_in_Veusz.command"
    export_edited = project_dir / "Export_Edited_Veusz.command"
    open_studio = project_dir / "Open_in_SciPlot_Studio.command"
    shared = [
        "#!/bin/zsh",
        "set -euo pipefail",
        'PROJECT_DIR="${0:A:h}"',
        "unset QT_QPA_PLATFORM || true",
        f'cd "{REPO_ROOT}"',
    ]
    _write_executable(
        open_veusz,
        [*shared, 'exec skill/scripts/sciplot studio "${PROJECT_DIR}/studio/document.vsz" --advanced-editor'],
    )
    _write_executable(
        export_edited,
        [*shared, 'skill/scripts/sciplot studio "${PROJECT_DIR}" --export pdf,tiff_300 --json'],
    )
    _write_executable(open_studio, [*shared, 'skill/scripts/sciplot studio "${PROJECT_DIR}"'])
    return open_veusz, export_edited, open_studio


def _copy_editable_request(
    source_root: Path,
    destination: Path,
    *,
    manifest: dict[str, Any],
    output_dir: Path,
) -> tuple[Path, str | None]:
    candidates = [source_root / "plot_request.json"]
    request_value = manifest.get("request_path")
    if isinstance(request_value, str) and request_value.strip():
        candidates.append(Path(request_value).expanduser())
    candidates.append(output_dir / "request_snapshot.json")
    request: dict[str, Any] = {}
    for candidate in candidates:
        payload = read_json_object(candidate)
        if payload is not None:
            request = payload
            break
    copied_data: str | None = None
    input_value = request.get("input")
    if isinstance(input_value, str) and input_value.strip():
        source = Path(input_value).expanduser()
        if not source.is_absolute():
            source = source_root / source
        if source.exists() and source.is_file():
            data_dir = destination / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            data_path = data_dir / source.name
            shutil.copy2(source, data_path)
            copied_data = str(data_path)
            request["input"] = str(data_path.relative_to(destination))
    request.setdefault("template", "curve")
    request["output"] = "."
    request_path = destination / "plot_request.json"
    request_path.write_text(json.dumps(json_safe(request), indent=2, ensure_ascii=False), encoding="utf-8")
    return request_path, copied_data


def _copy_editable_veusz_projects(
    manifest: dict[str, Any],
    *,
    output_dir: Path,
    editable_dir: Path,
) -> list[dict[str, Any]]:
    documents = _manifest_veusz_documents(manifest, output_dir)
    if not documents:
        return []
    editable_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for index, source_document in enumerate(documents, start=1):
        base_name = _editable_project_name(source_document, index=index)
        name = base_name
        suffix = 2
        while name in used_names:
            name = f"{base_name}_{suffix}"
            suffix += 1
        used_names.add(name)
        destination = editable_dir / name
        studio_dir = destination / "studio"
        studio_dir.mkdir(parents=True, exist_ok=True)
        document = studio_dir / "document.vsz"
        shutil.copy2(source_document, document)
        source_spec = source_document.parent / "spec.json"
        spec = studio_dir / "spec.json"
        if source_spec.exists():
            shutil.copy2(source_spec, spec)
        source_root = source_document.parent.parent
        request_path, copied_data = _copy_editable_request(
            source_root,
            destination,
            manifest=manifest,
            output_dir=output_dir,
        )
        source_hash = existing_file_sha256(source_document)
        delivery_hash = existing_file_sha256(document)
        intake_manifest = {
            "kind": "sciplot_editable_delivery_project",
            "version": 1,
            "project": name,
            "request": str(request_path.relative_to(destination)),
            "studio": {
                "engine": "veusz",
                "document": str(document.relative_to(destination)),
                "spec": str(spec.relative_to(destination)) if spec.exists() else None,
                "generated_hash": delivery_hash,
                "export_exact_current_document": True,
            },
        }
        (destination / "intake_manifest.json").write_text(
            json.dumps(json_safe(intake_manifest), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        open_veusz, export_edited, open_studio = _write_editable_launchers(destination)
        records.append(
            {
                "kind": "sciplot_delivery_editable_vsz_project",
                "id": name,
                "path": str(destination),
                "relative_path": str(destination.relative_to(editable_dir.parent)),
                "document": str(document),
                "document_relative_path": str(document.relative_to(editable_dir.parent)),
                "request": str(request_path),
                "data": copied_data,
                "open_in_veusz": str(open_veusz),
                "export_edited": str(export_edited),
                "open_in_sciplot_studio": str(open_studio),
                "source_document": str(source_document),
                "source_sha256": source_hash,
                "delivery_sha256": delivery_hash,
                "copy_hash_matches": bool(source_hash and source_hash == delivery_hash),
            }
        )
    readme = editable_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# Editable Veusz projects",
                "",
                "Each folder is a self-contained SciPlot/Veusz project for one delivered figure.",
                "",
                "1. Double-click `Open_in_Veusz.command` to edit the real `.vsz` document.",
                "2. Save inside Veusz.",
                "3. Double-click `Export_Edited_Veusz.command` to export that exact saved document through SciPlot QA.",
                "",
                "The export command never regenerates the plot from Python or replaces the saved Veusz document.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return records


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
    editable_dir = delivery_dir / DELIVERY_EDITABLE_DIR
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
        source_hash = existing_file_sha256(source)
        delivery_hash = existing_file_sha256(destination)
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
    editable_vsz_projects = _copy_editable_veusz_projects(
        manifest,
        output_dir=output_dir,
        editable_dir=editable_dir,
    )

    delivery_record = {
        "kind": "sciplot_minimal_delivery_package",
        "version": 2,
        "path": str(delivery_dir),
        "project": project,
        "project_file": str(sciplot_path),
        "excel_data": str(data_path) if data_path.exists() else None,
        "figures": figure_records,
        "internal": str(internal_dir),
        "internal_artifacts": copied_internal,
        "editable_vsz": editable_vsz,
        "editable": str(editable_dir) if editable_vsz_projects else None,
        "editable_vsz_projects": editable_vsz_projects,
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
            parsed = read_json_object(artifact_path)
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
                        isinstance(parsed, dict) and parsed.get("kind") == PUBLICATION_ARTIFACT_KINDS[filename]
                    ),
                }
            )
        copied_ledger = parsed_publication_artifacts.get("transform_ledger.json")
        artifact_status.append(
            {
                "id": "transform_lineage_reviewed",
                "path": str(internal_dir / "transform_ledger.json"),
                "exists": bool(
                    isinstance(copied_ledger, dict) and copied_ledger.get("status") in {"runtime_recorded", "confirmed"}
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
    if editable_vsz_projects:
        artifact_status.extend(
            [
                {
                    "id": "editable_vsz_projects",
                    "path": str(editable_dir),
                    "exists": all(Path(str(item["document"])).exists() for item in editable_vsz_projects),
                    "details": editable_vsz_projects,
                },
                {
                    "id": "editable_vsz_project_hashes_match",
                    "path": str(editable_dir),
                    "exists": all(bool(item["copy_hash_matches"]) for item in editable_vsz_projects),
                },
                {
                    "id": "editable_vsz_launchers",
                    "path": str(editable_dir),
                    "exists": all(
                        Path(str(item[key])).exists()
                        for item in editable_vsz_projects
                        for key in ("open_in_veusz", "export_edited", "open_in_sciplot_studio")
                    ),
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
