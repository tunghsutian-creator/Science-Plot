"""Freeze an explicit current experiment-group selection through paper owners."""

from pathlib import Path
import re
from typing import Any

from sciplot_core.studio_core.project_query_paths import canonical_path, project_snapshot
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_group_storage import group_path, load_group, step_state
from sciplot_core.task_paper_sources import capture_selection
from sciplot_core.task_papers import _path, _load, start_paper
from sciplot_core.task_paper_status import _current_summary
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot, _assert_snapshot_current


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
            return _current_summary(root, state)
    if item_ids is not None and (not item_ids or len(item_ids) != len(set(item_ids))):
        raise TaskControlError("paper_group_items_invalid", "Select distinct existing group item IDs in the desired order.")
    snapshot = stable_file_snapshot(group / "group.json", label="paper current group selection")
    state = load_group(group)
    indexed = {item["id"]: item for item in state["items"]}
    order = list(indexed) if item_ids is None else item_ids
    if any(identifier not in indexed for identifier in order):
        raise TaskControlError("paper_group_items_invalid", "Select only current group item IDs.")
    selected: list[dict[str, Any]] = []
    for identifier in order:
        item = indexed[identifier]
        children = [step_state(step) for step in item["steps"]]
        if (item.get("status") != "complete" or item.get("finished") is not True or item.get("blocker")
                or not children or any(child is None or child["status"] != "complete" for child in children)):
            raise TaskControlError("paper_group_item_pending", "Every selected item must finish its creation, presentation and export tasks before delivery.")
        projects = {child["project"] for child in children if child is not None and child.get("project")}
        if len(projects) != 1:
            raise TaskControlError("paper_group_project_ambiguous", "The selected item does not identify one canonical original project.")
        project = canonical_path(Path(next(iter(projects))))
        _, _, figures = project_snapshot(project)
        for figure in figures:
            if figure["status"] != "ready":
                raise TaskControlError("paper_group_figure_pending", "Every selected registered figure must have a saved native document.")
            captured = capture_selection(project, figure["figure_id"])
            label = f"{len(selected) + 1:03d}_" + re.sub(r"[^A-Za-z0-9_-]", "_", identifier + "_" + figure["figure_id"])[:59]
            selected.append({"project": captured["project"], "figure_id": figure["figure_id"],
                             "label": label, "expected_version": captured["version"]})
    group_sha256 = state["state_sha256"]
    group_title = state["request"]["title"]
    _assert_snapshot_current(snapshot, label="paper current group selection")
    request = {"version": 1, "title": title if title is not None else group_title, "out": str(out), "items": selected}
    return start_paper(request, paper_dir=root, selection_origin={"request": origin, "group_state_sha256": group_sha256,
                                                               "scope": "Frozen ordered registered figures, not a cross-plot edit."})
