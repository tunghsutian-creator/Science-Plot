"""Select registered Managed members without issuing project commands."""
from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import resolved_figure_plan_from_payload
from sciplot_core.project_store.io import observe_existing_store
from sciplot_core.project_store.repository import FileProjectStore

from .attachment_index import Attachment
from .head_observation import observe_plot_head
from .paths import canonical_path
from .repository_router import ComposedProjectRepository


def observe_saved_plot_head(plot: Path, *, optional: bool = False) -> dict[str, Any] | None:
    """Discover the selected semantic reader for a standalone host query."""
    return observe_plot_head(plot, owner=ComposedProjectRepository(), optional=optional)


def attachments_by_figure(store: FileProjectStore, index: dict[str, Any]) -> dict[str, Attachment]:
    """The stable project figure key is not a plot ID or a namespace path."""
    attachments: dict[str, Attachment] = {}
    for entry in index["attachments"].values():
        figure_id = entry["figure_id"]
        if figure_id in attachments:
            raise ValueError("One figure has competing current semantic attachments.")
        attachments[figure_id] = Attachment(store, entry)
    return attachments


@observe_existing_store()
def observe_project_figure_heads(project: Path, figure_ids: Sequence[str]) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Read selected project attachments together; never fall back to their old shadows."""
    from sciplot_core.project_store.io import STORE
    from .attached_repository import AttachedProjectRepository
    from .attachment_index import read_index, require_local_owner
    from .repository import document_root
    from .store_composition import existing_store

    project = canonical_path(project)
    store = None
    snapshot = None
    registered: dict[str, Attachment] = {}
    if (project / STORE / "head.json").is_file():
        store = existing_store(project)
        snapshot = store.observe_members(projection=False).selected
        registered = attachments_by_figure(store, read_index(store, snapshot))
    heads = {}
    for figure_id in figure_ids:
        attachment = registered.get(figure_id)
        if attachment is not None:
            head = observe_plot_head(attachment.root, owner=AttachedProjectRepository(attachment))
            assert head is not None
            if head["document"]["plot_id"] != attachment.entry["plot_id"]:
                raise ValueError("The selected semantic attachment has a different plot identity.")
            heads[figure_id] = (attachment.root, head)
        else:
            plot = document_root(project, figure_id)
            require_local_owner(plot)
            head = observe_saved_plot_head(plot, optional=True)
            if head is not None:
                heads[figure_id] = (plot, head)
    if store is not None and snapshot is not None and store.observe_members(projection=False).selected["generation"] != snapshot["generation"]:
        raise ValueError("The semantic attachments changed during figure observation.")
    return heads


@dataclass(frozen=True)
class FrequencyFigureObservation:
    """Registered Managed members of one saved generation, published or not."""

    generation: str
    projection_status: str | None
    primary_figure_id: str
    figures: list[dict[str, Any]]


@observe_existing_store()
def observe_frequency_figures(project: Path, *, projection: bool = False) -> FrequencyFigureObservation:
    """Select canonical members in the saved order, independent of sibling export status."""
    from sciplot_core.project_lifecycle.attachment_index import INDEX, validate_index

    project = canonical_path(project)
    if not (project / ".sciplot_store/head.json").is_file():
        raise ValueError("The Managed frequency project has no registered figure plan.")
    store = FileProjectStore(project)
    observation = store.observe_members((INDEX, "figure-plan.json"), projection=projection)
    plan_bytes = observation.members["figure-plan.json"].data
    index_bytes = observation.members[INDEX].data
    if plan_bytes is None or index_bytes is None:
        raise ValueError("The Managed frequency project has no registered figure plan.")
    plan = resolved_figure_plan_from_payload(json.loads(plan_bytes))
    entries = attachments_by_figure(store, validate_index(json.loads(index_bytes), observation.selected["project_id"]))
    if (plan is None or not plan.selected_figure_ids
            or not set(plan.selected_figure_ids).issubset(entries)):
        raise ValueError("The saved frequency figure plan and attachment index do not agree.")
    figures = [{"figure_id": task.figure_id, "title": task.title, "plot_id": entries[task.figure_id].entry["plot_id"],
                "plot": str(entries[task.figure_id].root)} for task in plan.tasks]
    status = observation.projection["projection_status"] if observation.projection is not None else None
    return FrequencyFigureObservation(observation.selected["generation"], status, plan.primary_figure_id, figures)
