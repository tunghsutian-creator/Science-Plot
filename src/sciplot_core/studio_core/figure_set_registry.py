"""Build the persisted Studio figure-set registry from verified entries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.studio_figure_set_contract import (
    STUDIO_FIGURE_SET_KIND,
    STUDIO_FIGURE_SET_LEGACY_VERSION,
    STUDIO_FIGURE_SET_TASK_VERSION,
)

from sciplot_core.studio_core.figure_task_evidence import (
    validate_figure_registry_against_plan,
)
from sciplot_core.studio_core.registry_state import _studio_figure_set_path


def build_studio_figure_set_registry(
    *,
    project_dir: Path,
    request_path: Path,
    request: dict[str, Any],
    primary_figure_id: str,
    primary_document: Path,
    entries: list[dict[str, Any]],
    resolved_plan: ResolvedFigurePlan | None,
) -> dict[str, Any]:
    """Return legacy v1 or exact task-aware v2 registry state."""

    registry: dict[str, Any] = {
        "kind": STUDIO_FIGURE_SET_KIND,
        "version": (
            STUDIO_FIGURE_SET_TASK_VERSION
            if resolved_plan is not None
            else STUDIO_FIGURE_SET_LEGACY_VERSION
        ),
        "rule_id": str(request.get("rule_id") or ""),
        "status": (
            "ready"
            if all(item.get("status") == "ready" for item in entries)
            else "partially_available"
        ),
        "primary_figure_id": primary_figure_id,
        "primary_document": str(primary_document),
        "document_policy": "independent_single_page_vsz",
        "publication_layout_inferred": False,
        "composite_figure": False,
        "figures": entries,
        "export_contract": {
            "kind": "sciplot_figure_set_export_scope",
            "version": 2,
            "status": "full_figure_set_exact_current",
            "scope": "full_figure_set_project_delivery",
            "primary_figure_id": primary_figure_id,
            "supported_figure_ids": [
                str(item["figure_id"])
                for item in entries
                if item.get("status") == "ready"
            ],
            "blocked_figure_ids": [],
            "blocker": None,
            "secondary_receipt_scope": "same_project_delivery",
            "full_figure_set_delivery_complete": all(
                item.get("status") == "ready" for item in entries
            ),
        },
        "generated_from": str(request_path),
        "registry_path": str(_studio_figure_set_path(project_dir)),
    }
    if resolved_plan is not None:
        registry["resolved_figure_plan"] = resolved_plan.to_payload()
        registry["plan_id"] = resolved_plan.plan_id
        registry["plan_sha256"] = resolved_plan.plan_sha256
        validate_figure_registry_against_plan(registry, resolved_plan)
    return registry


__all__ = ["build_studio_figure_set_registry"]
