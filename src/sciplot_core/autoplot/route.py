"""Describe the executed one-step route."""

from __future__ import annotations

from typing import Any


def _route_package(
    one_step: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    source = (
        one_step.get("source_package")
        if isinstance(one_step.get("source_package"), dict)
        else {}
    )
    mapping = (
        one_step.get("mapping_package")
        if isinstance(one_step.get("mapping_package"), dict)
        else {}
    )
    render_request = (
        one_step.get("render_request")
        if isinstance(one_step.get("render_request"), dict)
        else {}
    )
    semantic = (
        manifest.get("semantic") if isinstance(manifest.get("semantic"), dict) else {}
    )
    return {
        "mode": "one_step",
        "source_kind": source.get("source_kind") or "unknown",
        "semantic_family": mapping.get("semantic_family")
        or semantic.get("semantic_family")
        or "unknown",
        "rule_id": mapping.get("rule_id") or semantic.get("rule_id"),
        "confidence_band": source.get("confidence_band")
        or mapping.get("confidence_band")
        or "unknown",
        "recipe": render_request.get("recipe"),
        "template": render_request.get("template")
        or manifest.get("result", {}).get("template"),
        "figure_size": render_request.get("figure_size"),
        "exports": render_request.get("exports") or [],
    }
