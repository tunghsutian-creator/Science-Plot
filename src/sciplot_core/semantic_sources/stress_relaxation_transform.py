"""Resolve stress-relaxation series and bind their scientific contract."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)
from sciplot_core.semantic_sources.series_ordering import (
    _order_curve_series,
    _order_curve_series_by_shared_right_height,
    _series_order_map,
)
from sciplot_core.semantic_sources.stress_relaxation_contract import (
    _diagnostic_source_strings,
    _stress_relaxation_contract,
)
from sciplot_core.semantic_sources.stress_relaxation_sources import (
    _read_stress_relaxation_series_list,
)


def resolve_stress_relaxation_transform(
    source: Path,
    *,
    series_order: object = None,
) -> ResolvedScientificTransform:
    """Read and transform once, then expose the same series to preview and prepare."""

    series_list = _read_stress_relaxation_series_list(source)
    explicit_order = bool(_series_order_map(series_order))
    if explicit_order:
        series_list = _order_curve_series(series_list, series_order)
    elif source.is_dir():
        series_list = _order_curve_series_by_shared_right_height(series_list)
    selected_sources = _selected_sources(source, series_list)
    contract = _stress_relaxation_contract(
        series_list,
        selected_sources=selected_sources,
        automatic_visual_ordering=not explicit_order and source.is_dir(),
    )
    return ResolvedScientificTransform(
        series=tuple(series_list),
        contract=contract,
        selected_sources=selected_sources,
    )


def _selected_sources(
    source: Path,
    series_list: list[CurveSeriesPayload],
) -> tuple[Path, ...]:
    values: list[Path] = []
    for series in series_list:
        for value in _diagnostic_source_strings(dict(series.diagnostics or {})):
            path = Path(value).expanduser().resolve()
            if path not in values:
                values.append(path)
    if not values and source.is_file():
        values.append(source.expanduser().resolve())
    return tuple(values)


__all__ = ["resolve_stress_relaxation_transform"]
