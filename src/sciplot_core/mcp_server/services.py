"""Thin argument conversion into existing domain owners; no CLI choreography."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from platformdirs import user_cache_path

from sciplot_core.mcp_server.errors import AdapterError


def _preview_output(arguments: dict[str, Any]) -> Path:
    explicit = arguments.get("output_dir")
    if explicit:
        return Path(explicit)
    parent = user_cache_path("SciPlot") / "previews"
    parent.mkdir(parents=True, exist_ok=True)
    return parent / uuid4().hex


def invoke_owner(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "sciplot_capabilities":
        from sciplot_core.studio_core.project_capabilities import project_control_capabilities
        from sciplot_core.studio_core.annotation_schema import annotation_operation_capabilities

        return {
            **project_control_capabilities(),
            "transport": "mcp_stdio",
            "annotation_operations": annotation_operation_capabilities(),
            "resource_lifetime": "Immutable session snapshots; requery after restart or eviction.",
        }
    if name == "sciplot_task_find":
        from sciplot_core.task_discovery import find_tasks

        root = arguments.get("tasks_root")
        return find_tasks(Path(arguments["source"]), tasks_root=Path(root) if root else None,
                          limit=arguments.get("limit", 20))
    if name in {"sciplot_task_start", "sciplot_task_inspect", "sciplot_task_resume"}:
        from sciplot_core.task_control import inspect_task, resume_task, start_task

        if name == "sciplot_task_start":
            task_dir = arguments.get("task_dir")
            return start_task(arguments["request"], task_dir=Path(task_dir) if task_dir else None)
        task = Path(arguments["task"])
        return inspect_task(task) if name == "sciplot_task_inspect" else resume_task(task, arguments["response"])
    project = Path(arguments["project"])
    figure_id = arguments.get("figure_id")
    if name == "sciplot_project_inspect":
        from sciplot_core.studio_core.project_query import inspect_project

        return inspect_project(project, figure_id=figure_id, object_path=arguments.get("object_path"))
    if name == "sciplot_preview":
        from sciplot_core.studio_core.document_edit import preview_project_document

        return preview_project_document(project, figure_id=figure_id, output_dir=_preview_output(arguments))
    if name == "sciplot_annotation_inspect":
        from sciplot_core.studio_core.annotation_operations import inspect_annotation_state

        return inspect_annotation_state(project, figure_id=figure_id)
    if name == "sciplot_edit_preview":
        from sciplot_core.studio_core.annotation_operations import preview_document_operations

        return preview_document_operations(project, arguments["operations"],
            output_dir=_preview_output(arguments), figure_id=figure_id,
            expected_document_sha256=arguments["expected_document_sha256"])
    if name == "sciplot_edit_apply":
        from sciplot_core.studio_core.document_edit import apply_document_edit
        from sciplot_core.studio_core.project_query_paths import canonical_path

        path = canonical_path(Path(arguments["review_path"]))
        if path.stat().st_size > 16 * 1024 * 1024:
            raise AdapterError("invalid_preview", "The saved review is unexpectedly large.")
        review = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(review, dict):
            raise AdapterError("invalid_preview", "The saved edit review must be an object.")
        return apply_document_edit(project, review)
    if name == "sciplot_peaks":
        from sciplot_core.studio_core.peak_analysis import inspect_peak_candidates

        return inspect_peak_candidates(project, figure_id=figure_id,
            object_path=arguments["object_path"], window=arguments["window"],
            polarity=arguments["polarity"],
            expected_document_sha256=arguments["expected_document_sha256"])
    if name == "sciplot_export":
        from sciplot_core.studio_core.project_creation import export_project

        return export_project(project)
    if name == "sciplot_operation":
        from sciplot_core.studio_core.document_edit_commit import read_edit_operation
        from sciplot_core.studio_core.project_query import resolve_project_path

        return read_edit_operation(resolve_project_path(project), arguments["operation_id"])
    raise AdapterError("unknown_tool", "Use a tool returned by tools/list.")
