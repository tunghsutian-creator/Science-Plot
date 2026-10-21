"""Shared original rheology header, metric identity, and unit evidence readers."""
from __future__ import annotations

import pandas as pd

from sciplot_core.foundation.text_values import clean_text as _clean_text, token as _token
from sciplot_core.materials_rules.unit_formatting import format_unit_label
from sciplot_core.semantic_sources.models import _RHEOLOGY_SWEEP_METRICS
from sciplot_core.semantic_sources.rheology_frequency_metrics import is_rheology_magnitude_header
from sciplot_core.semantic_sources.paired_curve_table_metadata import explicit_header_unit
from sciplot_core.semantic_sources.table_scanning import _find_column, _axis_match, _unit_for, _unit_row_score


def _find_rheology_sweep_headers(
    raw: pd.DataFrame,
    *,
    x_aliases: tuple[str, ...],
    metrics: tuple[
        tuple[str, str, tuple[str, ...], str], ...
    ] = _RHEOLOGY_SWEEP_METRICS,
) -> list[int]:
    def is_sweep_header(row_index: int) -> bool:
        headers = [_clean_text(value) for value in raw.iloc[row_index].tolist()]
        try:
            _find_column(headers, x_aliases)
            return any(
                any(
                    is_rheology_magnitude_header(header, metric=key)
                    if key in {'complex_viscosity', 'complex_modulus'}
                    else _axis_match(header, aliases)
                    for header in headers
                )
                for key, _label, aliases, _unit in metrics
            )
        except ValueError:
            return False

    # Instrument exports can include project metadata such as an operator name
    # containing the single-letter symbolic alias ``G``.  That metadata may
    # also contain "frequency sweep", so a loose token scan can mistake it for
    # the table header.  The explicitly labelled interval header is the
    # authority whenever it exists; the generic scan remains available for
    # plain public tables without an interval wrapper.
    interval_matches = [
        row_index
        for row_index in range(raw.shape[0])
        if _token(raw.iat[row_index, 0] if raw.shape[1] else None) == "intervaldata"
        and is_sweep_header(row_index)
    ]
    if interval_matches:
        return interval_matches

    matches: list[int] = []
    for row_index in range(raw.shape[0]):
        if is_sweep_header(row_index):
            matches.append(row_index)
    if matches:
        return matches
    raise ValueError("Could not find rheology sweep X and requested response columns.")

def _sweep_metric_column(headers: list[str], key: str, aliases: tuple[str, ...]) -> int:
    if key not in {'complex_viscosity', 'complex_modulus'}:
        try:
            return _find_column(headers, aliases)
        except ValueError as exc:
            raise LookupError(f'No {key} column.') from exc
    matches = [
        index for index, header in enumerate(headers)
        if is_rheology_magnitude_header(header, metric=key)
    ]
    if len(matches) > 1:
        raise ValueError(f'Ambiguous explicit {key} magnitude columns.')
    if not matches:
        raise LookupError(f'No explicit {key} magnitude column.')
    return matches[0]

def _sweep_source_unit(
    headers: list[str], units: list[str], index: int, default: str, *, explicit: bool,
) -> tuple[str, str]:
    adjacent = _clean_text(units[index]).strip('[]() ') if index < len(units) else ''
    header = explicit_header_unit(headers[index])
    if adjacent and header and format_unit_label(adjacent) != format_unit_label(header):
        raise ValueError(f'Conflicting explicit unit evidence for `{headers[index]}`.')
    if adjacent:
        return format_unit_label(adjacent), 'adjacent_unit_row'
    if header:
        return format_unit_label(header), 'header'
    if explicit:
        raise ValueError(f'Missing explicit source unit for `{headers[index]}`.')
    return _unit_for(units, index, default), 'default_due_to_missing_unit_row'

def _rheology_sweep_units(
    raw: pd.DataFrame,
    *,
    header_index: int,
    columns: tuple[int, ...],
) -> list[str]:
    candidates = [
        row_index
        for row_index in (header_index + 1, header_index + 2)
        if row_index < raw.shape[0]
    ]
    if not candidates:
        return []
    best_index = max(
        candidates, key=lambda row_index: _unit_row_score(raw, row_index, columns)
    )
    if _unit_row_score(raw, best_index, columns) <= 0:
        return []
    return [_clean_text(value) for value in raw.iloc[best_index].tolist()]
