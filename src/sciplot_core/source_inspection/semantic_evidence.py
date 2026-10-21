"""Read byte-bound table candidates without choosing a scientific view or transform.

Candidates are observations, not a second persisted scientific plan. Existing
source bindings confirm them and retain original headers, units and row indices.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.data_mapping.original_tables import read_original_table, source_table_snapshot, table_position
from sciplot_core.data_mapping.raw_tables import _original_text
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.semantic_sources.paired_curve_table_metadata import explicit_header_unit, header_quantity_text, looks_like_unit
from sciplot_core.source_inspection.header_matching import cell_text
from sciplot_core.source_inspection.input_errors import SourceInputError, require_source_file
from sciplot_core.source_tables.read_session import with_table_reads


_QUANTITIES = {
    'time': {'time', 't', '时间'},
    'temperature': {'temperature', 'temp', 'ts', 'tr', '温度'},
    'charge': {'charge', 'electric charge', 'electrical charge', '电荷'},
    'mass': {'mass', 'weight', '质量', '重量'},
    'wavelength': {'wavelength', '波长'},
    'wavenumber': {'wavenumber', 'wave number', '波数'},
    'absorbance': {'absorbance', '吸光度'},
    'transmittance': {'transmittance', '透过率'},
    'heat_flow': {'heat flow', 'heatflow', '热流'},
    'angular_frequency': {'angular frequency', 'angularfrequency', 'frequency', 'omega', 'ω'},
    'storage_modulus': {'storage modulus', 'storagemodulus', "g'", 'g′'},
    'loss_modulus': {'loss modulus', 'lossmodulus', 'g"', 'g″'},
    'loss_factor': {'loss factor', 'lossfactor', 'tan delta', 'tan δ'},
    'complex_viscosity': {'complex viscosity', 'complexviscosity', '|η*|', '|eta*|'},
    'imaginary_complex_viscosity': {'im(complex viscosity)', 'imaginary complex viscosity'},
    'real_complex_viscosity': {'re(complex viscosity)', 'real complex viscosity'},
}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _quantity(header: str) -> str | None:
    # A component's parentheses are part of its quantity, not a unit suffix.
    from sciplot_core.semantic_sources.rheology_frequency_metrics import is_rheology_component_header, is_rheology_magnitude_header

    token = header_quantity_text(header).replace('_', ' ').strip().casefold()
    if is_rheology_component_header(header):
        return next((name for name, aliases in _QUANTITIES.items() if token in aliases), 'rheology_component')
    if is_rheology_magnitude_header(header, metric='complex_viscosity'):
        return 'complex_viscosity'
    return next((name for name, aliases in _QUANTITIES.items() if token in aliases), None)


def _unit(value: Any) -> str:
    text = cell_text(value)
    unwrapped = text.strip('[]')
    return text if text and _finite(text) is None and looks_like_unit(unwrapped) else ''


def _sample_row(frame: pd.DataFrame, row: int, headers: list[str]) -> bool:
    values = [cell_text(frame.iat[row, index]) for index, header in enumerate(headers) if header]
    # Repeated literal sample cells distinguish this metadata row from a note.
    return bool(values) and all(value and _finite(value) is None for value in values) and len(set(values)) < len(values)


def _header_candidate(frame: pd.DataFrame) -> tuple[int, int | None, int | None] | None:
    for row in range(min(32, len(frame))):
        headers = [cell_text(value) for value in frame.iloc[row]]
        if sum(bool(header) and _finite(header) is None for header in headers) < 2:
            continue
        inline = sum(bool(explicit_header_unit(header)) for header in headers)
        for offset in (1, 2):
            if row + offset >= len(frame):
                break
            middle = row + 1 if offset == 2 and any(cell_text(value) for value in frame.iloc[row + 1]) else None
            if middle is not None and not _sample_row(frame, middle, headers):
                continue
            adjacent = (sum(bool(_unit(value)) for value in frame.iloc[row + offset]) if row + offset < len(frame) else 0)
            if adjacent >= 2:
                return row, row + offset, middle
        if inline >= 2:
            return row, None, None
        # A named table can expose missing units for an explicit declaration;
        # unit absence is a scientific question, not a file-reading failure.
        if row + 1 < len(frame) and sum(_finite(value) is not None for value in frame.iloc[row + 1]) >= 2:
            return row, None, None
    return None


def _column(frame: pd.DataFrame, index: int, header: int, unit_row: int | None, start: int) -> dict[str, Any]:
    label = cell_text(frame.iat[header, index])
    unit = cell_text(frame.iat[unit_row, index]) if unit_row is not None else explicit_header_unit(label)
    quantity = _quantity(label)
    indices = [row for row in range(start, len(frame)) if _finite(frame.iat[row, index]) is not None]
    return {'column_id': f'column:{index}', 'column_index': index, 'header': label, 'unit': unit,
            'quantity': quantity, 'quantity_candidates': [quantity] if quantity else [],
            'evidence': [{'row_index': row, 'column_index': index, 'text': _original_text(frame.iat[row, index])}
                         for row in [header, *([unit_row] if unit_row is not None else [])]],
            'numeric': {'point_count': len(indices), 'first_row': min(indices) if indices else None,
                        'data_end_row': max(indices) + 1 if indices else None}}


def _segments(frame: pd.DataFrame, time: int, start: int, end: int) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    first: int | None = None
    previous: float | None = None
    for row in range(start, end + 1):
        value = _finite(frame.iat[row, time]) if row < end else None
        if first is not None and (value is None or (previous is not None and value < previous)):
            segments.append({'data_start_row': first, 'data_end_row': row, 'point_count': row - first,
                             'time_start': _finite(frame.iat[first, time]), 'time_end': previous})
            first = None
        if value is not None and first is None:
            first = row
        previous = value
    return segments


def acquisition_time_regions(frame: pd.DataFrame, time: int, start: int, end: int) -> tuple[list[dict[str, Any]], list[dict[str, int]]]:
    """Partition the complete body only at adjacent measured time resets.

    Missing coordinates break a finite display run, not the measurement domain.
    A decrease across a gap only bounds an unresolved reset; it cannot locate
    which missing observation belongs to an acquisition stage.
    """
    boundaries = [start]
    unresolved = []
    previous: tuple[int, float] | None = None
    for row in range(start, end):
        value = _finite(frame.iat[row, time])
        if value is None:
            continue
        if previous is not None and value < previous[1]:
            if previous[0] == row - 1:
                boundaries.append(row)
            else:
                unresolved.append({'previous_time_row': previous[0], 'next_time_row': row})
        previous = row, value
    regions = [{'data_start_row': first, 'data_end_row': last, 'point_count': last - first,
                'time_start': _finite(frame.iat[first, time]), 'time_end': _finite(frame.iat[last - 1, time])}
               for first, last in zip(boundaries, [*boundaries[1:], end], strict=True)]
    return regions, unresolved


def _blocks(frame: pd.DataFrame, columns: list[dict[str, Any]], start: int, end: int,
            sample_row: int | None = None) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    for column in columns:
        if not column['header']:
            continue
        previous = groups[-1][-1]['column_index'] if groups else -2
        changed_sample = (sample_row is not None and groups
                          and cell_text(frame.iat[sample_row, column['column_index']]) != cell_text(frame.iat[sample_row, previous]))
        if not groups or column['column_index'] != previous + 1 or changed_sample:
            groups.append([])
        groups[-1].append(column)
    blocks = []
    for position, group in enumerate(groups):
        times = [column for column in group if column['quantity'] == 'time']
        temperatures = [column['column_id'] for column in group if column['quantity'] == 'temperature']
        responses = [column['column_id'] for column in group if column['quantity'] not in {'time', 'temperature'}
                     and column['unit']]
        time = times[0] if len(times) == 1 else None
        block = {'block_id': f'block:{position}', 'order': position,
                       'column_indices': [column['column_index'] for column in group],
                       'data_start_row': start, 'data_end_row': end, 'point_count': end - start,
                       'time_column': time['column_id'] if time else None,
                       'time_columns': [column['column_id'] for column in times],
                       'temperature_columns': temperatures, 'response_columns': responses,
                       'segments': _segments(frame, time['column_index'], start, end) if time else []}
        if sample_row is not None:
            block['sample'] = cell_text(frame.iat[sample_row, group[0]['column_index']])
            block['label'] = block['sample']
        blocks.append(block)
    return blocks


def _candidate(frame: pd.DataFrame, sheet: str | None, position: int, *, source: Path) -> dict[str, Any] | None:
    header = _header_candidate(frame)
    if header is None:
        return None
    header_row, unit_row, sample_row = header
    start = max(value for value in (header_row, unit_row, sample_row) if value is not None) + 1
    # One explicit sample metadata row is retained when it precedes numeric data.
    if sample_row is None and start < len(frame) and _sample_row(frame, start, [cell_text(value) for value in frame.iloc[header_row]]):
        sample_row = start
        start += 1
    if start >= len(frame):
        return None
    members = [index for index, value in enumerate(frame.iloc[header_row]) if cell_text(value)]
    records = [row for row in range(start, len(frame))
               if any(_original_text(frame.iat[row, column]).strip() for column in members)]
    if not records:
        return None
    start, end = records[0], records[-1] + 1
    gaps = set(range(start, end)) - set(records)
    if gaps:
        raise SourceInputError("semantic_table_region_ambiguous",
            "The original named table has disconnected record regions; empty rows cannot authorize a join or deletion.",
            repair={"action": "inspect_original_table", "source": str(source), "sheet": sheet,
                    "row_index": min(gaps), "message": "Preserve the original cells and confirm an exact original region before creation."})
    columns = [_column(frame.iloc[:end], index, header_row, unit_row, start) for index in range(frame.shape[1])]
    blocks = _blocks(frame, columns, start, end, sample_row)
    if not blocks:
        return None
    selection = {'sheet': sheet, 'header_rows': [header_row], 'data_start_row': start, 'data_end_row': end}
    if unit_row is not None:
        selection['unit_row'] = unit_row
    if sample_row is not None:
        selection['sample_row'] = sample_row
    for block in blocks:
        block['columns'] = [column for column in columns if column['column_index'] in block['column_indices']]
        block['table_selection'] = dict(selection)
        block['source_interval'] = None
    ambiguities = []
    for block in blocks:
        if len(block['temperature_columns']) > 1:
            ambiguities.append({'code': 'temperature_role', 'block_id': block['block_id'],
                                'column_ids': block['temperature_columns'],
                                'message': 'Select the measured/program/reference temperature role from original headers; do not infer it by position.'})
        if len(block['time_columns']) > 1:
            ambiguities.append({'code': 'time_role', 'block_id': block['block_id'], 'column_ids': block['time_columns']})
        for identifier in block['response_columns']:
            column = next(item for item in columns if item['column_id'] == identifier)
            if column['quantity'] is None:
                ambiguities.append({'code': 'quantity_unconfirmed', 'block_id': block['block_id'],
                                    'column_ids': [identifier], 'header': column['header'], 'unit': column['unit'],
                                    'message': 'A unit alone does not identify a measured quantity; bind it to explicit scientific intent or source evidence.'})
    return {'candidate_id': f'table:{position}', 'sheet': sheet, 'table_selection': selection,
            'columns': columns, 'blocks': blocks, 'ambiguities': ambiguities,
            **({'format': 'sample_column_blocks'} if sample_row is not None else {})}


@with_table_reads
def inspect_semantic_tables(path: str | Path, *, rule_id: str | None = None,
                            sheets: list[str | None] | None = None) -> dict[str, Any]:
    """Expose original columns and stage candidates for the existing task owner.

    ``rule_id`` records caller context only; it never changes observed metadata,
    chooses an X axis, or confirms a percentage column as mass.
    """
    source = Path(path).expanduser().resolve()
    require_source_file(source)
    digest = file_sha256(source)
    snapshot = source_table_snapshot(source, rule_id=rule_id, sheets=sheets)
    if snapshot is None:
        return {'kind': 'sciplot_semantic_table_evidence', 'version': 1, 'source': str(source),
                'sha256': digest, 'candidates': [], 'scientific_identity': {'confirmed': False, 'rule_candidates': []}}
    candidates = []
    for index, table in enumerate(snapshot['tables']):
        position = table_position(table, index)
        if not table['row_count']:
            continue
        frame = read_original_table(source, table['sheet'], digest)
        from sciplot_core.source_inspection.rheology_evidence import instrument_candidate

        candidate = instrument_candidate(frame, sheet=table['sheet'], position=position, source=source,
            column_reader=_column)
        if candidate is None:
            candidate = _candidate(frame, table['sheet'], position, source=source)
        if candidate is not None:
            candidates.append(candidate)
    if file_sha256(source) != digest:
        raise ValueError('Source bytes changed while gathering semantic evidence.')
    # Only explicit mass and temperature identities suggest a thermal mass view.
    # The caller still chooses experiment identity and view independently.
    rules = ['tga_curve'] if any({'mass', 'temperature'} <= {column['quantity'] for column in item['columns']}
                                for item in candidates) else []
    return {'kind': 'sciplot_semantic_table_evidence', 'version': 1, 'source': str(source), 'sha256': digest,
            'candidates': candidates, 'scientific_identity': {'confirmed': False, 'rule_candidates': rules,
                'requested_rule_id': rule_id, 'basis': 'literal original quantity headers; units do not prove identity'}}
