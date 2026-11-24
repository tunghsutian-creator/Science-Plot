"""Assemble selected single figures through the existing delivery transaction."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.delivery import native_snapshot
from sciplot_core.delivery.contracts import DELIVERY_BINDING_POLICY_LEGACY, DELIVERY_PACKAGE_CONTRACT_VERSION
from sciplot_core.delivery.package_transaction import _relocate_record
from sciplot_core.delivery.package_validation import verify_delivery_package
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.delivery_identity import write_delivery_identity, inspect_delivery_identity, make_delivery_binding
from sciplot_core.plot_data.exports import build_plot_data_exports
from sciplot_core.policy import DELIVERY_DATA_DIR, DELIVERY_PDF_DIR, DELIVERY_TIFF_DIR, DELIVERY_PROJECT_DIR
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_paper_sources import assert_selection_current
from sciplot_core.task_paper_publication import assert_publication_current


def assert_sealed_item(item: dict[str, Any]) -> None:
    try:
        native_snapshot.require_inventory(Path(item["attempt"]), item["files"])
    except native_snapshot.SnapshotSealChanged as exc:
        raise TaskControlError("paper_stage_changed", str(exc)) from exc


def paper_manifest(state: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "sciplot_paper_figure_manifest", "version": 1, "title": state["request"]["title"],
            "items": [{"order": index, "label": request["label"], "stem": item["stem"],
                       "project": source["project"], "figure_id": source["figure_id"],
                       "version": source["version"], "source_files": source["source_files"],
                       "source_memberships": source["source_memberships"],
                       "source_scope": source["source_scope"], "document_authority": source["document_authority"],
                       "publication": source.get("publication"), "scientific_sha256": item["scientific_sha256"],
                       "prepared_source_sha256": item["prepared_source_sha256"],
                       "portable_native": item["portable_native"],
                       "pdf": f"{DELIVERY_PDF_DIR}/{item['stem']}.pdf", "tiff": f"{DELIVERY_TIFF_DIR}/{item['stem']}_300dpi.tiff",
                       "editable": f"project/{item['stem']}.vsz"}
                      for index, (request, source, item) in enumerate(
                          zip(state["request"]["items"], state["selections"], state["items"], strict=True), 1)],
            "publication_readiness_evaluated": False, "journal_acceptance_evaluated": False}


def publish_paper(state: dict[str, Any], *, checkpoint: Callable[[], None]) -> dict[str, Any]:
    destination = Path(state["request"]["out"])
    if destination.exists():
        raise TaskControlError("paper_output_exists", "The requested paper output already exists; no files were replaced.")
    manifest = paper_manifest(state)

    assembled: dict[str, str] = {}

    def build(stage: Path) -> dict[str, Any]:
        for folder in {DELIVERY_PDF_DIR, DELIVERY_TIFF_DIR, DELIVERY_PROJECT_DIR, DELIVERY_DATA_DIR}:
            (stage / folder).mkdir()
        figures = []
        documents = []
        data_records = []
        for source, item in zip(state["selections"], state["items"], strict=True):
            assert_selection_current(source)
            assert_publication_current(source["publication"], source)
            attempt = Path(item["attempt"])
            stem = item["stem"]
            editable = f"project/{stem}.vsz"
            spec = f"project/{stem}.spec.json"
            layout = {editable: editable, spec: spec, **{name: name for name in item["files"]
                                                        if name.startswith(f"data/imports/{stem}/")}}
            exports = []
            for folder, suffix, export_format in (
                (DELIVERY_PDF_DIR, ".pdf", "pdf"), (DELIVERY_TIFF_DIR, "_300dpi.tiff", "tiff_300"),
            ):
                export = next(export for export in item["exports"]["exports"] if export["format"] == export_format)
                original = Path(export["path"])
                relative = f"{folder}/{stem}{suffix}"
                name = str(original.relative_to(attempt))
                layout[name] = relative
                exports.append((name, relative, export_format))
            try:
                native_snapshot.stage_native(attempt, stage, item["files"], layout=layout,
                                             assembled=assembled, stem=stem, portable=item["portable_native"])
            except native_snapshot.SnapshotSealChanged as exc:
                raise TaskControlError("paper_stage_changed", str(exc)) from exc
            except native_snapshot.NativeSnapshotError as exc:
                raise TaskControlError("paper_native_copy_failed", str(exc)) from exc
            for name, relative, export_format in exports:
                digest = assembled[relative]
                figures.append({"path": str(stage / relative), "relative_path": relative,
                                "figure_id": stem, "export_format": export_format,
                                "format": "pdf" if export_format == "pdf" else "tiff", "source": str(attempt / name),
                                "source_sha256": digest, "delivery_sha256": digest, "copy_hash_matches": True, "exists": True})
            target = stage / editable
            digest = assembled[editable]
            documents.append({"path": str(target), "relative_path": editable,
                              "figure_id": stem, "source": str(attempt / editable), "format": "vsz",
                              "source_sha256": digest, "delivery_sha256": digest,
                              "expected_sha256": digest, "hash_matches_export": True, "exists": True})
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
        identity = write_delivery_identity(stage, binding=make_delivery_binding(root=destination, manifest={}, documents=documents))
        contract = inspect_delivery_identity(stage)
        for selection in state["selections"]:
            assert_selection_current(selection)
        if destination.exists():
            raise TaskControlError("paper_output_exists", "The paper output was occupied while staging; no files were replaced.")
        record = {"kind": "sciplot_user_delivery_package", "version": DELIVERY_PACKAGE_CONTRACT_VERSION,
                "binding_policy": DELIVERY_BINDING_POLICY_LEGACY, "path": str(stage), "complete": True,
                "figures": figures, "project_documents": documents, "data_csvs": data_records,
                "identity": str(identity), "identity_sha256": contract["content_sha256"],
                "identity_contract": contract, "artifacts": [{"id": "selected_sources_and_native_state",
                                                              "path": str(manifest_file), "exists": True}],
                "paper_manifest": manifest, "paper_manifest_sha256": canonical_json_sha256(manifest, allow_nan=False)}
        verification = verify_delivery_package(record, expected_root=stage, expected_manifest={})
        if verification["passed"] is not True:
            raise TaskControlError("paper_delivery_failed", f"Selected package validation failed: {verification['failed_checks']}")
        record["verification"] = verification
        return record

    # One exact paper candidate already sits beside its destination. There is
    # no prior visible package to stage through the replaceable Studio owner.
    private = destination.with_name(f".{destination.name}.paper-publication-{uuid4().hex}")
    private.mkdir(mode=0o700, parents=True)
    final = _relocate_record(build(private), private, destination)

    def freeze(files: dict[str, str]) -> None:
        state["publication_candidate"] = {"path": str(private), "files": files, "delivery": final}
        checkpoint()

    def validate() -> None:
        for selection in state["selections"]:
            assert_selection_current(selection)
            assert_publication_current(selection["publication"], selection)

    try:
        native_snapshot.publish_snapshot(private, destination, assembled=assembled, freeze=freeze, validate=validate)
    except native_snapshot.SnapshotSealChanged as exc:
        raise TaskControlError("paper_delivery_failed", str(exc)) from exc
    final["verification"] = verify_delivery_package(final, expected_root=destination, expected_manifest={})
    if final["verification"]["passed"] is not True:
        raise TaskControlError("paper_delivery_failed", "Installed selected paper package failed verification; preserve and inspect.")
    return final
