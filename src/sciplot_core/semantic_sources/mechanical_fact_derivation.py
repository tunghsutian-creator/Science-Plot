"""Derive specimen observations and representative mechanical curves."""

from __future__ import annotations

import json
import math
import statistics
from decimal import Decimal
from typing import Any

from sciplot_core.materials_rules import (
    ELONGATION_AT_BREAK_METRIC,
    tensile_curve_metric_values,
)
from sciplot_core.semantic_sources.mechanical_fact_models import (
    MECHANICAL_METRIC_UNITS,
    MechanicalSummaryObservation,
    fail_mechanical_source_facts as _fail,
)
from sciplot_core.semantic_sources.mechanical_sources import (
    _NON_TENSILE_MECHANICAL_CONTRACTS,
)
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.series_labels import (
    _intake_group_name,
    _with_series_sample,
)
from sciplot_core.semantic_sources.series_ordering import _order_curve_series


_TENSILE_METRICS = (
    "strength_MPa",
    ELONGATION_AT_BREAK_METRIC,
    "modulus_MPa",
    "toughness_MJ_m3",
)


def derive_mechanical_source_projection(
    series: list[CurveSeriesPayload],
    *,
    supplied_rows: list[dict[str, Any]] | None,
    rule_id: str,
    curated: bool,
) -> tuple[
    tuple[MechanicalSummaryObservation, ...],
    tuple[str, ...],
    tuple[tuple[str, int], ...],
    tuple[CurveSeriesPayload, ...],
]:
    """Validate raw values and close observations, counts, and representatives."""

    _validate_curve_series(series)
    observations = (
        _observations_from_rows(supplied_rows, rule_id=rule_id)
        if supplied_rows is not None
        else tuple(_observation_for_series(item, rule_id=rule_id) for item in series)
    )
    sample_order = _sample_order(series, observations)
    observations = _order_observations(observations, sample_order)
    replicate_counts = _replicate_counts(observations, sample_order)
    representatives = (
        tuple(_with_series_sample(item, item.sample) for item in series)
        if curated
        else _representative_series(series, rule_id=rule_id)
    )
    representatives = tuple(
        _order_curve_series(list(representatives), list(sample_order))
    )
    return observations, sample_order, replicate_counts, representatives


def _observation_for_series(
    series: CurveSeriesPayload, *, rule_id: str
) -> MechanicalSummaryObservation:
    diagnostics = series.diagnostics or {}
    group = _intake_group_name(series.sample) or series.sample
    replicate = str(diagnostics.get("replicate_label") or _replicate_name(series))
    if rule_id == "tensile_curve":
        reported = {
            metric: float(diagnostics[metric])
            for metric in _TENSILE_METRICS[:3]
            if diagnostics.get(metric) is not None
        }
        values = tensile_curve_metric_values(
            series.points, x_unit=series.x_unit, reported=reported
        )
        metrics = tuple(
            (metric, float(values[metric]))
            for metric in _TENSILE_METRICS
            if metric in values and math.isfinite(float(values[metric]))
        )
        details = tuple(
            (key, _diagnostic_text(value))
            for key, value in values.items()
            if key not in _TENSILE_METRICS
        )
    else:
        contract = _NON_TENSILE_MECHANICAL_CONTRACTS[rule_id]
        metric = str(contract["strength_metric"])
        stresses = [float(value) for _x, value in series.points]
        magnitude = bool(contract["magnitude"])
        strength = max(abs(value) for value in stresses) if magnitude else max(stresses)
        metrics = ((metric, strength),)
        details = (
            (
                "strength_source",
                "curve_maximum_magnitude" if magnitude else "curve_maximum",
            ),
        )
    source_file = str(diagnostics.get("source_file") or "")
    if not source_file:
        _fail(
            "mechanical_source_file_missing",
            f"No source file recorded for {series.sample!r}.",
        )
    headers = diagnostics.get("reported_metric_headers")
    if headers:
        details = (*details, ("reported_metric_headers", _diagnostic_text(headers)))
    return MechanicalSummaryObservation(group, replicate, metrics, source_file, details)


def _observations_from_rows(
    rows: list[dict[str, Any]], *, rule_id: str
) -> tuple[MechanicalSummaryObservation, ...]:
    metric_names = tuple(metric for metric, _unit in MECHANICAL_METRIC_UNITS[rule_id])
    result: list[MechanicalSummaryObservation] = []
    for index, row in enumerate(rows, start=1):
        sample = str(row.get("sample") or "").strip()
        replicate = str(row.get("replicate") or f"replicate {index}").strip()
        metrics = tuple(
            (metric, float(row[metric]))
            for metric in metric_names
            if row.get(metric) is not None and math.isfinite(float(row[metric]))
        )
        source_file = str(row.get("source_file") or "").strip()
        if not sample or not metrics or not source_file:
            _fail(
                "mechanical_summary_row_invalid",
                "A specimen summary row is incomplete.",
            )
        _validate_reported_metric_units(
            row,
            metrics=metrics,
            rule_id=rule_id,
        )
        details = tuple(
            (str(key), _diagnostic_text(value))
            for key, value in row.items()
            if key not in {"sample", "replicate", "source_file", *metric_names}
            and value is not None
        )
        result.append(
            MechanicalSummaryObservation(
                sample, replicate, metrics, source_file, details
            )
        )
    return tuple(result)


