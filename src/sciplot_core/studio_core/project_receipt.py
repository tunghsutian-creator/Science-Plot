"""Compact projections of the canonical Studio publication receipt."""

from __future__ import annotations

from typing import Any
from pathlib import Path


def project_receipt(payload: dict[str, Any], returncode: int) -> dict[str, Any]:
    """Project the existing Studio receipt without duplicating scientific arrays."""
    run = payload.get("studio_run")
    if not isinstance(run, dict):
        raise ValueError("Studio creation returned no managed export result.")
    ready = returncode == 0 and run.get("ready_to_use") is True
    state = run.get("state")
    reason = run.get("failure_reason")
    if returncode and not reason:
        reason = f"Studio creation returned exit status {returncode}."
    if not ready and not reason:
        reason = "The created project did not pass its export and delivery gates."
    if not ready and state == "ready":
        state = "failed"
    delivery_value = run.get("delivery_package")
    delivery = delivery_value if isinstance(delivery_value, dict) else {}
    registry_value = payload.get("figure_set")
    registry = registry_value if isinstance(registry_value, dict) else {}
    artifacts = delivery.get("figures") or []
    figures = []
    primary = registry.get("primary_figure_id")
    for item in registry.get("figures", []):
        if not isinstance(item, dict):
            continue
        figures.append(
            {
                "figure_id": item.get("figure_id"),
                "title": item.get("title"),
                "document": item.get("document"),
                "exports": [
                    {"format": artifact.get("format"), "path": artifact.get("path")}
                    for artifact in artifacts
                    if isinstance(artifact, dict)
                    and artifact.get("figure_id") == item.get("figure_id")
                ],
            }
        )
    if ready and not figures and isinstance(payload.get("project_dir"), str):
        from sciplot_core.studio_core.project_query import inspect_project

        try:
            current = inspect_project(Path(payload["project_dir"]))
            if all((current.get(key) or {}).get("current") is True for key in ("source", "qa", "delivery")):
                for item in current.get("figures", []):
                    if item.get("status") != "ready" or not Path(item["document"]).is_file():
                        continue
                    exports = [{"format": record.get("format"), "path": record["path"]}
                        for record in artifacts if record.get("figure_id") == item["figure_id"]
                        and isinstance(record.get("path"), str) and Path(record["path"]).is_file()]
                    if exports:
                        figures.append({**{key: item.get(key) for key in ("figure_id", "title", "document")}, "exports": exports})
                primary = current.get("primary_figure_id")
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return {
        "kind": "sciplot_project_creation_result",
        "version": 1,
        "status": "created" if ready else "blocked",
        "project_dir": payload.get("project_dir"),
        "document": payload.get("document"),
        "request": payload.get("request"),
        "primary_figure_id": primary,
        "figures": figures,
        "studio_run": {
            "ready_to_use": ready,
            "state": state,
            "manifest": run.get("manifest"),
            "delivery_package": {
                "path": delivery.get("path"),
                "complete": delivery.get("complete") is True,
            },
            "failure_stage": run.get("failure_stage"),
            "failure_reason": reason,
        },
    }

