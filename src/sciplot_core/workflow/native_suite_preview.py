"""Prepare exact single-figure candidates inside the existing suite transaction."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.workflow.native_suite_objects import selected_spec
from sciplot_core.workflow.native_suite_storage import save_operation
from sciplot_core.workflow.rheology_tts_style_storage import check_snapshot, snapshot
from sciplot_core.workflow.rheology_tts_tables import write_json


def baseline_files(context: dict[str, Any]) -> dict[str, Any]:
    workspace, delivery = Path(context["workspace"]), Path(context["delivery"])
    spec, _ = selected_spec(context)
    paths = [workspace / "suite.json", delivery / "data/delivery_manifest.json", spec,
             Path(context["plot"]), *(Path(source["path"]) for source in context["manifest"]["sources"])]
    paths.extend(path for path in [workspace / "figure_plan.json", delivery / "data/figure_plan.json",
        workspace / "analysis.json", delivery / "data/analysis.json",
        *(Path(name) for name in context["document"]["exports"])] if path.exists() or path.is_symlink())
    return snapshot(paths)


def prepare_preview(context: dict[str, Any], record: dict[str, Any], path: Path) -> dict[str, Any]:
    from sciplot_core.rheology_tts_render import export_tts_document, patch_tts_display
    from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities

    directory = path.parent
    check_snapshot(record["baseline"], label="native display baseline")
    _, figure = selected_spec(context)
    edit_path = directory / "native_edit.json"
    if edit_path.exists():
        edit = json.loads(edit_path.read_text(encoding="utf-8"))
        if (edit["source_document"] != context["plot"]
                or edit["source_document_sha256"] != record["before_native_sha256"]
                or file_sha256(Path(edit["document"])) != edit["document_sha256"]):
            raise ValueError("Saved native display candidate changed; preserve and reject this operation.")
    else:
        candidate = directory / "native" / Path(context["plot"]).name
        edit = patch_tts_display(Path(context["plot"]), candidate, figure,
                                  record["native_changes"], record["before_native_sha256"])
        write_json(edit_path, edit)
    export_path = directory / "export_result.json"
    if export_path.exists():
        exported = json.loads(export_path.read_text(encoding="utf-8"))
        check_snapshot({item["path"]: item["sha256"] for item in exported["exports"]},
                       label="native display export candidate")
    else:
        exported = export_tts_document(Path(edit["document"]),
            directory / "export_attempts" / uuid4().hex / context["figure_id"], figure)
        write_json(export_path, exported)
    if exported["document_sha256"] != edit["document_sha256"]:
        raise ValueError("Native display candidate changed during export.")
    check_snapshot(record["baseline"], label="native display baseline")
    manifest = context["manifest"]
    specs = manifest.get("presentation_revision", {}).get("figures") or manifest["native_result"]["figures"]
    preview = {"kind": "sciplot_native_display_preview", "version": 1,
        "workspace": context["workspace"], "delivery": context["delivery"], "sources": manifest["sources"],
        "contract_sha256": rheology_capabilities()["contract_sha256"], "baseline": record["baseline"],
        "candidate_files": snapshot([Path(edit["document"]), edit_path, export_path,
                                    *(Path(item["path"]) for item in exported["exports"])]),
        "figures": deepcopy(specs), "candidates": [{"id": context["figure_id"], "edit": edit, "export": exported}],
        "presentation_plan": {}, "status": "preview_ready"}
    preview_path = directory / "preview.json"
    write_json(preview_path, preview)
    (directory / "preview.sha256").write_text(canonical_json_sha256(preview), encoding="ascii")
    record.update(phase="needs_review", preview=str(preview_path),
                  preview_png=next(item["path"] for item in exported["exports"] if item["format"] == "png_300"))
    record.pop("error", None)
    save_operation(path, record)
    return record
