"""Prepare exact single-figure candidates inside the existing suite transaction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.workflow.native_suite_objects import selected_spec
from sciplot_core.workflow.rheology_tts_style_storage import check_snapshot, snapshot
from sciplot_core.workflow.rheology_tts_suite import _figure_folder


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


def check_acceptance(context: dict[str, Any], record: dict[str, Any], path: Path) -> None:
    """Require current reviewed evidence before durably accepting its mutation."""
    from sciplot_core.studio_core.source_update_commit import reject_symlink_path
    from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities
    from sciplot_core.workflow.rheology_tts_suite import _check_sources

    preview_path = path.parent / "preview.json"
    reject_symlink_path(preview_path)
    seal_path = path.parent / "preview.sha256"
    reject_symlink_path(seal_path)
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    if (record["preview"] != str(preview_path) or canonical_json_sha256(preview) != seal_path.read_text(encoding="ascii")
            or preview.get("kind") != "sciplot_native_display_preview" or preview.get("workspace") != context["workspace"]
            or preview.get("delivery") != context["delivery"] or preview.get("baseline") != record["baseline"]
            or preview.get("contract_sha256") != rheology_capabilities()["contract_sha256"]):
        raise ValueError("Native display acceptance evidence changed; inspect a current preview.")
    _check_sources(record["sources"])
    check_snapshot(record["baseline"], label="presentation baseline")
    check_snapshot(preview["candidate_files"], label="presentation candidate")
