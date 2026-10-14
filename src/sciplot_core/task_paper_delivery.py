"""Assemble selected single figures through the existing delivery transaction."""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.delivery.contracts import DELIVERY_BINDING_POLICY_LEGACY, DELIVERY_PACKAGE_CONTRACT_VERSION
from sciplot_core.delivery.package_transaction import publish_delivery_transaction, _relocate_record
from sciplot_core.delivery.package_validation import verify_delivery_package
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.launchers import write_delivery_launcher, inspect_delivery_launcher_contract
from sciplot_core.plot_data.exports import build_plot_data_exports
from sciplot_core.policy import DELIVERY_DATA_DIR, DELIVERY_PDF_DIR, DELIVERY_TIFF_DIR, DELIVERY_PROJECT_DIR
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_paper_sources import assert_selection_current


def assert_sealed_item(item: dict[str, Any]) -> None:
    root = Path(item["attempt"])
    if file_inventory(root) != item["files"]:
        raise TaskControlError("paper_stage_changed", "A sealed selected-figure staging directory changed; preserve it and inspect.")


def paper_manifest(state: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "sciplot_paper_figure_manifest", "version": 1, "title": state["request"]["title"],
            "items": [{"order": index, "label": request["label"], "stem": item["stem"],
                       "project": source["project"], "figure_id": source["figure_id"],
                       "version": source["version"], "source_files": source["source_files"],
                       "source_memberships": source["source_memberships"],
                       "source_scope": source["source_scope"], "document_authority": source["document_authority"],
                       "scientific_sha256": item["scientific_sha256"],
                       "prepared_source_sha256": item["prepared_source_sha256"],
                       "portable_native": item["portable_native"],
                       "pdf": f"{DELIVERY_PDF_DIR}/{item['stem']}.pdf", "tiff": f"{DELIVERY_TIFF_DIR}/{item['stem']}_300dpi.tiff",
                       "editable": f"project/{item['stem']}.vsz"}
                      for index, (request, source, item) in enumerate(
                          zip(state["request"]["items"], state["selections"], state["items"], strict=True), 1)],
            "publication_readiness_evaluated": False, "journal_acceptance_evaluated": False}


def publish_paper(root: Path, state: dict[str, Any], *, checkpoint: Callable[[], None]) -> dict[str, Any]:
    destination = Path(state["request"]["out"])
    if destination.exists():
        raise TaskControlError("paper_output_exists", "The requested paper output already exists; no files were replaced.")
    manifest = paper_manifest(state)

    def build(stage: Path) -> dict[str, Any]:
        for folder in {DELIVERY_PDF_DIR, DELIVERY_TIFF_DIR, DELIVERY_PROJECT_DIR, DELIVERY_DATA_DIR}:
            (stage / folder).mkdir()
        figures = []
        documents = []
        data_records = []
        for source, item in zip(state["selections"], state["items"], strict=True):
            assert_selection_current(source)
            assert_sealed_item(item)
            attempt = Path(item["attempt"])
            stem = item["stem"]
            for folder, suffix, export_format in ((DELIVERY_PDF_DIR, ".pdf", "pdf"), (DELIVERY_TIFF_DIR, "_300dpi.tiff", "tiff_300")):
                original = Path(next(export["path"] for export in item["exports"]["exports"] if export["format"] == export_format))
                target = stage / folder / f"{stem}{suffix}"
                shutil.copy2(original, target)
                figures.append({"path": str(target), "relative_path": f"{folder}/{target.name}",
                                "figure_id": stem, "export_format": export_format,
                                "format": "pdf" if export_format == "pdf" else "tiff", "source": str(original), "source_sha256": file_sha256(original),
                                "delivery_sha256": file_sha256(target), "copy_hash_matches": True, "exists": True})
            original = attempt / "project" / f"{stem}.vsz"
            target = stage / "project" / original.name
            shutil.copy2(original, target)
            shutil.copy2(attempt / "project" / f"{stem}.spec.json", target.with_suffix(".spec.json"))
            imports = attempt / "data" / "imports" / stem
            if imports.is_dir():
                shutil.copytree(imports, stage / "data" / "imports" / stem)
            documents.append({"path": str(target), "relative_path": f"project/{target.name}",
                              "figure_id": stem, "source": str(original), "format": "vsz",
                              "source_sha256": file_sha256(original), "delivery_sha256": file_sha256(target),
                              "expected_sha256": file_sha256(original), "hash_matches_export": True, "exists": True})
            data_records.extend(build_plot_data_exports(
                {"project": stem, "veusz_documents": [str(target)]}, destination=stage / "data"))
        manifest_file = stage / "data" / "figure_sources.json"
        manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        sources_csv = stage / "data" / "figure_sources.csv"
        with sources_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["order", "label", "project", "figure_id", "document_sha256", "spec_sha256",
                             "request_sha256", "source_sha256", "scientific_sha256", "portable_sha256"])
            for item in manifest["items"]:
                writer.writerow([item["order"], item["label"], item["project"], item["figure_id"],
                                 *[item["version"][key] for key in ("document_sha256", "spec_sha256", "request_sha256", "source_sha256")],
                                 item["scientific_sha256"], item["portable_native"]["portable_sha256"]])
        data_records.append({"path": str(sources_csv), "sha256": file_sha256(sources_csv)})
        launcher = write_delivery_launcher(stage)
        contract = inspect_delivery_launcher_contract(stage)
        for selection in state["selections"]:
            assert_selection_current(selection)
        if destination.exists():
            raise TaskControlError("paper_output_exists", "The paper output was occupied while staging; no files were replaced.")
        record = {"kind": "sciplot_user_delivery_package", "version": DELIVERY_PACKAGE_CONTRACT_VERSION,
                "binding_policy": DELIVERY_BINDING_POLICY_LEGACY, "path": str(stage), "complete": True,
                "figures": figures, "project_documents": documents, "data_csvs": data_records,
                "open_in_veusz": str(launcher), "open_in_veusz_sha256": contract["content_sha256"],
                "launcher_contract": contract, "artifacts": [{"id": "selected_sources_and_native_state",
                                                              "path": str(manifest_file), "exists": True}],
                "paper_manifest": manifest, "paper_manifest_sha256": canonical_json_sha256(manifest, allow_nan=False)}
        verification = verify_delivery_package(record, expected_root=stage, expected_manifest={})
        if verification["passed"] is not True:
            raise TaskControlError("paper_delivery_failed", f"Selected package validation failed: {verification['failed_checks']}")
        return record

    # Reuse delivery staging/validation, then the existing exclusive creation
    # installer. The replacement transaction never sees the caller's output.
    private = destination.with_name(f".{destination.name}.paper-publication-{uuid4().hex}")
    delivery = publish_delivery_transaction(root=private, output_dir=root, manifest={}, build=build)
    if delivery.get("verification", {}).get("passed") is not True:
        raise TaskControlError("paper_delivery_failed", "The selected paper package failed delivery verification.")
    final = _relocate_record(delivery, private, destination)
    state["publication_candidate"] = {"path": str(private), "files": file_inventory(private), "delivery": final}
    checkpoint()  # Freeze full candidate closure before exclusive atomic publish.
    for selection in state["selections"]:
        assert_selection_current(selection)
    from sciplot_core.delivery.install import install_new_delivery

    install_new_delivery(private, destination)
    final["verification"] = verify_delivery_package(final, expected_root=destination, expected_manifest={})
    if final["verification"]["passed"] is not True:
        raise TaskControlError("paper_delivery_failed", "Installed selected paper package failed verification; preserve and inspect.")
    return final
