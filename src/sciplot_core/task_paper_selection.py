"""Freeze an explicit current experiment-group selection through paper owners."""

from pathlib import Path
import re
from typing import Any

from sciplot_core.studio_core.project_query_paths import canonical_path, project_snapshot
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_group_storage import group_path, load_group, step_state
from sciplot_core.task_papers import _path, _load, _inspect, start_paper, inspect_paper, start_managed_group_paper
from sciplot_core.task_semantic_owner import describe_managed
from sciplot_core.task_storage import task_location
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot, _assert_snapshot_current


def _label(item: dict[str, Any], figure: dict[str, Any], figures: list[dict[str, Any]]) -> str:
    def safe(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_-")

    label = safe(item["label"])
    if len(figures) > 1:
        titles = [safe(str(entry.get("title") or entry["figure_id"])) for entry in figures]
        title = safe(str(figure.get("title") or figure["figure_id"]))
        suffix = title if title and titles.count(title) == 1 else safe(figure["figure_id"])
        suffix = suffix[:48]
        label = label[:max(1, 63 - len(suffix))] + "_" + suffix
    if not label:
        raise TaskControlError("paper_group_label_invalid", "Give the selected group item a nonempty safe display label.")
    return label[:64]


def start_group_paper(group: Path, *, paper_dir: Path, out: Path, title: str | None = None,
                      item_ids: list[str] | None = None) -> dict[str, Any]:
    """Capture once, then use frozen versions on every retry; never render a gallery."""
    group, root, out = group_path(group), _path(paper_dir), canonical_path(out)
    origin = {"kind": "current_group_selection", "group": str(group),
              "item_ids": item_ids, "title": title, "out": str(out)}
    if root.exists():
        with external_project_session(root):
            state = _load(root)
            if (state.get("selection_origin") or {}).get("request") != origin:
                raise TaskControlError("paper_already_exists", "This paper checkpoint owns another frozen selection.")
            return _inspect(root, state)
    if item_ids is not None and (not item_ids or len(item_ids) != len(set(item_ids))):
        raise TaskControlError("paper_group_items_invalid", "Select distinct existing group item IDs in the desired order.")
    snapshot = stable_file_snapshot(group / "group.json", label="paper current group selection")
    state = load_group(group)
    indexed = {item["id"]: item for item in state["items"]}
    order = list(indexed) if item_ids is None else item_ids
    if any(identifier not in indexed for identifier in order):
        raise TaskControlError("paper_group_items_invalid", "Select only current group item IDs.")
    registered: list[dict[str, Any]] = []
    for identifier in order:
        item = indexed[identifier]
        children = [step_state(step) for step in item["steps"]]
        if not children or children[0] is None:
            raise TaskControlError("paper_group_item_pending", "The selected item has no saved figures yet.")
        creation = children[0].get("result") or {}
        handles = [handle for handle in creation.get("plot_objects", []) if handle.get("plot_type") == "ManagedPlot"]
        frequency = creation.get("document_authority") == "managed_figure_group"
        if not frequency and not handles:
            if (item.get("status") != "complete" or item.get("finished") is not True or item.get("blocker")
                    or any(child is None or child["status"] != "complete" for child in children)):
                raise TaskControlError("paper_group_item_pending", "Every selected legacy item must finish its creation, presentation and export tasks before delivery.")
        elif len(children) != 1:
            raise TaskControlError("paper_group_item_pending", "Resolve the selected item's pending group steps before packaging its Managed figures.")
        projects = {child["project"] for child in children if child is not None and child.get("project")}
        if len(projects) != 1:
            raise TaskControlError("paper_group_project_ambiguous", "The selected item does not identify one canonical original project.")
        project = canonical_path(Path(next(iter(projects))))
        if frequency:
            from sciplot_core.studio_core.managed_frequency_query import registered_frequency_members

            figures = registered_frequency_members(project)
        elif handles:
            figures = [{**handle, "figure_id": handle["plot_id"]} for handle in handles]
        else:
            _, _, figures = project_snapshot(project)
        for figure in figures:
            registered.append({"item_id": identifier, "project": str(project), "figure": figure,
                               "label": _label(item, figure, figures),
                               "authority": "ManagedPlot" if frequency or handles else "LegacyPlot"})
    authorities = {item["authority"] for item in registered}
    if len(authorities) > 1:
        error = TaskControlError("paper_group_mixed_authority", "Select separate Managed and legacy paper packages; nothing was packaged.")
        error.repair = {"action": "select_separate_packages", "items": [{
            "item_id": item["item_id"], "project": item["project"], "authority": item["authority"],
            "figure_id": item["figure"]["figure_id"], **({"plot": item["figure"]["plot"]} if "plot" in item["figure"] else {}),
        } for item in registered]}
        raise error

    managed = authorities == {"ManagedPlot"}
    selected: list[dict[str, Any]] = []
    for item in registered:
        figure = item["figure"]
        if managed:
            current = describe_managed(Path(figure["plot"]))
            if current.get("plot_type") != "ManagedPlot" or current.get("plot_id") != figure["plot_id"]:
                raise TaskControlError("paper_group_figure_changed", f"The registered figure no longer identifies its saved ManagedPlot: {figure['plot']}")
            selected.append({**{key: current[key] for key in ("plot", "plot_id", "revision")}, "label": item["label"]})
        else:
            if figure["status"] != "ready":
                raise TaskControlError("paper_group_figure_pending", "Every selected registered figure must have a saved native document.")
            selected.append({"project": item["project"], "figure_id": figure["figure_id"], "label": item["label"],
                             "expected_version": {key: figure[key] for key in ("document_sha256", "spec_sha256")}})
    resolved_title = title if title is not None else state["request"]["title"]
    selection_origin = {"request": origin, "group_state_sha256": state["state_sha256"],
                        "scope": "Frozen ordered registered figures, not a cross-plot edit."}
    if managed:
        _assert_snapshot_current(snapshot, label="paper current group selection", expected_sha256=snapshot["sha256"])
        if any(target == group or target.is_relative_to(group) or group.is_relative_to(target) for target in (root, out)):
            raise TaskControlError("paper_path_overlap", "Keep the paper package and checkpoint outside the original group.")
        # Protect the group's input tree, workspace and original visible output
        # as well as the individual Managed heads checked by the publisher.
        requests = {item["id"]: item["request"] for item in state["request"]["items"]}
        for identifier in order:
            task_location(requests[identifier], root)
            task_location(requests[identifier], out)
        return start_managed_group_paper(root, out=out, title=resolved_title, items=selected, selection_origin=selection_origin)
    result = start_paper({"version": 1, "title": resolved_title, "out": str(out), "items": selected},
                         paper_dir=root, selection_origin=selection_origin, group_snapshot=snapshot)
    return inspect_paper(root) if result.get("status") == "complete" else result
