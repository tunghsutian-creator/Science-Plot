from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core._utils import slug
from sciplot_core.policy import DELIVERY_DIR


HIDDEN_WORKSPACE_DIR = ".sciplot"
VISIBLE_PROJECT_SUFFIX = "_SciPlot"
REQUEST_DELIVERY_ROOT_KEY = "delivery_output"


@dataclass(frozen=True)
class UserOutputLayout:
    """Separate the visible handoff from SciPlot's hidden runtime evidence."""

    delivery_root: Path
    workspace_root: Path


def _source_stem(source: Path) -> str:
    if source.is_dir():
        value = source.name
    else:
        value = source.stem
    return slug(value) or "sciplot"


def resolve_user_output_layout(
    source: str | Path,
    *,
    requested_delivery_root: str | Path | None = None,
    project_name: str | None = None,
) -> UserOutputLayout:
    """Return the visible delivery and its sibling hidden workspace.

    ``--out`` names the dedicated visible handoff directory.  Without an
    explicit path, the handoff is placed beside the source.  Runtime history,
    manifests, QA, raw snapshots, and provenance live below the sibling
    ``.sciplot`` directory and never appear in the handoff.
    """

    resolved_source = Path(source).expanduser().resolve()
    if requested_delivery_root is None:
        requested_name = (
            slug(project_name)
            if isinstance(project_name, str) and project_name.strip()
            else _source_stem(resolved_source)
        )
        delivery_root = resolved_source.parent / f"{requested_name}{VISIBLE_PROJECT_SUFFIX}"
    else:
        delivery_root = Path(requested_delivery_root).expanduser().resolve()
    delivery_root = delivery_root.resolve()
    if delivery_root == resolved_source or delivery_root == resolved_source.parent:
        raise ValueError(
            "The visible SciPlot output must be a dedicated directory, not the "
            "source itself or its parent directory."
        )
    workspace_root = (
        delivery_root.parent
        / HIDDEN_WORKSPACE_DIR
        / (slug(delivery_root.name).casefold() or "sciplot")
    ).resolve()
    return UserOutputLayout(
        delivery_root=delivery_root,
        workspace_root=workspace_root,
    )


def requested_delivery_root(
    manifest: dict[str, Any],
    *,
    run_output: Path,
) -> Path:
    """Resolve the authoritative visible root recorded on a plot request."""

    request = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    value = request.get(REQUEST_DELIVERY_ROOT_KEY)
    if not isinstance(value, str) or not value.strip():
        source_request = (
            manifest.get("source_request")
            if isinstance(manifest.get("source_request"), dict)
            else {}
        )
        value = source_request.get(REQUEST_DELIVERY_ROOT_KEY)
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser().resolve()
    return (run_output.expanduser().resolve() / DELIVERY_DIR).resolve()


__all__ = [
    "HIDDEN_WORKSPACE_DIR",
    "REQUEST_DELIVERY_ROOT_KEY",
    "UserOutputLayout",
    "VISIBLE_PROJECT_SUFFIX",
    "requested_delivery_root",
    "resolve_user_output_layout",
]
