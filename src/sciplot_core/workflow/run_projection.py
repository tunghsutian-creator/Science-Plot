"""Pure completed-run projection; no native preparation or physical writer."""

from copy import deepcopy
from typing import Any

from sciplot_core.figure_plan import sync_figure_plan_projection


def _project_manifest_after_run(existing_project_manifest: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Derive the complete run registration without native preparation or IO."""
    project_manifest = deepcopy(existing_project_manifest)
    manifest = deepcopy(manifest)
    project_manifest["last_run"] = {
        "completed_at": manifest["created_at"],
        "output": manifest["output"],
        "figures": manifest["figures"],
        "analysis_metrics": manifest.get("result", {}).get("analysis_metrics", []),
        "qa": manifest.get("qa", {}),
        "revision_brief": manifest.get("revision_brief"),
        "package_contract": manifest.get("package_contract", {}),
        "delivery_package": manifest.get("delivery_package", {}),
        "layout_quality": manifest.get("layout_quality", {}),
        "one_step": manifest.get("one_step", {}),
        "publication_intent": manifest.get("publication_intent", {}),
        "transform_ledger": manifest.get("transform_ledger", {}),
        "journal_profile": manifest.get("journal_profile", {}),
        "publication_qa": manifest.get("publication_qa", {}),
    }
    if isinstance(manifest.get("study_model"), dict):
        project_manifest["study_model"] = manifest["study_model"]
        project_manifest["last_run"]["study_model"] = manifest["study_model"]
    if isinstance(manifest.get("package_contract"), dict):
        project_manifest["package_contract"] = manifest["package_contract"]
    if isinstance(manifest.get("layout_quality"), dict):
        project_manifest["layout_quality"] = manifest["layout_quality"]
    if isinstance(manifest.get("delivery_package"), dict):
        project_manifest["delivery_package"] = manifest["delivery_package"]
    if isinstance(manifest.get("one_step"), dict):
        project_manifest["one_step"] = manifest["one_step"]
    sync_figure_plan_projection(project_manifest, manifest)
    sync_figure_plan_projection(project_manifest["last_run"], manifest)
    for key in (
        "publication_intent",
        "transform_ledger",
        "journal_profile",
        "publication_qa",
    ):
        if isinstance(manifest.get(key), dict):
            project_manifest[key] = manifest[key]
    return project_manifest