def _validate_reported_metric_units(
    row: dict[str, Any],
    *,
    metrics: tuple[tuple[str, float], ...],
    rule_id: str,
) -> None:
    raw_headers = row.get("reported_metric_headers")
    try:
        headers = (
            json.loads(raw_headers)
            if isinstance(raw_headers, str)
            else dict(raw_headers or {})
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Mechanical reported metric headers are invalid.") from exc
    required_units = dict(MECHANICAL_METRIC_UNITS[rule_id])
    for metric, _value in metrics:
        header = str(headers.get(metric) or "")
        expected = required_units[metric]
        normalized = header.casefold().replace(" ", "")
        unit_is_explicit = (
            (expected == "%" and ("%" in header or "percent" in normalized))
            or (expected == "MPa" and "mpa" in normalized)
            or (
                expected == "MJ/m3"
                and (
                    "mj/m3" in normalized
                    or "mjm⁻³" in normalized
                    or "mjm-3" in normalized
                )
            )
        )
        if not unit_is_explicit:
            _fail(
                "mechanical_summary_unit_unverified",
                f"Reported metric {metric!r} does not declare required unit "
                f"{expected!r} in its source header.",
            )


def _representative_series(
    series_list: list[CurveSeriesPayload], *, rule_id: str
) -> tuple[CurveSeriesPayload, ...]:
    groups: dict[str, list[CurveSeriesPayload]] = {}
    for series in series_list:
        groups.setdefault(
            _intake_group_name(series.sample) or series.sample, []
        ).append(series)
    representatives: list[CurveSeriesPayload] = []
    metric_id = (
        _TENSILE_METRICS[0]
        if rule_id == "tensile_curve"
        else str(_NON_TENSILE_MECHANICAL_CONTRACTS[rule_id]["strength_metric"])
    )
    for group, items in groups.items():
        observations = [
            _observation_for_series(item, rule_id=rule_id) for item in items
        ]
        median_primary = statistics.median(
            _decimal_metric(item, metric_id) for item in observations
        )
        secondary_metric = (
            ELONGATION_AT_BREAK_METRIC if rule_id == "tensile_curve" else None
        )
        median_secondary = (
            statistics.median(
                _decimal_metric(item, secondary_metric) for item in observations
            )
            if secondary_metric is not None
            else 0.0
        )
        selected = min(
            enumerate(zip(items, observations, strict=True)),
            key=lambda pair: (
                abs(_decimal_metric(pair[1][1], metric_id) - median_primary),
                abs(_decimal_metric(pair[1][1], secondary_metric) - median_secondary)
                if secondary_metric is not None
                else 0.0,
                pair[0],
            ),
        )[1][0]
        representatives.append(_with_series_sample(selected, group))
    return tuple(representatives)


def _sample_order(
    series: list[CurveSeriesPayload], rows: tuple[MechanicalSummaryObservation, ...]
) -> tuple[str, ...]:
    order = list(
        dict.fromkeys(_intake_group_name(item.sample) or item.sample for item in series)
    )
    order.extend(row.sample for row in rows if row.sample not in order)
    if not order:
        _fail("mechanical_sample_order_missing", "No mechanical samples were resolved.")
    return tuple(order)


def _replicate_counts(
    rows: tuple[MechanicalSummaryObservation, ...], sample_order: tuple[str, ...]
) -> tuple[tuple[str, int], ...]:
    counts = tuple(
        (sample, sum(row.sample == sample for row in rows)) for sample in sample_order
    )
    if any(count < 1 for _sample, count in counts):
        _fail(
            "mechanical_replicate_count_invalid",
            "Every sample needs a raw specimen observation.",
        )
    return counts


def _validate_curve_series(series: list[CurveSeriesPayload]) -> None:
    if not series or len({item.sample for item in series}) != len(series):
        _fail(
            "mechanical_curve_identity_ambiguous",
            "Mechanical curve identities must be explicit and unique.",
        )
    for item in series:
        if item.x_unit != "%" or item.y_unit != "MPa" or len(item.points) < 2:
            _fail(
                "mechanical_curve_unit_or_points_invalid",
                "Mechanical curves require at least two points in % and MPa.",
            )
        if not all(
            math.isfinite(float(x)) and math.isfinite(float(y)) for x, y in item.points
        ):
            _fail(
                "mechanical_curve_nonfinite", "Mechanical curve points must be finite."
            )


def _order_observations(
    rows: tuple[MechanicalSummaryObservation, ...], sample_order: tuple[str, ...]
) -> tuple[MechanicalSummaryObservation, ...]:
    rank = {sample: index for index, sample in enumerate(sample_order)}
    ordered = sorted(
        enumerate(rows),
        key=lambda pair: (rank.get(pair[1].sample, len(rank)), pair[0]),
    )
    return tuple(row for _index, row in ordered)


def _required_metric(observation: MechanicalSummaryObservation, metric: str) -> float:
    value = observation.metric_value(metric)
    if value is None or not math.isfinite(value):
        _fail(
            "mechanical_representative_metric_missing",
            f"Representative selection requires finite {metric!r} values.",
        )
    return value


def _decimal_metric(observation: MechanicalSummaryObservation, metric: str) -> Decimal:
    return Decimal(str(_required_metric(observation, metric)))


def _replicate_name(series: CurveSeriesPayload) -> str:
    return series.sample.split("__", 1)[1] if "__" in series.sample else series.sample


def _diagnostic_text(value: object) -> str:
    if isinstance(value, dict | list | tuple):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


__all__ = ["derive_mechanical_source_projection"]
