"""Observe one persisted semantic plot head using its explicitly selected reader."""
from pathlib import Path
from typing import Any

from sciplot_core.project_store.io import observe_existing_store

from .context import repository_scope
from .errors import EngineError
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


def require_matching_figure(figure_id: str | None, *, plot_id: str, saved_figure_id: str | None) -> None:
    """An exact path and a supplied ID must identify the same authority."""
    if figure_id is not None and figure_id not in (plot_id, saved_figure_id):
        raise EngineError("figure_selection_mismatch", "The supplied figure ID does not match this saved plot.",
                          figure_id=figure_id, plot_id=plot_id, saved_figure_id=saved_figure_id)
