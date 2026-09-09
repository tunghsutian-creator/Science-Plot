"""Explicit alternatives for one saved figure; scientific operations keep their owner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.studio_core.annotation_schema import (
    annotation_operation_capabilities, object_schema, validate_operation_batch,
)
from sciplot_core.studio_core.project_query import resolve_project_path
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_group_contract import validate_shape


def comparison_request_schema() -> dict[str, Any]:
    text = {"type": "string", "minLength": 1, "maxLength": 200}
    return object_schema({
        "version": {"type": "integer", "const": 1}, "title": text,
        "project": {"type": "string", "minLength": 1}, "figure_id": text,
        "expected_document_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "export": {"type": "boolean", "default": False},
        "candidates": {"type": "array", "minItems": 2, "maxItems": 8, "items": object_schema({
            "id": {"type": "string", "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$", "not": {"const": "baseline"}},
            "label": text, "rationale": {"type": "string", "maxLength": 500},
            "operations": annotation_operation_capabilities()["operations_schema"],
        }, ["id", "label", "operations"])},
    }, ["version", "title", "project", "figure_id", "expected_document_sha256", "candidates"])


def comparison_selection_schema() -> dict[str, Any]:
    return object_schema({
        "candidate_id": {"type": "string", "minLength": 1},
        "expected_comparison_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    }, ["candidate_id", "expected_comparison_id"])


def normalize_comparison_request(value: dict[str, Any], *, base_dir: Path | None = None) -> dict[str, Any]:
    validate_shape(value, comparison_request_schema())
    request = json.loads(json.dumps(value, ensure_ascii=False))
    base = base_dir or Path.cwd()

    def absolute(raw: str) -> Path:
        path = Path(raw).expanduser()
        return canonical_path(path if path.is_absolute() else base / path)

    ids = [item["id"] for item in request["candidates"]]
    if len(ids) != len(set(ids)):
        raise TaskControlError("duplicate_comparison_candidate", "比较中的候选 id 必须唯一。")
    for candidate in request["candidates"]:
        validate_operation_batch(candidate["operations"])
        for operation in candidate["operations"]:
            if operation["op"] == "apply_sample_style_preset":
                operation["preset"] = str(absolute(operation["preset"]))
    request["project"] = str(resolve_project_path(absolute(request["project"])))
    request.setdefault("export", False)
    return dict(request)


def candidate_request(request: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "action": "edit", "export": False,
            **{key: request[key] for key in ("project", "figure_id", "expected_document_sha256")},
            "operations": candidate["operations"]}
