"""Immutable models for source-bound mechanical observations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from sciplot_core.mechanical_figure_contract import (
    MECHANICAL_FIGURE_CONTRACTS,
    MECHANICAL_RULE_IDS,
)
from sciplot_core.semantic_sources.models import CurveSeriesPayload


MECHANICAL_METRIC_UNITS = {
    rule_id: tuple((task.y_metric, task.y_unit) for task in contract.summary_tasks)
    for rule_id, contract in MECHANICAL_FIGURE_CONTRACTS.items()
}


class MechanicalSourceFactsError(ValueError):
    """Stable fail-closed error for ambiguous mechanical source facts."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class MechanicalSummaryObservation:
    """One retained specimen observation and its exact calculated metrics."""

    sample: str
    replicate: str
    metrics: tuple[tuple[str, float], ...]
    source_file: str
    diagnostics: tuple[tuple[str, str], ...] = ()

    def metric_value(self, metric: str) -> float | None:
        return dict(self.metrics).get(metric)

    def to_record(self) -> dict[str, object]:
        return {
            "sample": self.sample,
            "replicate": self.replicate,
            **dict(self.metrics),
            "source_file": self.source_file,
            **dict(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class MechanicalSourceFacts:
    """A source-hash-bound mechanical dataset with no materialized outputs."""

    rule_id: str
    source_root: Path
    source_sha256: str
    selected_sources: tuple[Path, ...]
    raw_series: tuple[CurveSeriesPayload, ...]
    individual_curve_series: tuple[CurveSeriesPayload, ...]
    representative_curve_series: tuple[CurveSeriesPayload, ...]
    summary_rows: tuple[MechanicalSummaryObservation, ...]
    sample_order: tuple[str, ...]
    replicate_counts: tuple[tuple[str, int], ...]
    x_label: str
    x_unit: str
    y_label: str
    y_unit: str
    metric_units: tuple[tuple[str, str], ...]
    curve_source_kind: str
    individual_curves_complete: bool

    def curve_series_for_mode(
        self, mode: object = None
    ) -> tuple[CurveSeriesPayload, ...]:
        normalized = normalize_mechanical_curve_mode(mode)
        if normalized == "individual":
            if not self.individual_curves_complete:
                fail_mechanical_source_facts(
                    "mechanical_individual_curves_unavailable",
                    "The reduced workbook contains authoritative representative "
                    "curves but not every specimen curve.",
                )
            return self.individual_curve_series
        return self.representative_curve_series

    def curve_sample_order(self, mode: object = None) -> tuple[str, ...]:
        return tuple(series.sample for series in self.curve_series_for_mode(mode))

    def curve_point_counts(self, mode: object = None) -> tuple[tuple[str, int], ...]:
        return tuple(
            (series.sample, len(series.points))
            for series in self.curve_series_for_mode(mode)
        )

    def summary_records(self) -> list[dict[str, object]]:
        return [row.to_record() for row in self.summary_rows]

    @property
    def point_counts(self) -> tuple[tuple[str, int], ...]:
        return self.curve_point_counts("representative")


def normalize_mechanical_curve_mode(value: object) -> str:
    token = str(value or "representative").strip().casefold()
    token = {"best": "representative", "all": "individual"}.get(token, token)
    if token == "mean":
        fail_mechanical_source_facts(
            "mechanical_curve_mean_unsupported",
            "Mechanical specimen curves cannot be averaged silently.",
        )
    if token not in {"representative", "individual"}:
        fail_mechanical_source_facts(
            "mechanical_curve_mode_invalid",
            "Mechanical curve mode must be representative or individual.",
        )
    return token


def fail_mechanical_source_facts(reason_code: str, message: str) -> NoReturn:
    raise MechanicalSourceFactsError(reason_code, message)


__all__ = [
    "MECHANICAL_METRIC_UNITS",
    "MECHANICAL_RULE_IDS",
    "MechanicalSourceFacts",
    "MechanicalSourceFactsError",
    "MechanicalSummaryObservation",
    "fail_mechanical_source_facts",
    "normalize_mechanical_curve_mode",
]
