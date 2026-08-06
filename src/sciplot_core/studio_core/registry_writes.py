"""Register Studio document, export, and run state in the project manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.figure_plan import sync_figure_plan_projection
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.project_manifest import (
    edit_intake_project_manifest,
    edit_intake_project_manifest_with_snapshot,
)


def _register_studio_block(project_dir: Path, studio_block: dict[str, Any]) -> None:
    with edit_intake_project_manifest(project_dir) as payload:
        if payload is not None:
            payload["studio"] = studio_block
            sync_figure_plan_projection(payload, studio_block)
    # Existing or moved projects can carry a retired Web launcher and stale
    # absolute launcher paths in both manifests.  Converge only after the
    # current portable launchers and Studio block are written so normal
    # `studio PROJECT` is itself the repair path.
    from sciplot_core.intake.packaging import converge_intake_project_launchers

    converge_intake_project_launchers(project_dir)


def _register_studio_run(
    project_dir: Path,
    manifest: dict[str, Any],
    *,
    studio_run: dict[str, Any],
) -> None:
    figure_set_export_scope = (
        manifest.get("figure_set_export_scope")
        if isinstance(manifest.get("figure_set_export_scope"), dict)
        else None
    )
    last_run = {
        "completed_at": manifest.get("created_at"),
        "route": "studio",
        "output": manifest.get("output"),
        "figures": manifest.get("figures", []),
        "qa": manifest.get("qa", {}),
        "revision_brief": manifest.get("revision_brief"),
        "package_contract": manifest.get("package_contract", {}),
        "delivery_package": manifest.get("delivery_package", {}),
        "layout_quality": manifest.get("layout_quality", {}),
        "state": manifest.get("state"),
        "ready_to_use": manifest.get("ready_to_use"),
        "failure_stage": manifest.get("failure_stage"),
        "failure_reason": manifest.get("failure_reason"),
        "template": manifest.get("template"),
        "presentation_identity": manifest.get("presentation_identity"),
        "rule_readiness": manifest.get("rule_readiness"),
        "pending_rule_review": manifest.get("pending_rule_review"),
        "publication_rule_blocked": manifest.get("publication_rule_blocked"),
        "autonomous_rule_ready": manifest.get("autonomous_rule_ready"),
    }
    if figure_set_export_scope is not None:
        last_run["figure_set_export_scope"] = json_safe(figure_set_export_scope)
    sync_figure_plan_projection(last_run, manifest)
    from sciplot_core.intake.packaging import (
        _refresh_intake_project_zip_unlocked,
    )

    with edit_intake_project_manifest_with_snapshot(
        project_dir,
        snapshot_writer=_refresh_intake_project_zip_unlocked,
    ) as payload:
        if payload is not None:
            payload["last_run"] = last_run
            payload["package_contract"] = manifest.get("package_contract", {})
            payload["delivery_package"] = manifest.get("delivery_package", {})
            payload["layout_quality"] = manifest.get("layout_quality", {})
            if figure_set_export_scope is not None:
                payload["figure_set_export_scope"] = json_safe(figure_set_export_scope)
            else:
                payload.pop("figure_set_export_scope", None)
            sync_figure_plan_projection(payload, manifest)
            studio = (
                payload.get("studio") if isinstance(payload.get("studio"), dict) else {}
            )
            exports = (
                studio_run.get("exports")
                if isinstance(studio_run.get("exports"), list)
                else []
            )
            studio["exports"] = json_safe(exports)
            presentation_identity = studio_run.get("presentation_identity")
            if isinstance(presentation_identity, dict):
                studio["presentation_identity"] = json_safe(presentation_identity)
            studio["last_export_run"] = json_safe(studio_run)
            payload["studio"] = studio
            payload["study_model"] = manifest.get(
                "study_model", payload.get("study_model", {})
            )
