from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from sciplot_core.canvas._validation import (
    reject_unknown_keys,
    require_json_int,
    require_json_list,
)
from sciplot_core.canvas.annotations import (
    REVIEW_ANNOTATION_VERSION,
    ReviewAnnotation,
)
from sciplot_core.canvas.composition import CompositionProject
from sciplot_core.canvas.model import CanvasSession

CANVAS_SESSION_FILENAME = "canvas_session.json"
COMPOSITION_FILENAME = "composition.json"
REVIEW_ANNOTATIONS_FILENAME = "review_annotations.json"
OPERATION_JOURNAL_FILENAME = "operation_journal.jsonl"


def atomic_write_json(path: Path, payload: dict[str, Any]) -> Path:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(
                payload,
                handle,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return target


def save_canvas_session(path: Path, session: CanvasSession) -> Path:
    return atomic_write_json(path, session.to_dict())


def load_canvas_session(path: Path) -> CanvasSession:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("canvas_session.json must contain an object.")
    return CanvasSession.from_dict(payload)


def save_composition_project(path: Path, project: CompositionProject) -> Path:
    return atomic_write_json(path, project.to_dict())


def load_composition_project(path: Path) -> CompositionProject:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("composition.json must contain an object.")
    return CompositionProject.from_dict(payload)


def save_review_annotations(path: Path, annotations: list[ReviewAnnotation]) -> Path:
    annotation_ids = [annotation.annotation_id for annotation in annotations]
    if len(set(annotation_ids)) != len(annotation_ids):
        raise ValueError("Review annotation IDs must be unique.")
    return atomic_write_json(
        path,
        {
            "kind": "sciplot_review_annotations",
            "version": REVIEW_ANNOTATION_VERSION,
            "annotations": [annotation.to_dict() for annotation in annotations],
        },
    )


def load_review_annotations(path: Path) -> list[ReviewAnnotation]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("review_annotations.json must contain an object.")
    reject_unknown_keys(
        payload,
        {"kind", "version", "annotations"},
        label="review_annotations.json",
    )
    if payload.get("kind") != "sciplot_review_annotations":
        raise ValueError("Not a SciPlot review annotations payload.")
    version = require_json_int(payload.get("version", 0), label="version")
    if version not in {1, REVIEW_ANNOTATION_VERSION}:
        raise ValueError(
            f"Unsupported review annotations version: {payload.get('version')!r}"
        )
    raw_annotations = require_json_list(
        payload.get("annotations"), label="review annotations"
    )
    if not all(isinstance(item, dict) for item in raw_annotations):
        raise ValueError("Every review annotation must be an object.")
    annotations = [ReviewAnnotation.from_dict(item) for item in raw_annotations]
    annotation_ids = [annotation.annotation_id for annotation in annotations]
    if len(set(annotation_ids)) != len(annotation_ids):
        raise ValueError("Review annotation IDs must be unique.")
    return annotations


def append_operation_journal(path: Path, entry: dict[str, Any]) -> Path:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        entry,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    with target.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return target


def append_operation_journal_once(
    path: Path,
    entry: dict[str, Any],
) -> tuple[Path, bool]:
    """Append one durable event, deduplicated by its persisted event ID."""

    event_id = str(entry.get("event_id") or "").strip()
    if not event_id:
        raise ValueError("Idempotent journal entries require an event_id.")
    target = path.expanduser().resolve()
    if target.is_file():
        for existing in read_operation_journal(target):
            if str(existing.get("event_id") or "") == event_id:
                return target, False
    append_operation_journal(target, entry)
    return target, True


def read_operation_journal(path: Path) -> list[dict[str, Any]]:
    target = path.expanduser()
    if not target.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        target.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Journal line {line_number} is not an object.")
        entries.append(payload)
    return entries


__all__ = [
    "CANVAS_SESSION_FILENAME",
    "COMPOSITION_FILENAME",
    "OPERATION_JOURNAL_FILENAME",
    "REVIEW_ANNOTATIONS_FILENAME",
    "append_operation_journal",
    "append_operation_journal_once",
    "atomic_write_json",
    "load_canvas_session",
    "load_composition_project",
    "load_review_annotations",
    "read_operation_journal",
    "save_canvas_session",
    "save_composition_project",
    "save_review_annotations",
]
