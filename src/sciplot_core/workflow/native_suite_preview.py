"""Prepare exact single-figure candidates inside the existing suite transaction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import PreparedFile
from sciplot_core.workflow.native_suite_generation import candidate_file, canonical_sha
from sciplot_core.workflow.native_suite_objects import selected_spec
from sciplot_core.workflow.rheology_tts_style_storage import check_snapshot, snapshot
from sciplot_core.workflow.rheology_tts_saved_state import _figure_folder


def baseline_files(context: dict[str, Any]) -> dict[str, Any]:
    workspace, delivery = Path(context["workspace"]), Path(context["delivery"])
    spec, _ = selected_spec(context)
    paths = [workspace / "suite.json", delivery / "data/delivery_manifest.json", spec,
             Path(context["plot"]), *(Path(source["path"]) for source in context["manifest"]["sources"])]
    paths.extend(path for path in [workspace / "figure_plan.json", delivery / "data/figure_plan.json",
        workspace / "analysis.json", delivery / "data/analysis.json",
        _figure_folder(delivery, context["figure_id"]) / f"{context['figure_id']}.native-audit.json",
        *(Path(name) for name in context["document"]["exports"])] if path.exists() or path.is_symlink())
    return snapshot(paths)


@dataclass(frozen=True)
class LegacyCandidate:
    preview: dict[str, Any]
    native: PreparedFile
    png: PreparedFile
    evidence: dict[Path, PreparedFile]


def read_candidate(context: dict[str, Any], record: dict[str, Any], path: Path) -> LegacyCandidate:
    """Freeze one confined legacy candidate for either pending import route."""
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path
    from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities
    from sciplot_core.workflow.rheology_tts_saved_state import _check_sources

    preview_path = path.parent / "preview.json"
    reject_symlink_path(preview_path)
    seal_path = path.parent / "preview.sha256"
    reject_symlink_path(seal_path)
    record_bytes = path.read_bytes()
    preview_bytes, seal_bytes = preview_path.read_bytes(), seal_path.read_bytes()
    preview = json.loads(preview_bytes)
    if (record["preview"] != str(preview_path) or canonical_json_sha256(preview) != seal_path.read_text(encoding="ascii")
            or preview.get("kind") != "sciplot_native_display_preview" or preview.get("workspace") != context["workspace"]
            or preview.get("delivery") != context["delivery"] or preview.get("baseline") != record["baseline"]
            or preview.get("contract_sha256") != rheology_capabilities()["contract_sha256"]
            or preview.get("sources") != record["sources"] or json.loads(record_bytes) != record):
        raise ValueError("Native display acceptance evidence changed; inspect a current preview.")
    _check_sources(record["sources"])
    files = preview["candidate_files"]
    if any(not Path(name).is_absolute() or str(Path(name)) != name or ".." in Path(name).parts
           or not Path(name).is_relative_to(path.parent) for name in files):
        raise ValueError("Legacy candidate evidence must remain in its exact canonical private directory.")
    candidates = preview.get("candidates", [])
    if len(candidates) != 1 or candidates[0]["id"] != context["figure_id"]:
        raise ValueError("Legacy candidate must bind exactly the selected figure.")
    edit, exported = candidates[0]["edit"], candidates[0]["export"]
    native, digest = exported["document"], exported["document_sha256"]
    if (native not in files or files[native] != digest or edit.get("document") != native
            or edit.get("document_sha256") != digest):
        raise ValueError("Legacy candidate native bytes lack their exact sealed binding.")
    exports = exported["exports"]
    if len(exports) != 3 or {item["format"] for item in exports} != {"pdf", "tiff_300", "png_300"}:
        raise ValueError("Legacy candidate requires its complete exact export set.")
    for item in exports:
        if item["path"] not in files or files[item["path"]] != item["sha256"]:
            raise ValueError("Legacy candidate export is outside its sealed file set.")
    png = next(item["path"] for item in exports if item["format"] == "png_300")
    if record.get("preview_png") != png:
        raise ValueError("Legacy preview PNG is not the exact confined candidate export.")
    hashes = {**files, str(path): canonical_sha(record_bytes), str(preview_path): canonical_sha(preview_bytes),
              str(seal_path): canonical_sha(seal_bytes)}
    frozen = {Path(name): candidate_file(Path(name), sha) for name, sha in hashes.items()}
    if frozen[seal_path].data.decode() != canonical_json_sha256(preview):
        raise ValueError("Legacy preview seal changed while being frozen.")
    return LegacyCandidate(preview, frozen[Path(native)], frozen[Path(png)], frozen)


def check_acceptance(context: dict[str, Any], record: dict[str, Any], path: Path) -> None:
    """Require current reviewed evidence before durably accepting its mutation."""
    read_candidate(context, record, path)
    check_snapshot(record["baseline"], label="presentation baseline")
