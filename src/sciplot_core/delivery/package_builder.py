"""Build the minimal user-facing delivery package."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.manifest_gate import figure_plan_manifest_gate
from sciplot_core.figure_plan.plan import resolved_figure_plan_from_payload
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.launchers import (
    inspect_delivery_launcher_contract,
    write_delivery_launcher,
)
from sciplot_core.output_contract import requested_delivery_root
from sciplot_core.plot_data import build_plot_data_exports
from sciplot_core.policy import (
    DELIVERY_DATA_DIR,
    DELIVERY_LAUNCHER,
    DELIVERY_PDF_DIR,
    DELIVERY_PROJECT_DIR,
    DELIVERY_TIFF_DIR,
)

from sciplot_core.delivery.contracts import (
    DELIVERY_BINDING_POLICY_LEGACY,
    DELIVERY_BINDING_POLICY_RESOLVED_PLAN,
    DELIVERY_PACKAGE_CONTRACT_VERSION,
    _project_slug,
)

from sciplot_core.delivery.figure_pairing import (
    _delivery_figure_pairing,
)

from sciplot_core.delivery.project_documents import (
    _copy_project_documents,
)

from sciplot_core.delivery.publication_evidence import (
    _qa_hash_evidence,
    _publication_status,
)

from sciplot_core.delivery.package_validation import (
    verify_delivery_package,
)
from sciplot_core.delivery.plan_binding import plan_source_figure_ids


def build_delivery_package(
    output_dir: Path, *, manifest: dict[str, Any]
) -> dict[str, Any]:
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
    figure_ids_by_path = _figure_ids_by_path(manifest)
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
                "figure_id": figure_ids_by_path.get(str(source.resolve())),
                "source_sha256": source_hash,
                "delivery_sha256": delivery_hash,
                "copy_hash_matches": bool(source_hash and source_hash == delivery_hash),
                "exists": destination.exists(),
            }
        )

    data_records = build_plot_data_exports(manifest, destination=data_dir)
    project_records = _copy_project_documents(
        manifest, output_dir=output_dir, project_dir=project_dir
    )
    launcher = write_delivery_launcher(delivery_dir)
    launcher_contract = inspect_delivery_launcher_contract(delivery_dir)
    figure_pairing = _delivery_figure_pairing(figure_records)
    qa_hash_evidence = _qa_hash_evidence(manifest, figure_records)
    qa_hashes_match = bool(qa_hash_evidence) and all(
        item["qa_sha256"]
        and item["qa_sha256"] == item["source_sha256"] == item["delivery_sha256"]
        for item in qa_hash_evidence
    )
    project_files_exist = bool(project_records) and all(
        item["exists"] for item in project_records
    )
    data_files_exist = bool(data_records) and all(
        Path(str(item["path"])).exists() for item in data_records
    )
    qa_value = manifest.get("qa")
    qa_payload = qa_value if isinstance(qa_value, dict) else {}
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
            "exists": launcher_contract.get("ready") is True and bool(project_records),
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
                "path": str(project_dir),
                "exists": all(
                    bool(record["hash_matches_export"]) for record in project_records
                ),
                "details": project_records,
            }
        )
    if publication_present:
        artifact_status.extend(publication_status)
        publication_intent_value = manifest.get("publication_intent")
        publication_intent = (
            publication_intent_value
            if isinstance(publication_intent_value, dict)
            else {}
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
    plan_gate = figure_plan_manifest_gate(manifest)
    if plan_gate is not None:
        delivered_ids = set(figure_pairing["complete_figure_ids"])
        selected_ids = set(plan_gate["selected_figure_ids"])
        project_figure_ids = [
            str(item.get("figure_id") or "").strip() for item in project_records
        ]
        plan_delivery_complete = bool(
            plan_gate["valid"] is True
            and plan_gate["complete"] is True
            and figure_pairing["passed"] is True
            and delivered_ids == selected_ids
            and not figure_pairing["unidentified_paths"]
            and len(project_figure_ids) == len(selected_ids)
            and all(project_figure_ids)
            and set(project_figure_ids) == selected_ids
        )
        artifact_status.append(
            {
                "id": "resolved_figure_plan_complete",
                "path": str(output_dir / "manifest.json"),
                "exists": plan_delivery_complete,
                "details": {
                    **plan_gate,
                    "delivered_figure_ids": sorted(delivered_ids),
                    "editable_project_figure_ids": sorted(project_figure_ids),
                },
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
            "expected_hash": manifest.get("exported_document_hash")
            or first["source_sha256"],
            "actual_hash": first["delivery_sha256"],
            "hash_matches_export": first["hash_matches_export"],
        }
    delivery_record: dict[str, Any] = {
        "kind": "sciplot_user_delivery_package",
        "version": DELIVERY_PACKAGE_CONTRACT_VERSION,
        "binding_policy": (
            DELIVERY_BINDING_POLICY_RESOLVED_PLAN
            if plan_gate is not None
            else DELIVERY_BINDING_POLICY_LEGACY
        ),
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
    if plan_gate is not None:
        delivery_record["resolved_figure_plan"] = manifest.get("resolved_figure_plan")
    delivery_record["complete"] = all(item["exists"] for item in artifact_status)
    verification = verify_delivery_package(
        delivery_record,
        expected_root=delivery_dir,
        expected_manifest=manifest,
    )
    delivery_record["verification"] = verification
    delivery_record["complete"] = bool(
        delivery_record["complete"] and verification["passed"]
    )

    return delivery_record


def _figure_ids_by_path(manifest: dict[str, Any]) -> dict[str, str]:
    result_value = manifest.get("result")
    result = result_value if isinstance(result_value, dict) else {}
    plan = resolved_figure_plan_from_payload(manifest.get("resolved_figure_plan"))
    single_id = (
        plan.tasks[0].figure_id if plan is not None and len(plan.tasks) == 1 else None
    )
    values: dict[str, str] = {}
    if plan is not None:
        values = {
            path: figure_id
            for path, figure_id in plan_source_figure_ids(plan).items()
            if Path(path).suffix.casefold() in {".pdf", ".tif", ".tiff"}
        }
    for item in result.get("exports", []):
        if not isinstance(item, dict):
            continue
        path_value = item.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            continue
        if Path(path_value).suffix.casefold() not in {".pdf", ".tif", ".tiff"}:
            continue
        figure_id = str(item.get("figure_id") or single_id or "").strip()
        if plan is not None and figure_id == "primary":
            figure_id = plan.primary_figure_id
        resolved_path = str(Path(path_value).expanduser().resolve())
        if plan is None:
            if figure_id:
                values[resolved_path] = figure_id
            continue
        expected_figure_id = values.get(resolved_path)
        if expected_figure_id is None:
            raise ValueError(
                "Renderer export is not bound to a selected FigureOutcome: "
                f"{resolved_path}"
            )
        if figure_id and figure_id != expected_figure_id:
            raise ValueError(
                "Renderer export figure_id conflicts with the resolved outcome: "
                f"{resolved_path}"
            )
    return values
