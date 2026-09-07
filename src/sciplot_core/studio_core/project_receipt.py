"""Compact projections of the canonical Studio publication receipt."""

from __future__ import annotations

from typing import Any


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
    return {
        "kind": "sciplot_project_creation_result",
        "version": 1,
        "status": "created" if ready else "blocked",
        "project_dir": payload.get("project_dir"),
        "document": payload.get("document"),
        "request": payload.get("request"),
        "primary_figure_id": registry.get("primary_figure_id"),
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

