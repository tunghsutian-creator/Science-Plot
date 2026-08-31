"""Bind Impact FigureTasks to one validated, private execution snapshot."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any, NoReturn
from uuid import uuid4

import pandas as pd

from sciplot_core.figure_plan import (
    FigurePlanResolutionError,
    ResolvedFigurePlan,
    source_tree_sha256,
)
from sciplot_core.figure_plan.impact_resolution import (
    resolve_impact_plan_from_payloads,
)
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.semantic_sources.models import ImpactReplicatePayload
from sciplot_core.studio_core.figure_task_evidence import figure_queue_item_from_task
from sciplot_core.studio_core.mechanical_task_source_lifecycle import (
    _private_figure_task_source_root,
)


def validated_impact_plan_snapshot(
    plan: ResolvedFigurePlan,
    *,
    template: str,
    request: dict[str, Any],
    source_root: Path,
    workbook: Path,
) -> tuple[list[tuple[str, ImpactReplicatePayload]], str]:
    """Read once and prove that the complete execution plan is still current."""

    expected_hash = plan.source_sha256
    if expected_hash is None or _impact_source_hash(source_root) != expected_hash:
        _source_changed(
            "Resolved impact conditions do not match the current source snapshot."
        )
    from sciplot_core.semantic_sources.impact_sources import (
        read_impact_condition_payloads,
    )

    try:
        payloads = read_impact_condition_payloads(workbook)
    except (OSError, ValueError) as exc:
        raise FigurePlanResolutionError(
            "impact_condition_source_changed",
            "Resolved impact conditions can no longer be read from the source.",
        ) from exc
    if _impact_source_hash(source_root) != expected_hash:
        _source_changed("The impact source changed while condition payloads were read.")
    current_plan = resolve_impact_plan_from_payloads(
        payloads,
        template=template,
        request=request,
        source_sha256=expected_hash,
    )
    if current_plan.plan_sha256 != plan.plan_sha256:
        _source_changed("Resolved impact task identity changed before execution.")
    workbook_hash = existing_file_sha256(workbook)
    if workbook_hash is None or _impact_source_hash(source_root) != expected_hash:
        _source_changed(
            "The impact source changed while its execution snapshot was bound."
        )
    return payloads, workbook_hash


def materialize_impact_condition_sources(
    plan: ResolvedFigurePlan,
    *,
    condition_payloads: list[tuple[str, ImpactReplicatePayload]],
    project_dir: Path,
) -> list[dict[str, Any]]:
    """Write every categorical task into one rollback-owned private directory."""

    output_dir = _new_source_directory(project_dir, plan=plan)
    queue: list[dict[str, Any]] = []
    try:
        for task, (condition, payload) in zip(
            plan.tasks,
            condition_payloads,
            strict=True,
        ):
            condition_source = output_dir / f"{task.document_stem}.csv"
            pd.DataFrame(payload.rows).to_csv(
                condition_source,
                header=False,
                index=False,
            )
            queue.append(
                {
                    **figure_queue_item_from_task(task),
                    "condition": condition,
                    "condition_source": str(condition_source),
                    "replicate_counts": dict(task.replicate_counts),
                    "supported_templates": [
                        "bar",
                        "box",
                        "box_strip",
                        "point_line",
                    ],
                    "presentation_data_shape": "categorical_replicates",
                }
            )
    except BaseException:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise
    return queue


def materialize_impact_point_line_source(
    plan: ResolvedFigurePlan,
    *,
    source_root: Path,
    workbook: Path,
    workbook_hash: str,
    project_dir: Path,
) -> Path:
    """Copy one verified workbook so rendering cannot reread mutable raw input."""

    output_dir = _new_source_directory(project_dir, plan=plan)
    destination = (
        output_dir / f"{plan.tasks[0].document_stem}{workbook.suffix.casefold()}"
    )
    try:
        shutil.copy2(workbook, destination)
        if (
            existing_file_sha256(destination) != workbook_hash
            or _impact_source_hash(source_root) != plan.source_sha256
        ):
            _source_changed(
                "The impact source changed while its point-line snapshot was copied."
            )
    except BaseException:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise
    return destination


def _new_source_directory(
    project_dir: Path,
    *,
    plan: ResolvedFigurePlan,
) -> Path:
    try:
        source_root = _private_figure_task_source_root(
            project_dir,
            source_kind="impact_conditions",
        )
        output_dir = source_root / f"{plan.plan_id}_{uuid4().hex}"
        output_dir.mkdir(exist_ok=False)
        if output_dir.is_symlink() or output_dir.resolve().parent != source_root:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise ValueError("private Impact source directory escaped its project")
    except (OSError, ValueError) as exc:
        raise FigurePlanResolutionError(
            "impact_condition_source_changed",
            "Impact task sources require an ordinary project-owned directory.",
        ) from exc
    return output_dir


def _impact_source_hash(source: Path) -> str | None:
    try:
        return source_tree_sha256(source)
    except OSError as exc:
        raise FigurePlanResolutionError(
            "impact_condition_source_changed",
            "The resolved impact source snapshot is no longer readable.",
        ) from exc


def _source_changed(message: str) -> NoReturn:
    raise FigurePlanResolutionError("impact_condition_source_changed", message)


__all__ = [
    "materialize_impact_condition_sources",
    "materialize_impact_point_line_source",
    "validated_impact_plan_snapshot",
]
