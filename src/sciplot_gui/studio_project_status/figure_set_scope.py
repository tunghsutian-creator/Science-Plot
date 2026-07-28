"""Resolve and validate multi-figure export scope."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.studio_figure_set_contract import (
    is_primary_figure_set_export_scope as _is_primary_figure_set_export_scope,
)


def _resolve_figure_set_export_scope(
    *,
    project_dir: Path,
    request: dict[str, Any],
    latest_run: dict[str, Any],
    _scope_builder: Any = None,
) -> tuple[dict[str, Any] | None, str]:
    persisted_present = "figure_set_export_scope" in latest_run
    persisted = latest_run.get("figure_set_export_scope")
    if _is_primary_figure_set_export_scope(persisted):
        return dict(persisted), "persisted"

    recomputed = None
    if _scope_builder is not None:
        try:
            recomputed = _scope_builder(
                project_dir,
                request=request,
            )
        except Exception:
            recomputed = None
    if _is_primary_figure_set_export_scope(recomputed):
        return dict(recomputed), "recomputed_current_project"

    delivery = (
        latest_run.get("delivery_package")
        if isinstance(latest_run.get("delivery_package"), dict)
        else {}
    )
    package = (
        latest_run.get("package_contract")
        if isinstance(latest_run.get("package_contract"), dict)
        else {}
    )
    figure_set_indicated = bool(
        persisted_present
        or (project_dir / "studio" / "figure_set.json").exists()
        or delivery.get("scope") == "full_figure_set_project_delivery"
        or package.get("full_figure_set_complete") is True
    )
    return (
        (None, "unknown_or_incomplete")
        if figure_set_indicated
        else (None, "not_applicable")
    )
