"""Bind a read-only scientific preview to source bytes and parsed choices."""

from __future__ import annotations

from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256


def preview_identity_for(
    preview: dict[str, Any], *, source_sha256: str
) -> dict[str, Any]:
    """Hash the actual scientific projection, never just its source path."""
    selection = {
        key: preview.get(key)
        for key in (
            "rule_id",
            "template",
            "resolved_figure_plan",
            "scientific_transform",
        )
    }
    identity = {
        "kind": "sciplot_plan_preview_identity",
        "version": 1,
        "source_tree_sha256": source_sha256,
        "selection_sha256": canonical_json_sha256(selection, allow_nan=False),
    }
    return {**identity, "sha256": canonical_json_sha256(identity, allow_nan=False)}


__all__ = ["preview_identity_for"]
