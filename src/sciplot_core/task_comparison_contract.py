"""Explicit alternatives for one saved figure; scientific operations keep their owner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.studio_core.annotation_schema import (
    annotation_operation_capabilities, object_schema, validate_operation_batch,
)
from sciplot_core.project_lifecycle.figure_observation import resolve_project_path
from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_group_contract import validate_shape


def comparison_request_schema() -> dict[str, Any]:
    from sciplot_core.plot_document.schema import patch_schema

    patch = patch_schema()["properties"]
    text = {"type": "string", "minLength": 1, "maxLength": 200}
    identifier = {"type": "string", "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$", "not": {"const": "baseline"}}
    def alternatives(field: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {"type": "array", "minItems": 2, "maxItems": 8, "items": object_schema({
            "id": identifier, "label": text, "rationale": {"type": "string", "maxLength": 500},
            field: schema,
        }, ["id", "label", field])}

    publication = {"type": "boolean", "default": False}
    managed = object_schema({
        "version": {"type": "integer", "const": 2}, "title": text,
        "plot": {"type": "string", "minLength": 1}, "plot_id": patch["plot_id"], "base_revision": patch["base_revision"],
        "export": publication, "candidates": alternatives("changes", patch["changes"]),
    }, ["version", "title", "plot", "plot_id", "base_revision", "candidates"])
    native = object_schema({
        "version": {"type": "integer", "const": 1}, "title": text,
        "project": {"type": "string", "minLength": 1}, "figure_id": text,
        "expected_document_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "export": publication,
        "candidates": alternatives("operations", annotation_operation_capabilities()["operations_schema"]),
    }, ["version", "title", "project", "figure_id", "expected_document_sha256", "candidates"])
    native["description"] = "Native comparison for already admitted native products or existing frozen comparisons. Use version 2 for Managed plots."
    return {"type": "object", "oneOf": [managed, native]}


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
    if type(request["version"]) is not int:
        raise TaskControlError("invalid_comparison_version", "The comparison version must be an integer.")
    request.setdefault("export", False)
    if request["version"] == 2:
        if type(request["base_revision"]) is not int:
            raise TaskControlError("invalid_comparison_revision", "The base revision must be an integer.")
        request["plot"] = str(absolute(request["plot"]))
        return dict(request)
    for candidate in request["candidates"]:
        validate_operation_batch(candidate["operations"])
        for operation in candidate["operations"]:
            if operation["op"] == "apply_sample_style_preset":
                operation["preset"] = str(absolute(operation["preset"]))
    request["project"] = str(resolve_project_path(absolute(request["project"])))
    return dict(request)


def candidate_request(request: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "action": "edit", "export": False,
            **{key: request[key] for key in ("project", "figure_id", "expected_document_sha256")},
            "operations": candidate["operations"]}
