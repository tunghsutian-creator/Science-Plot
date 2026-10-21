"""Explicit ordered selection of exact saved figures across projects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from sciplot_core.studio_core.annotation_schema import object_schema
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_contract import TaskControlError


def paper_request_schema() -> dict[str, Any]:
    text = {"type": "string", "minLength": 1, "maxLength": 200}
    digest = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    version = object_schema({name: digest for name in (
        "request_sha256", "document_sha256", "spec_sha256", "source_sha256",
    )}, ["request_sha256", "document_sha256", "spec_sha256", "source_sha256"])
    return object_schema({
        "version": {"type": "integer", "const": 1}, "title": text,
        "out": {"type": "string", "minLength": 1},
        "items": {"type": "array", "minItems": 1, "maxItems": 32, "items": object_schema({
            "project": {"type": "string", "minLength": 1}, "figure_id": text,
            "label": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
            "expected_version": version,
        }, ["project", "figure_id", "label", "expected_version"])},
    }, ["version", "title", "out", "items"])


def normalize_paper_request(value: object, *, base_dir: Path | None = None) -> dict[str, Any]:
    try:
        json.dumps(value, allow_nan=False)
        error = next(Draft202012Validator(paper_request_schema()).iter_errors(value), None)
        if error is not None:
            raise ValueError(f"{'/'.join(map(str, error.absolute_path))}: {error.message[:400]}")
    except (ValueError, TypeError) as exc:
        raise TaskControlError("invalid_paper_request", str(exc)) from exc
    request = json.loads(json.dumps(value, ensure_ascii=False))
    base = base_dir or Path.cwd()
    for entry in [request, *request["items"]]:
        key = "out" if entry is request else "project"
        path = Path(entry[key]).expanduser()
        entry[key] = str(canonical_path(path if path.is_absolute() else base / path))
    labels = [item["label"].casefold() for item in request["items"]]
    if len(labels) != len(set(labels)):
        raise TaskControlError("duplicate_paper_label", "Paper labels must be unique, including case.")
    identities = [(item["project"], item["figure_id"]) for item in request["items"]]
    if len(identities) != len(set(identities)):
        raise TaskControlError("duplicate_paper_figure", "Select each exact project figure once.")
    return dict(request)


def paper_stem(index: int, label: str) -> str:
    """Order is the request array, never inferred from project or file names."""
    return f"{index:03d}_{label}"
