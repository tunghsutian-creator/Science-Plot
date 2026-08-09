"""Build route-neutral terminal evidence for a mechanical FigurePlan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.figure_plan import ResolvedFigurePlan
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.mechanical_figure_contract import mechanical_figure_contract
from sciplot_core.mechanical_task_sources import MechanicalTaskSource
from sciplot_core.policy import MIN_BOX_REPLICATES


def build_mechanical_execution_evidence(
    *,
    plan: ResolvedFigurePlan,
    records: list[MechanicalTaskSource],
    specs_by_figure_id: dict[str, Path],
) -> dict[str, Any]:
    """Return one path-free signature after terminal validation has passed."""

    if (
        len(records) != len(plan.tasks)
        or tuple(record.task for record in records) != plan.tasks
    ):
        _fail("task source order")
    contract = mechanical_figure_contract(plan.rule_id)
    tasks: list[dict[str, Any]] = []
    for record, task_contract in zip(records, contract.tasks, strict=True):
        spec_path = specs_by_figure_id.get(record.task.figure_id)
        if spec_path is None or not spec_path.is_file():
            _fail("terminal spec inventory")
        spec = _read_object(spec_path)
        source_request = _object(spec.get("source_request"), "source_request")
        if (
            spec.get("template") != record.task.template
            or source_request.get("resolved_figure_task") != record.task.to_payload()
        ):
            _fail("terminal task identity")
        axes = _object(spec.get("axes"), "axes")
        x_axis = _object(axes.get("x"), "axes.x")
        y_axis = _object(axes.get("y"), "axes.y")
        series = _series_projection(spec.get("series"))
        palette_resolution = _object(
            spec.get("palette_resolution"),
            "palette resolution",
        )
        encoding_contract = _object(
            spec.get("series_encoding_contract"),
            "series encoding contract",
        )
        if (
            palette_resolution.get("kind") != "sciplot_palette_resolution"
            or palette_resolution.get("version") != 1
            or not isinstance(palette_resolution.get("palette_id"), str)
            or encoding_contract.get("kind") != "sciplot_series_encoding_contract"
            or encoding_contract.get("version") != 1
        ):
            _fail("palette or series-encoding identity")
        source_binding = _source_binding_projection(record)
        task_evidence: dict[str, Any] = {
            "figure_id": record.task.figure_id,
            "task_sha256": canonical_json_sha256(
                record.task.to_payload(),
                allow_nan=False,
            ),
            "task_kind": record.task_kind,
            "template": record.task.template,
            "metric_binding": record.task.metric_binding.to_payload()
            if record.task.metric_binding is not None
            else None,
            "sample_order": list(record.binding.sample_order),
            "replicate_counts": [
                {"sample": sample, "count": count}
                for sample, count in record.task.replicate_counts
            ],
            "point_counts": [
                {"sample": sample, "count": count}
                for sample, count in record.binding.point_counts
            ],
            "units": {
                "x": task_contract.x_unit,
                "y": record.unit,
                "display_x": x_axis.get("label"),
                "display_y": y_axis.get("label"),
            },
            "source_binding": source_binding,
            "source_binding_sha256": canonical_json_sha256(
                source_binding,
                allow_nan=False,
            ),
            "terminal_series_sha256": canonical_json_sha256(
                series,
                allow_nan=False,
            ),
            "palette_resolution": palette_resolution,
            "series_encoding_contract": encoding_contract,
            "series_encodings": [item["encoding"] for item in series],
        }
        if record.task_kind == "summary":
            categorical = _object(spec.get("categorical"), "categorical")
            summary_groups = _summary_groups(
                spec,
                record=record,
                series=series,
            )
            task_evidence["statistics_method"] = task_contract.statistics_method
            task_evidence["summary_groups"] = summary_groups
            task_evidence["raw_values_preserved"] = (
                categorical.get("raw_values_preserved") is True
            )
            task_evidence["raw_points_visible"] = all(
                group["raw_points_visible"] is True for group in summary_groups
            )
        else:
            task_evidence["curve_series"] = [
                {
                    "sample": item["label"],
                    "point_count": len(item["x_values"]),
                }
                for item in series
            ]
        tasks.append(task_evidence)
    evidence: dict[str, Any] = {
        "kind": "sciplot_mechanical_execution_evidence",
        "version": 1,
        "rule_id": plan.rule_id,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "source_sha256": plan.source_sha256,
        "figure_ids": list(plan.selected_figure_ids),
        "tasks": tasks,
    }
    evidence["evidence_sha256"] = canonical_json_sha256(
        evidence,
        allow_nan=False,
    )
    return evidence


def _summary_groups(
    spec: dict[str, Any],
    *,
    record: MechanicalTaskSource,
    series: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    categorical = _object(spec.get("categorical"), "categorical")
    groups = categorical.get("groups")
    if not isinstance(groups, list) or len(groups) != len(record.groups):
        _fail("summary group inventory")
    evidence: list[dict[str, Any]] = []
    for raw, terminal, terminal_series in zip(
        record.groups,
        groups,
        series,
        strict=True,
    ):
        terminal_group = _object(terminal, "categorical group")
        statistics = _object(
            terminal_group.get("descriptive_statistics"),
            "descriptive statistics",
        )
        expected_status = (
            "boxplot"
            if len(raw.values) >= MIN_BOX_REPLICATES
            else "insufficient_replicates"
        )
        encoding = _object(terminal_series.get("encoding"), "series encoding")
        marker = _object(encoding.get("marker"), "encoding.marker")
        raw_points_visible = (
            terminal_group.get("raw_points_visible") is True
            and terminal_series.get("raw_points_visible") is True
            and marker.get("fill_visible") is True
        )
        if (
            terminal_group.get("label") != raw.sample
            or terminal_group.get("replicate_count") != len(raw.values)
            or not raw_points_visible
            or terminal_group.get("summary_status") != expected_status
        ):
            _fail("summary raw-point identity")
        evidence.append(
            {
                "sample": raw.sample,
                "replicates": list(raw.replicates),
                "raw_values": list(raw.values),
                "n": len(raw.values),
                "minimum": statistics.get("minimum"),
                "q1": statistics.get("q1"),
                "median": statistics.get("median"),
                "q3": statistics.get("q3"),
                "maximum": statistics.get("maximum"),
                "raw_points_visible": raw_points_visible,
                "summary_status": expected_status,
                "boxplot_visible": expected_status == "boxplot",
            }
        )
    return evidence


def _source_binding_projection(record: MechanicalTaskSource) -> dict[str, Any]:
    binding = record.binding
    return {
        "raw_source_sha256": [item.sha256 for item in binding.raw_sources],
        "prepared_source_sha256": binding.prepared_source.sha256,
        "terminal_source_sha256": binding.terminal_source.sha256,
        "task_key": binding.task_key,
        "rule_id": binding.rule_id,
        "template": binding.template,
        "x_metric": binding.x_metric,
        "y_metric": binding.y_metric,
    }


def _series_projection(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        _fail("terminal series")
    projection: list[dict[str, Any]] = []
    for item in value:
        record = _object(item, "series")
        x_values = record.get("x_values")
        y_values = record.get("y_values")
        if not isinstance(x_values, list) or not isinstance(y_values, list):
            _fail("terminal series coordinates")
        projection.append(
            {
                "label": record.get("label"),
                "x_values": x_values,
                "y_values": y_values,
                "encoding": record.get("encoding"),
                "raw_points_visible": record.get("raw_points_visible"),
            }
        )
    return projection


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            "mechanical_execution_evidence_mismatch: terminal spec is invalid."
        ) from exc
    return _object(value, "terminal spec")


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(label)
    return value


def _fail(field: str) -> NoReturn:
    raise ValueError(
        "mechanical_execution_evidence_mismatch: "
        f"{field} conflicts with the selected mechanical FigurePlan."
    )


__all__ = ["build_mechanical_execution_evidence"]
