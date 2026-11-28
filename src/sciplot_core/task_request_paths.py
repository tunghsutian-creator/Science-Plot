"""Bind task input and output paths before task execution reserves state."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.project_lifecycle.figure_observation import resolve_project_path
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_semantic_contract import archive_task_target


def normalize_task_paths(request: dict[str, Any]) -> tuple[str | None, dict[str, str] | None, str | None]:
    """Normalize the wire request in place and return the original input witness."""
    source_hashes = None
    archive_target = archive_task_target(request)
    if archive_target is not None:
        target = canonical_path(Path(archive_target))
        if target.suffix != ".sciplot":
            raise TaskControlError("invalid_project_file_target", "Choose an exact .sciplot filename.")
        request["append_to" if "append_to" in request else "project_file"] = str(target)
        archive_target = str(target)
        request["sources"] = [str(canonical_path(Path(value))) for value in request["sources"]]
        digest = None
    elif "intent" in request:
        from sciplot_core.task_semantic_creation import normalize_sources

        source_hashes = normalize_sources(request)
        digest = None
    elif request["action"] in {"create", "update_source"}:
        source = canonical_path(Path(request["source"]))
        digest = source_tree_sha256(source)
        if digest is None:
            raise TaskControlError("source_not_found", "未找到原始数据文件或目录。")
        request["source"] = str(source)
    else:
        digest = None
    if request["action"] != "create":
        request["project"] = str(resolve_project_path(Path(request["project"])))
    for key in ("out", "profile"):
        if key in request:
            request[key] = str(canonical_path(Path(request[key])))
    return archive_target, source_hashes, digest
