"""Validate mechanical terminal evidence before a bundle is installed."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.mechanical_task_sources import MechanicalTaskSource
from sciplot_core.policy import normalize_export_formats
from sciplot_core.source_tables import load_curve_table
from sciplot_core.terminal_request import (
    TERMINAL_RENDER_REQUEST_FIELDS,
    normalize_terminal_render_request,
)
from sciplot_core.workflow.mechanical_summary_validation import (
    validate_mechanical_summary_spec,
)
from sciplot_core.workflow.mechanical_visual_validation import (
    validate_mechanical_visual_encoding,
)


_TERMINAL_MISMATCH = "mechanical_terminal_evidence_mismatch"
_validate_summary_spec = validate_mechanical_summary_spec
_validate_visual_encoding = validate_mechanical_visual_encoding


def validate_mechanical_render_payload(
    payload: dict[str, Any],
    *,
    record: MechanicalTaskSource,
    metric_dir: Path,
    export_formats: object,
) -> None:
    """Require exact task, source, data, spec, QA, and export evidence."""

    record.binding.verify_sources()
    _validate_exports(
        payload,
        metric_dir=metric_dir,
        export_formats=export_formats,
    )
    worker_root = (metric_dir / "_veusz").resolve()
    document = _single_path(
        payload,
        "veusz_documents",
        worker_root,
        "Veusz document",
    )[0]
    spec_path = _single_path(
        payload,
        "veusz_specs",
        worker_root,
        "Veusz specification",
    )[0]
    if document.suffix.casefold() != ".vsz" or spec_path.suffix.casefold() != ".json":
        _fail("editable document or specification type")
    qa_reports = payload.get("qa_reports")
    if (
        not isinstance(qa_reports, list)
        or len(qa_reports) != 1
        or not isinstance(qa_reports[0], dict)
    ):
        _fail("each task requires exactly one QA report")

    terminal_requests = payload.get("terminal_render_requests")
    if (
        not isinstance(terminal_requests, list)
        or len(terminal_requests) != 1
        or not isinstance(terminal_requests[0], dict)
        or not _request_matches_record(
            terminal_requests[0],
            record,
            canonical=True,
        )
    ):
        _fail("terminal request task or source identity")

    spec = _read_object(spec_path, label="terminal specification")
    terminal_request = terminal_requests[0]
    source_request = spec.get("source_request")
    if (
        spec.get("template") != record.binding.template
        or not isinstance(source_request, dict)
        or not _request_matches_record(source_request, record, canonical=False)
        or _terminal_request_projection(source_request) != terminal_request
    ):
        _fail("terminal specification request identity")
    axes = _object(spec.get("axes"), label="axes")
    x_axis = _object(axes.get("x"), label="axes.x")
    y_axis = _object(axes.get("y"), label="axes.y")
    if x_axis.get("label") != record.render_options.get(
        "x_label_override"
    ) or y_axis.get("label") != record.render_options.get("y_label_override"):
        _fail("terminal axis labels or display units")
    series = _series(spec.get("series"), record=record)
    _validate_visual_encoding(spec, series=series)
    if record.task_kind == "summary":
        _validate_summary_spec(spec, series=series, record=record)
    else:
        _validate_curve_spec(series, record=record)


def _validate_exports(
    payload: dict[str, Any],
    *,
    metric_dir: Path,
    export_formats: object,
) -> None:
    requested = normalize_export_formats(export_formats)
    if payload.get("export_formats") != list(requested):
        _fail("renderer export-format inventory")
    exports = payload.get("exports")
    if not isinstance(exports, list) or len(exports) != len(requested):
        _fail("complete requested export set")
    formats: list[str] = []
    paths: list[Path] = []
    for item in exports:
        if not isinstance(item, dict):
            _fail("well-formed export record")
        formats.append(str(item.get("format") or ""))
        paths.append(
            _existing_scoped_file(
                item.get("path"),
                root=metric_dir,
                label="task export",
            )
        )
    if tuple(formats) != requested or payload.get("outputs") != [
        str(path) for path in paths
    ]:
        _fail("ordered export formats and output paths")


def _request_matches_record(
    request: dict[str, Any],
    record: MechanicalTaskSource,
    *,
    canonical: bool,
) -> bool:
    try:
        normalized = (
            normalize_terminal_render_request(
                request,
                label="mechanical terminal request",
            )
            if canonical
            else request
        )
        if canonical and normalized != request:
            return False
        task = FigureTask.from_payload(request["resolved_figure_task"])
    except (KeyError, TypeError, ValueError):
        return False
    options = request.get("render_options")
    return (
        task == record.task
        and request.get("rule_id") == record.binding.rule_id
        and request.get("template") == record.binding.template
        and request.get("x_metric") == record.binding.x_metric
        and request.get("y_metric") == record.binding.y_metric
        and request.get("series_order") == list(record.binding.sample_order)
        and request.get("explicit_render_option_keys")
        == list(record.explicit_render_option_keys)
        and isinstance(options, dict)
        and options == json_safe(record.render_options)
    )


def _terminal_request_projection(request: dict[str, Any]) -> dict[str, Any]:
    return {
        field: request[field]
        for field in TERMINAL_RENDER_REQUEST_FIELDS
        if field in request
    }


def _series(
    value: object,
    *,
    record: MechanicalTaskSource,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(record.binding.sample_order):
        _fail("terminal series coverage")
    expected_counts = dict(record.binding.point_counts)
    expected_artifacts = [record.binding.terminal_source.to_payload()]
    result: list[dict[str, Any]] = []
    for sample, item in zip(record.binding.sample_order, value, strict=True):
        if not isinstance(item, dict) or item.get("label") != sample:
            _fail("terminal sample order")
        x_values = item.get("x_values")
        y_values = item.get("y_values")
        if (
            not isinstance(x_values, list)
            or not isinstance(y_values, list)
            or len(x_values) != expected_counts[sample]
            or len(y_values) != expected_counts[sample]
            or item.get("source_artifacts") != expected_artifacts
            or not all(
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                for value in [*x_values, *y_values]
            )
        ):
            _fail(f"terminal data or source binding for {sample!r}")
        result.append(item)
    return result


def _validate_curve_spec(
    series: list[dict[str, Any]],
    *,
    record: MechanicalTaskSource,
) -> None:
    expected = load_curve_table(record.source)
    if len(expected) != len(series):
        _fail("curve source series coverage")
    for source, item in zip(expected, series, strict=True):
        x_values = tuple(float(value) for value in item["x_values"])
        y_values = tuple(float(value) for value in item["y_values"])
        source_points = tuple(
            (float(x), float(y))
            for x, y in source.data.itertuples(index=False, name=None)
        )
        if source.sample != item["label"] or not _same_points(
            tuple(zip(x_values, y_values, strict=True)),
            source_points,
        ):
            _fail(f"curve values for {source.sample!r}")


def _same_points(
    actual: tuple[tuple[float, float], ...],
    expected: tuple[tuple[float, float], ...],
) -> bool:
    return len(actual) == len(expected) and all(
        _close(ax, ex) and _close(ay, ey)
        for (ax, ay), (ex, ey) in zip(actual, expected, strict=True)
    )


def _close(value: object, expected: float) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isclose(float(value), expected, rel_tol=1e-12, abs_tol=1e-12)
    )


def _single_path(
    payload: dict[str, Any],
    field: str,
    root: Path,
    label: str,
) -> list[Path]:
    values = payload.get(field)
    if not isinstance(values, list) or len(values) != 1:
        _fail(f"single {label}")
    return [_existing_scoped_file(values[0], root=root, label=label)]


def _existing_scoped_file(value: object, *, root: Path, label: str) -> Path:
    if not isinstance(value, str):
        _fail(label)
    path = Path(value).expanduser().resolve()
    if not path.is_file() or not path.is_relative_to(root.resolve()):
        _fail(label)
    return path


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{_TERMINAL_MISMATCH}: invalid {label}.") from exc
    return _object(value, label=label)


def _object(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(label)
    return value


def _fail(field: str) -> NoReturn:
    raise ValueError(
        f"{_TERMINAL_MISMATCH}: terminal {field} conflicts with the selected "
        "mechanical FigurePlan."
    )


__all__ = ["validate_mechanical_render_payload"]
