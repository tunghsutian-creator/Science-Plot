"""Observe one persisted semantic plot head using its explicitly selected reader."""
from pathlib import Path
from typing import Any

from sciplot_core.project_store.io import observe_existing_store

from .context import repository_scope
from .paths import canonical_path
from .ports import ProjectRepository


@observe_existing_store()
def observe_plot_head(plot: Path, *, owner: ProjectRepository,
                      optional: bool = False) -> dict[str, Any] | None:
    """Read one sealed semantic head using the existing repository's query scope."""
    plot = canonical_path(plot)
    with repository_scope(owner), owner.query_scope(plot):
        if not owner.has_head(plot):
            if optional:
                return None
            # Retain the repository's own missing/invalid head error.
            return owner.load_head(plot)
        pointer = plot / "head.json"
        before = owner.content_snapshot(pointer)["sha256"]
        head = owner.load_head(plot)
        if owner.content_snapshot(pointer)["sha256"] != before:
            raise ValueError("The selected plot revision changed during observation.")
        return head
