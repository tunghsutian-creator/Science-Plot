"""Resolve typed multi-metric rheology sweep source domains."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.foundation.text_values import clean_text
from sciplot_core.semantic_sources.models import (
    RheologySweepSample,
    _RHEOLOGY_COMPLEX_MODULUS_METRIC,
    _RHEOLOGY_FREQUENCY_OUTPUT_METRICS,
    _RHEOLOGY_SWEEP_METRICS,
)
from sciplot_core.semantic_sources.rheology_confirmation import (
    _confirmed_column_items,
    _read_confirmed_rheology_sweep_samples,
)
from sciplot_core.semantic_sources.rheology_ordering import _ordered_sweep_samples
from sciplot_core.semantic_sources.rheology_replicates import (
    _coalesce_replicate_sweep_samples,
)
from sciplot_core.semantic_sources.rheology_sweep_sources import (
    _read_rheology_frequency_comparison_samples,
    _read_rheology_temperature_comparison_samples,
)


TEMPERATURE_RULE_ID = "rheology_temperature_sweep"
TEMPERATURE_SAMPLE_METRICS = ("storage_modulus", "loss_factor")
FREQUENCY_RULE_ID = "rheology_frequency_sweep"

_METRIC_ORDER = tuple(
    metric[0]
    for metric in (*_RHEOLOGY_SWEEP_METRICS, _RHEOLOGY_COMPLEX_MODULUS_METRIC)
)

SourceHasher = Callable[[Path], str | None]
SweepReader = Callable[[Path], list[RheologySweepSample]]


class RheologySweepDomainError(ValueError):
    """Stable source-domain error translated at orchestration boundaries."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RheologySweepSourceFacts:
    """Stable planning facts projected from one parsed sweep snapshot."""

    source_sha256: str
    sample_order: tuple[str, ...]
    replicate_counts: tuple[tuple[str, int], ...]
    available_metrics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedRheologySweepDomain:
    """One parsed multi-metric snapshot shared by planning and preparation."""

    rule_id: str
    source: Path
    source_sha256: str
    selected_sources: tuple[Path, ...]
    raw_samples: tuple[RheologySweepSample, ...]
    prepared_samples: tuple[RheologySweepSample, ...]
    facts: RheologySweepSourceFacts

    def __post_init__(self) -> None:
        if self.rule_id not in {TEMPERATURE_RULE_ID, FREQUENCY_RULE_ID}:
            raise ValueError("Resolved rheology sweep domain has an unknown rule.")
        if self.source != self.source.expanduser().resolve():
            raise ValueError("Resolved rheology sweep source path must be absolute.")


def resolve_rheology_temperature_domain(
    input_path: Path,
    *,
    request: dict[str, Any],
) -> ResolvedRheologySweepDomain:
    """Resolve one temperature sweep without writes or cached state."""

    return _resolve_rheology_temperature_domain(
        input_path,
        request=request,
        source_hasher=source_tree_sha256,
        automatic_reader=_read_rheology_temperature_comparison_samples,
    )


def resolve_rheology_frequency_domain(
    input_path: Path,
    *,
    request: dict[str, Any],
) -> ResolvedRheologySweepDomain:
    """Resolve one raw-export frequency directory into the shared domain."""

    source = input_path.expanduser().resolve()
    if not source.is_dir():
        _fail(
            "frequency_source_unavailable",
            "Rheology frequency domain resolution requires a source directory.",
        )
    source_sha256_before = source_tree_sha256(source)
    if source_sha256_before is None:
        _fail(
            "frequency_source_unavailable",
            "SciPlot could not fingerprint the rheology-frequency source.",
        )
    try:
        try:
            raw_samples = _read_rheology_frequency_comparison_samples(source)
        except ValueError as automatic_error:
            column_confirmations = request.get("column_confirmations")
            if not _confirmed_column_items(column_confirmations):
                raise
            try:
                raw_samples = _read_confirmed_rheology_sweep_samples(
                    source,
                    column_confirmations,
                    x_label="Angular Frequency",
                    default_x_unit="rad/s",
                    metrics=_RHEOLOGY_FREQUENCY_OUTPUT_METRICS,
                )
            except ValueError as confirmed_error:
                raise ValueError(
                    "Rheology frequency preparation failed both automatic and "
                    f"confirmed parsing (automatic: {automatic_error}; "
                    f"confirmed: {confirmed_error})."
                ) from confirmed_error
    except (OSError, ValueError) as exc:
        raise RheologySweepDomainError(
            "frequency_source_unavailable",
            f"SciPlot could not read the rheology-frequency source: {exc}",
        ) from exc
    source_sha256_after = source_tree_sha256(source)
    if source_sha256_after != source_sha256_before:
        _fail(
            "frequency_source_changed_during_resolution",
            "The rheology-frequency source changed while its domain was being "
            "resolved.",
        )

    return _build_domain(
        rule_id=FREQUENCY_RULE_ID,
        source=source,
        source_sha256=source_sha256_after,
        raw_samples=raw_samples,
        request=request,
        empty_reason_code="frequency_source_unavailable",
        empty_message=(
            "Rheology frequency folders need at least one parseable sample export."
        ),
        ambiguous_reason_code="frequency_sample_identity_ambiguous",
        ambiguous_message=(
            "The prepared rheology-frequency samples do not have unique labels."
        ),
        lost_identity_message=(
            "A prepared rheology-frequency sample lost its raw replicate identity."
        ),
    )


