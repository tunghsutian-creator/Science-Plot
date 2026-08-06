"""Validate complete terminal evidence before installing rheology figures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import CartesianMetricBinding, ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.policy import normalize_export_formats
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.terminal_request import normalize_terminal_render_request
from sciplot_core.workflow.rheology_task_sources import RheologyTaskSource


_TEMPERATURE_BINDING_MISMATCH = "temperature_terminal_source_binding_mismatch"


def validate_temperature_task_sources(
    records: list[RheologyTaskSource],
    *,
    figure_plan: ResolvedFigurePlan,
    source_attestation: PreparationSourceAttestation | None,
) -> None:
    """Require the exact two internally bound temperature metric tables."""

    expected = (
        ("temp_storage_modulus", "storage_modulus_vs_temperature", "storage_modulus"),
        ("temp_loss_factor", "tan_delta_vs_temperature", "loss_factor"),
    )
    actual: list[tuple[str, str, str]] = []
    sample_order: tuple[str, ...] | None = None
    if (
        source_attestation is None
        or figure_plan.source_sha256 != source_attestation.source_tree_sha256_after
    ):
        _fail("FigurePlan source identity diverged from semantic preparation")
    if len(figure_plan.tasks) != len(expected):
        _fail("FigurePlan does not contain exactly two temperature tasks")
    if len(records) != len(expected):
        raise ValueError(
            "temperature_metric_source_unavailable: temperature Workflow must "
            "materialize exactly two metric sources."
        )
    for record, task in zip(records, figure_plan.tasks, strict=True):
        binding = record.binding
        if binding is None:
            _fail("every required metric table needs a private terminal binding")
        binding.verify_sources()
        if (
            binding.rule_id != "rheology_temperature_sweep"
            or binding.template != "point_line"
            or binding.x_metric != "temperature"
            or Path(binding.terminal_source.path) != record.source.resolve()
            or task.figure_id != binding.task_key
            or task.artifact_stem != record.metric_id
            or task.template != binding.template
            or task.sample_order != binding.sample_order
        ):
            _fail("metric table and terminal binding identities diverged")
        metric_binding = task.metric_binding
        if (
            not isinstance(metric_binding, CartesianMetricBinding)
            or metric_binding.x_metric != binding.x_metric
            or metric_binding.y_metric != binding.y_metric
        ):
            _fail("FigureTask metric binding diverged from terminal authority")
        if sample_order is None:
            sample_order = binding.sample_order
        elif sample_order != binding.sample_order:
            _fail("both temperature tasks must preserve one source-derived order")
        actual.append((record.metric_id, binding.task_key, binding.y_metric))
    if tuple(actual) != expected:
        raise ValueError(
            "temperature_metric_source_unavailable: temperature Workflow must "
            "materialize exactly storage modulus then loss factor."
        )


def validate_temperature_render_payload(
    payload: dict[str, Any],
    *,
    record: RheologyTaskSource,
    task: FigureTask,
    metric_dir: Path,
    export_formats: object,
) -> None:
    """Require one complete export, editable document, spec, and QA record."""

    binding = record.binding
    if binding is None:
        _fail("rendered metric has no private terminal binding")
    requested_formats = normalize_export_formats(export_formats)
    if payload.get("export_formats") != list(requested_formats):
        _fail("renderer export-format evidence diverged from the request")

    exports = payload.get("exports")
    if not isinstance(exports, list) or len(exports) != len(requested_formats):
        _fail("renderer did not return every requested metric export")
    export_paths: list[Path] = []
    actual_formats: list[str] = []
    for item in exports:
        if not isinstance(item, dict):
            _fail("renderer returned a malformed metric export record")
        actual_formats.append(str(item.get("format") or ""))
        export_paths.append(
            _existing_scoped_file(
                item.get("path"), root=metric_dir, label="metric export"
            )
        )
    if tuple(actual_formats) != requested_formats:
        _fail("renderer returned unexpected or reordered metric export formats")
    if payload.get("outputs") != [str(path) for path in export_paths]:
        _fail("renderer output paths diverged from its export records")

    worker_root = (metric_dir / "_veusz").resolve()
    documents = _single_path(payload, "veusz_documents", worker_root, "Veusz document")
    specs = _single_path(payload, "veusz_specs", worker_root, "Veusz specification")
    document_path = documents[0]
    spec_path = specs[0]
    if document_path.suffix.casefold() != ".vsz":
        _fail("terminal document is not an editable VSZ")
    if spec_path.suffix.casefold() != ".json":
        _fail("terminal specification is not JSON")

    qa_reports = payload.get("qa_reports")
    if (
        not isinstance(qa_reports, list)
        or len(qa_reports) != 1
        or not isinstance(qa_reports[0], dict)
    ):
        _fail("each temperature metric needs exactly one QA report")

    terminal_requests = payload.get("terminal_render_requests")
    if (
        not isinstance(terminal_requests, list)
        or len(terminal_requests) != 1
        or not isinstance(terminal_requests[0], dict)
    ):
        _fail("each temperature metric needs exactly one terminal request")
    terminal_request = terminal_requests[0]
    if not _request_matches_binding(
        terminal_request,
        record,
        task=task,
        canonical=True,
    ):
        _fail("terminal request identity or order diverged from its binding")

    spec = _read_object(spec_path, label="terminal specification")
    if spec.get("template") != binding.template:
        _fail("terminal specification template diverged from its binding")
    source_request = spec.get("source_request")
    if not isinstance(source_request, dict) or not _request_matches_binding(
        source_request,
        record,
        task=task,
        canonical=False,
    ):
        _fail("terminal specification source request diverged from its binding")
    _validate_spec_series(spec.get("series"), record=record)

    request_paths = list(worker_root.rglob("plot_request.json"))
    if len(request_paths) != 1:
        _fail("terminal worker request inventory is incomplete or ambiguous")
    worker_request = _read_object(request_paths[0], label="terminal worker request")
    ledger = worker_request.get("transform_ledger")
    steps = ledger.get("steps", []) if isinstance(ledger, dict) else []
    if any(
        isinstance(step, dict)
        and step.get("implementation_ref")
        == "sciplot_core.semantic.prepare_semantic_source"
        for step in steps
    ):
        _fail("terminal worker repeated semantic source preparation")
    if list(worker_root.rglob("rheology_temperature_comparison.xlsx")):
        _fail("terminal worker materialized a second temperature workbook")


def _validate_spec_series(value: object, *, record: RheologyTaskSource) -> None:
    binding = record.binding
    assert binding is not None
    if not isinstance(value, list) or len(value) != len(binding.sample_order):
        _fail("terminal specification series coverage is incomplete")
    expected_counts = dict(binding.point_counts)
    expected_artifacts = [binding.terminal_source.to_payload()]
    for sample, item in zip(binding.sample_order, value, strict=True):
        if not isinstance(item, dict) or item.get("label") != sample:
            _fail("terminal specification series order diverged from source")
        x_values = item.get("x_values")
        y_values = item.get("y_values")
        if (
            not isinstance(x_values, list)
            or not isinstance(y_values, list)
            or len(x_values) != expected_counts[sample]
            or len(y_values) != expected_counts[sample]
        ):
            _fail(f"terminal point count diverged for sample {sample!r}")
        if item.get("source_artifacts") != expected_artifacts:
            _fail(f"terminal source artifact diverged for sample {sample!r}")


def _request_matches_binding(
    request: dict[str, Any],
    record: RheologyTaskSource,
    *,
    task: FigureTask,
    canonical: bool,
) -> bool:
    binding = record.binding
    assert binding is not None
    try:
        if canonical:
            normalized = normalize_terminal_render_request(
                request,
                label="temperature terminal request",
            )
            if normalized != request:
                return False
        request_task = FigureTask.from_payload(request["resolved_figure_task"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        request_task == task
        and request.get("rule_id") == binding.rule_id
        and request.get("template") == binding.template
        and request.get("x_metric") == binding.x_metric
        and request.get("y_metric") == binding.y_metric
        and request.get("series_order") == list(binding.sample_order)
    )


def _single_path(
    payload: dict[str, Any], key: str, root: Path, label: str
) -> tuple[Path]:
    values = payload.get(key)
    if not isinstance(values, list) or len(values) != 1:
        _fail(f"each temperature metric needs exactly one {label}")
    return (_existing_scoped_file(values[0], root=root, label=label),)


def _existing_scoped_file(value: object, *, root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label} path is missing")
    path = Path(value).expanduser().resolve()
    if not path.is_file() or not path.is_relative_to(root.resolve()):
        _fail(f"{label} is absent or escaped its metric transaction")
    return path


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"{_TEMPERATURE_BINDING_MISMATCH}: {label} could not be read."
        ) from exc
    if not isinstance(payload, dict):
        _fail(f"{label} is not an object")
    return payload


def _fail(message: str) -> None:
    raise ValueError(f"{_TEMPERATURE_BINDING_MISMATCH}: {message}.")


__all__ = [
    "validate_temperature_render_payload",
    "validate_temperature_task_sources",
]
