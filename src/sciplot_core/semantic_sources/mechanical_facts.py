"""Read immutable source facts shared by mechanical planning and preparation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.semantic_sources.mechanical_fact_derivation import (
    derive_mechanical_source_projection,
)
from sciplot_core.semantic_sources.mechanical_fact_models import (
    MECHANICAL_METRIC_UNITS,
    MECHANICAL_RULE_IDS,
    MechanicalSourceFacts,
    MechanicalSourceFactsError,
    MechanicalSummaryObservation,
    fail_mechanical_source_facts as _fail,
)
from sciplot_core.semantic_sources.mechanical_grouping import (
    normalize_explicit_mechanical_replicates,
)
from sciplot_core.semantic_sources.mechanical_sources import (
    _read_non_tensile_mechanical_series,
    _read_non_tensile_mechanical_workbook_directory,
)
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.series_ordering import (
    _order_curve_series,
    _order_recycled_pa_pair_control_first,
    _series_order_map,
)
from sciplot_core.semantic_sources.tensile_exports import (
    _read_tensile_export_series_list,
    _tensile_export_files,
)
from sciplot_core.semantic_sources.tensile_workbooks import (
    _read_tensile_workbook_directory,
    _read_tensile_workbook_series,
)


def load_mechanical_source_facts(
    input_path: Path,
    *,
    rule_id: str,
    series_order: object = None,
) -> MechanicalSourceFacts:
    """Parse once between source-tree hashes and return closed source facts."""

    if rule_id not in MECHANICAL_RULE_IDS:
        _fail("mechanical_rule_unsupported", f"Unsupported mechanical rule: {rule_id}")
    source = input_path.expanduser().resolve()
    before = source_tree_sha256(source)
    if before is None:
        _fail("mechanical_source_unavailable", f"Mechanical source is absent: {source}")
    try:
        raw_series, supplied_rows, selected, source_kind = _read_source(
            source, rule_id=rule_id
        )
        curated = source_kind == "curated_representative_workbooks"
        series = list(raw_series)
        if not curated:
            series = normalize_explicit_mechanical_replicates(series)
        series = _order_mechanical_series(series, series_order=series_order)
        observations, sample_order, replicate_counts, representatives = (
            derive_mechanical_source_projection(
                series,
                supplied_rows=supplied_rows,
                rule_id=rule_id,
                curated=curated,
            )
        )
    except MechanicalSourceFactsError:
        raise
    except (OSError, ValueError, KeyError, IndexError) as exc:
        raise MechanicalSourceFactsError(
            "mechanical_source_contract_invalid",
            f"The {rule_id} source could not be resolved: {exc}",
        ) from exc
    after = source_tree_sha256(source)
    if after != before:
        _fail(
            "mechanical_source_changed_during_resolution",
            "The mechanical source changed while its facts were being resolved.",
        )
    selected_sources = tuple(dict.fromkeys(path.resolve() for path in selected))
    if not selected_sources:
        _fail(
            "mechanical_selected_sources_missing",
            "No consumed source files were recorded.",
        )
    first = series[0]
    return MechanicalSourceFacts(
        rule_id=rule_id,
        source_root=source,
        source_sha256=before,
        selected_sources=selected_sources,
        raw_series=tuple(series),
        individual_curve_series=tuple(series) if not curated else (),
        representative_curve_series=representatives,
        summary_rows=observations,
        sample_order=sample_order,
        replicate_counts=replicate_counts,
        x_label=first.x_label,
        x_unit=first.x_unit,
        y_label=first.y_label,
        y_unit=first.y_unit,
        metric_units=MECHANICAL_METRIC_UNITS[rule_id],
        curve_source_kind=source_kind,
        individual_curves_complete=not curated,
    )


def _read_source(
    source: Path, *, rule_id: str
) -> tuple[
    list[CurveSeriesPayload], list[dict[str, Any]] | None, tuple[Path, ...], str
]:
    if rule_id != "tensile_curve":
        curated = (
            _read_non_tensile_mechanical_workbook_directory(source, family=rule_id)
            if source.is_dir()
            else None
        )
        if curated is not None:
            curves, rows = curated
            return (
                curves,
                rows,
                _workbook_paths(source),
                "curated_representative_workbooks",
            )
        curves = _read_non_tensile_mechanical_series(source, family=rule_id)
        return curves, None, _selected_paths(curves, source), "raw_specimen_curves"

    csv_sources = (
        _tensile_export_files(source) if source.suffix.lower() != ".xlsx" else []
    )
    workbooks = _workbook_paths(source)
    if source.is_dir() and not csv_sources and workbooks:
        curves, rows = _read_tensile_workbook_directory(source)
        return curves, rows, workbooks, "curated_representative_workbooks"
    if source.is_file() and source.suffix.lower() in {".xlsx", ".xls"}:
        curves = _read_tensile_workbook_series(source)
        curves = [_with_source_file(item, source) for item in curves]
        return curves, None, (source,), "raw_specimen_curves"
    curves = _read_tensile_export_series_list(source)
    return curves, None, _selected_paths(curves, source), "raw_specimen_curves"


def _order_mechanical_series(
    series: list[CurveSeriesPayload], *, series_order: object
) -> list[CurveSeriesPayload]:
    if _series_order_map(series_order):
        return _order_curve_series(series, series_order)
    return _order_recycled_pa_pair_control_first(
        series, sample_of=lambda item: item.sample
    )


def _selected_paths(series: list[CurveSeriesPayload], source: Path) -> tuple[Path, ...]:
    paths = tuple(
        Path(str((item.diagnostics or {}).get("source_file"))).expanduser().resolve()
        for item in series
        if (item.diagnostics or {}).get("source_file")
    )
    return tuple(dict.fromkeys(paths)) or ((source,) if source.is_file() else ())


def _workbook_paths(source: Path) -> tuple[Path, ...]:
    if source.is_file():
        return (source,) if source.suffix.casefold() in {".xlsx", ".xls"} else ()
    return tuple(
        path.resolve()
        for path in sorted(source.rglob("*"))
        if path.is_file() and path.suffix.casefold() in {".xlsx", ".xls"}
    )


def _with_source_file(series: CurveSeriesPayload, source: Path) -> CurveSeriesPayload:
    return CurveSeriesPayload(
        series.sample,
        series.x_label,
        series.x_unit,
        series.y_label,
        series.y_unit,
        series.points,
        {**(series.diagnostics or {}), "source_file": str(source.resolve())},
    )


__all__ = [
    "MECHANICAL_RULE_IDS",
    "MechanicalSourceFacts",
    "MechanicalSourceFactsError",
    "MechanicalSummaryObservation",
    "load_mechanical_source_facts",
]