def _resolve_rheology_temperature_domain(
    input_path: Path,
    *,
    request: dict[str, Any],
    source_hasher: SourceHasher,
    automatic_reader: SweepReader,
) -> ResolvedRheologySweepDomain:
    source = input_path.expanduser().resolve()
    source_sha256_before = source_hasher(source)
    if source_sha256_before is None:
        _fail(
            "temperature_source_unavailable",
            "SciPlot could not fingerprint the rheology-temperature source.",
        )
    try:
        try:
            raw_samples = automatic_reader(source)
        except ValueError as automatic_error:
            column_confirmations = request.get("column_confirmations")
            if not _confirmed_column_items(column_confirmations):
                raise
            try:
                raw_samples = _read_confirmed_rheology_sweep_samples(
                    source,
                    column_confirmations,
                    x_label="Temperature",
                    default_x_unit="°C",
                    metrics=_RHEOLOGY_SWEEP_METRICS,
                )
            except ValueError as confirmed_error:
                raise ValueError(
                    "Rheology temperature preparation failed both automatic "
                    f"and confirmed parsing (automatic: {automatic_error}; "
                    f"confirmed: {confirmed_error})."
                ) from confirmed_error
    except (OSError, ValueError) as exc:
        raise RheologySweepDomainError(
            "temperature_source_unavailable",
            f"SciPlot could not read the rheology-temperature source: {exc}",
        ) from exc
    source_sha256_after = source_hasher(source)
    if source_sha256_after != source_sha256_before:
        _fail(
            "temperature_source_changed_during_resolution",
            "The rheology-temperature source changed while its FigurePlan was "
            "being resolved.",
        )

    domain = _build_domain(
        rule_id=TEMPERATURE_RULE_ID,
        source=source,
        source_sha256=source_sha256_after,
        raw_samples=raw_samples,
        request=request,
        empty_reason_code="temperature_source_unavailable",
        empty_message="The rheology-temperature source has no selected samples.",
        ambiguous_reason_code="temperature_sample_identity_ambiguous",
        ambiguous_message=(
            "The prepared rheology-temperature samples do not have unique labels."
        ),
        lost_identity_message=(
            "A prepared rheology-temperature sample lost its raw replicate identity."
        ),
    )
    _require_temperature_metrics(domain.prepared_samples)
    return domain


def _build_domain(
    *,
    rule_id: str,
    source: Path,
    source_sha256: str,
    raw_samples: list[RheologySweepSample],
    request: dict[str, Any],
    empty_reason_code: str,
    empty_message: str,
    ambiguous_reason_code: str,
    ambiguous_message: str,
    lost_identity_message: str,
) -> ResolvedRheologySweepDomain:
    prepared_samples = _coalesce_replicate_sweep_samples(
        raw_samples,
        replicate_mode=request.get("replicate_mode"),
    )
    prepared_samples = _ordered_sweep_samples(
        prepared_samples,
        series_order=request.get("series_order"),
    )
    if not prepared_samples:
        _fail(empty_reason_code, empty_message)
    sample_order = tuple(sample.sample for sample in prepared_samples)
    if len(set(sample_order)) != len(sample_order):
        _fail(ambiguous_reason_code, ambiguous_message)

    raw_counts = Counter(_replicate_key(sample) for sample in raw_samples)
    replicate_counts = tuple(
        (sample.sample, raw_counts[_replicate_key(sample)])
        for sample in prepared_samples
    )
    if any(count < 1 for _sample, count in replicate_counts):
        _fail(ambiguous_reason_code, lost_identity_message)
    facts = RheologySweepSourceFacts(
        source_sha256=source_sha256,
        sample_order=sample_order,
        replicate_counts=replicate_counts,
        available_metrics=available_rheology_sweep_metrics(prepared_samples),
    )
    return ResolvedRheologySweepDomain(
        rule_id=rule_id,
        source=source,
        source_sha256=source_sha256,
        selected_sources=tuple(
            dict.fromkeys(sample.source.expanduser().resolve() for sample in raw_samples)
        ),
        raw_samples=tuple(raw_samples),
        prepared_samples=tuple(prepared_samples),
        facts=facts,
    )


def available_rheology_sweep_metrics(
    samples: Sequence[RheologySweepSample],
) -> tuple[str, ...]:
    """Return metrics with at least one paired point in every selected sample."""

    if not samples:
        return ()
    return tuple(
        metric
        for metric in _METRIC_ORDER
        if all(
            any("x" in row and metric in row for row in sample.rows)
            for sample in samples
        )
    )


def _require_temperature_metrics(
    samples: tuple[RheologySweepSample, ...],
) -> None:
    missing: list[str] = []
    for sample in samples:
        absent = [
            metric
            for metric in TEMPERATURE_SAMPLE_METRICS
            if not any("x" in row and metric in row for row in sample.rows)
        ]
        if absent:
            missing.append(f"{sample.sample}: {', '.join(absent)}")
    if missing:
        _fail(
            "temperature_metric_source_unavailable",
            "The selected temperature samples do not all contain storage modulus "
            f"and loss factor ({'; '.join(missing)}).",
        )


def _replicate_key(sample: RheologySweepSample) -> str:
    return clean_text(sample.sample) or sample.source.stem


def _fail(reason_code: str, message: str) -> NoReturn:
    raise RheologySweepDomainError(reason_code, message)


__all__ = [
    "FREQUENCY_RULE_ID",
    "ResolvedRheologySweepDomain",
    "RheologySweepDomainError",
    "RheologySweepSourceFacts",
    "TEMPERATURE_RULE_ID",
    "TEMPERATURE_SAMPLE_METRICS",
    "available_rheology_sweep_metrics",
    "resolve_rheology_frequency_domain",
    "resolve_rheology_temperature_domain",
]
