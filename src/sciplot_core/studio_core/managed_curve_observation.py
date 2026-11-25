"""Locate the saved ordinary Managed creation from its exact product entry."""
from pathlib import Path
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.project_lifecycle.managed_figure_observation import observe_saved_plot_head


def observe_managed_curve(value: Path, *, figure_id: str | None = None
                          ) -> tuple[dict[str, Any], dict[str, Any], bool] | None:
    """Read the exact semantic figure behind an ordinary creation or its original package."""
    from sciplot_core.foundation.json_io import read_json_object
    from sciplot_core.plot_engine.managed_delivery_continuation import local_managed_target
    from sciplot_core.task_storage import load_task

    selected = canonical_path(value)
    snapshot = selected if selected.suffix.casefold() == ".vsz" and selected.parent.name == "project" else None
    package = snapshot.parent.parent if snapshot is not None else selected.parent if selected.name == "index.json" else selected
    index = read_json_object(package / "index.json") if package.is_dir() else None
    delivered = index is not None and index.get("kind") == "sciplot_managed_delivery"
    selected_journal = None
    if delivered:
        if snapshot is not None and not snapshot.is_file():
            raise ValueError(f"The selected Managed delivery document does not exist: {snapshot}")
        target = local_managed_target(package, None)
        if snapshot is not None and target["native_snapshot"] != str(snapshot):
            raise ValueError(f"The selected VSZ is not registered in this Managed delivery: {snapshot}")
        plot = target["plot"]
    elif (selected.parent.name == "managed" and selected.parent.parent.name == ".sciplot_documents"
          or selected.parent.name == ".sciplot_semantic"):
        plot = selected
    elif selected.name == "task.json" and selected.parent.name == "creation" and selected.is_file():
        journal_state = load_task(selected.parent)
        if not isinstance(journal_state.get("project_creation_figure"), dict) or not isinstance(journal_state.get("project"), str):
            return None
        selected_journal = selected.parent
        plot = canonical_path(Path(journal_state["project"]))
    else:
        return None
    head = observe_saved_plot_head(plot, optional=True)
    if head is None:
        return None
    document = head["document"]
    if document.get("plot_type") != "ManagedPlot":
        return None
    task_binding = document["scientific"]["provenance"].get("binding", {}).get("semantic_task", {})
    journal_value = task_binding.get("task")
    if not isinstance(journal_value, str):
        return None
    journal = canonical_path(Path(journal_value))
    if selected_journal is not None and journal != selected_journal:
        raise ValueError("The selected creation journal does not own this Managed plot.")
    if not (journal / "task.json").is_file():
        return None
    state = load_task(journal)
    task = state.get("project_creation_figure")
    if not isinstance(task, dict) or state.get("project") != str(plot):
        return None
    if delivered and package != Path(state["delivery_request"]["out"]):
        raise ValueError("The delivery is not the original local package for this project.")
    if figure_id is not None and figure_id != task["figure_id"]:
        raise ValueError(f"Unknown figure_id for this Managed project: {figure_id}")
    item = {"figure_id": task["figure_id"], "title": task["title"], "status": "ready",
            "plot": str(plot), "plot_id": document["plot_id"], "revision": document["revision"],
            "document": head["binding"]["document"]}
    return item, state, figure_id is not None or snapshot is not None
