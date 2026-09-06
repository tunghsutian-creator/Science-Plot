"""Recover exact registered FigureTask tables for managed data delivery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import resolved_figure_plan_from_payload
from sciplot_core.source_coverage.file_snapshots import (
    _assert_snapshot_current,
    _stable_file_snapshot,
)
from sciplot_core.source_coverage.managed_documents import (
    _source_records,
    _verify_prepared_data,
)
from sciplot_core.studio_core.figure_task_evidence import (
    validate_veusz_spec_figure_task,
)


def registered_task_snapshot_sources(
    *,
    request: dict[str, Any],
    project_dir: Path,
    documents: list[Path],
    existing_sources: list[Path],
) -> list[Path]:
    """Include task tables only after their persisted task and data checks.

    Preparation's private worker seal is not a persisted certificate. Here the
    evidence is the validated FigurePlan, recorded source hash, and reproducible
    prepared table -> spec data contract. The caller separately verifies raw
    source fingerprints and preparation lineage.
    """

    plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    additions: list[Path] = []
    root = project_dir.expanduser().resolve()
    for document in documents:
        spec_path = (
            document.with_name("spec.json")
            if document.name == "document.vsz"
            else document.with_suffix(".spec.json")
        )
        spec_snapshot = _stable_file_snapshot(spec_path, label="registered task spec")
        spec = json.loads(spec_snapshot["bytes"])
        records = _source_records(spec)
        extra = [
            path
            for path in records
            if not any(
                path == source or source.is_dir() and path.is_relative_to(source)
                for source in existing_sources
            )
        ]
        if not extra:
            continue
        source_request = spec.get("source_request")
        if plan is None or not isinstance(source_request, dict):
            raise ValueError(
                "Additional plotted tables require a registered FigureTask."
            )
        task_payload = source_request.get("resolved_figure_task")
        task = next(
            (task for task in plan.tasks if task.to_payload() == task_payload), None
        )
        if task is None:
            raise ValueError(
                "Additional plotted table task does not match the selected FigurePlan."
            )
        validate_veusz_spec_figure_task(
            spec, expected=task, source="managed plotted table"
        )
        input_value = source_request.get("input")
        if not isinstance(input_value, str) or not input_value:
            raise ValueError("Registered task table has no exact source input.")
        input_path = Path(input_value).expanduser()
        if input_path.resolve() != input_path or not input_path.is_file():
            raise ValueError("Registered task table input is not a canonical file.")
        if len(records) != 1 or len(extra) != 1:
            raise ValueError(
                "Registered task table and rendered source inventory disagree."
            )
        source_path = extra[0]
        for path in (input_path, source_path):
            if not path.is_relative_to(root / "studio" / "processed"):
                raise ValueError(
                    "Registered task table is outside its private processed directory."
                )
            candidate = path
            while candidate != root:
                if candidate.is_symlink():
                    raise ValueError(
                        "Registered task table cannot traverse a symbolic link."
                    )
                candidate = candidate.parent
        input_snapshot = _stable_file_snapshot(
            input_path, label="registered task input"
        )
        snapshot = _stable_file_snapshot(source_path, label="registered task table")
        if snapshot["sha256"] != records[source_path]:
            raise ValueError("Registered task table changed after rendering.")
        # Some semantic preparation writes an identical canonical table under
        # another filename. Permit that exact copy, not an unproved transform.
        if input_snapshot["sha256"] != snapshot["sha256"]:
            raise ValueError(
                "Registered task input and plotted table are not identical; "
                "a derived-table source proof is required."
            )
        _verify_prepared_data(spec, [snapshot])
        _assert_snapshot_current(snapshot, label="registered task table")
        _assert_snapshot_current(input_snapshot, label="registered task input")
        _assert_snapshot_current(spec_snapshot, label="registered task spec")
        additions.append(source_path)
    return list(dict.fromkeys([*existing_sources, *additions]))
