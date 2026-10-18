"""Read byte-bound table candidates without choosing a scientific view or transform.

Candidates are observations, not a second persisted scientific plan. Existing
source bindings confirm them and retain original headers, units and row indices.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Any

import pandas as pd

from sciplot_core.data_mapping.table_choice import read_original_table, source_table_snapshot
from sciplot_core.data_mapping.column_choice import _original_text
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.semantic_sources.paired_curve_table_metadata import explicit_header_unit, looks_like_unit
from sciplot_core.source_inspection.header_matching import cell_text
from sciplot_core.source_inspection.input_errors import require_source_file
from sciplot_core.source_tables.read_session import with_table_reads


_UNIT_SUFFIX = re.compile(r'\s*(?:\([^()]*\)|\[[^\[\]]*\])\s*$')
_QUANTITIES = {
    'time': {'time', 't', '时间'},
    'temperature': {'temperature', 'temp', 'ts', 'tr', '温度'},
    'mass': {'mass', 'weight', '质量', '重量'},
    'wavelength': {'wavelength', '波长'},
    'absorbance': {'absorbance', '吸光度'},
    'transmittance': {'transmittance', '透过率'},
}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _quantity(header: str) -> str | None:
    token = _UNIT_SUFFIX.sub('', header).strip().casefold()
    return next((name for name, aliases in _QUANTITIES.items() if token in aliases), None)


def _unit(value: Any) -> str:
    text = cell_text(value)
    unwrapped = text.strip('[]')
    return text if text and _finite(text) is None and looks_like_unit(unwrapped) else ''


def _header_candidate(frame: pd.DataFrame) -> tuple[int, int | None] | None:
    for row in range(min(32, len(frame))):
        headers = [cell_text(value) for value in frame.iloc[row]]
        if sum(bool(header) and _finite(header) is None for header in headers) < 2:
            continue
        inline = sum(bool(explicit_header_unit(header)) for header in headers)
        adjacent = (sum(bool(_unit(value)) for value in frame.iloc[row + 1]) if row + 1 < len(frame) else 0)
        if adjacent >= 2:
            return row, row + 1
        if inline >= 2:
            return row, None
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


def _blocks(frame: pd.DataFrame, columns: list[dict[str, Any]], start: int) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    for column in columns:
        if not column['header'] or not column['numeric']['point_count']:
            continue
        if not groups or column['column_index'] != groups[-1][-1]['column_index'] + 1:
            groups.append([])
        groups[-1].append(column)
    blocks = []
    for position, group in enumerate(groups):
        times = [column for column in group if column['quantity'] == 'time']
        temperatures = [column['column_id'] for column in group if column['quantity'] == 'temperature']
        responses = [column['column_id'] for column in group if column['quantity'] not in {'time', 'temperature'}
                     and column['unit']]
        end = max(column['numeric']['data_end_row'] for column in group)
        time = times[0] if len(times) == 1 else None
        blocks.append({'block_id': f'block:{position}', 'order': position,
                       'column_indices': [column['column_index'] for column in group],
                       'data_start_row': start, 'data_end_row': end,
                       'time_column': time['column_id'] if time else None,
                       'time_columns': [column['column_id'] for column in times],
                       'temperature_columns': temperatures, 'response_columns': responses,
                       'segments': _segments(frame, time['column_index'], start, end) if time else []})
    return blocks


def _candidate(frame: pd.DataFrame, sheet: str | None, position: int) -> dict[str, Any] | None:
    header = _header_candidate(frame)
    if header is None:
        return None
    header_row, unit_row = header
    start = (unit_row if unit_row is not None else header_row) + 1
    # One explicit sample metadata row is retained when it precedes numeric data.
    sample_row = None
    if start < len(frame) and not any(_finite(value) is not None for value in frame.iloc[start]):
        sample_row = start
        start += 1
    if start >= len(frame):
        return None
    columns = [_column(frame, index, header_row, unit_row, start) for index in range(frame.shape[1])]
    blocks = _blocks(frame, columns, start)
    if not blocks:
        return None
    end = max(block['data_end_row'] for block in blocks)
    selection = {'sheet': sheet, 'header_rows': [header_row], 'data_start_row': start, 'data_end_row': end}
    if unit_row is not None:
        selection['unit_row'] = unit_row
    if sample_row is not None:
        selection['sample_row'] = sample_row
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
            'columns': columns, 'blocks': blocks, 'ambiguities': ambiguities}


@with_table_reads
def inspect_semantic_tables(path: str | Path, *, rule_id: str | None = None) -> dict[str, Any]:
    """Expose original columns and stage candidates for the existing task owner.

    ``rule_id`` records caller context only; it never changes observed metadata,
    chooses an X axis, or confirms a percentage column as mass.
    """
    source = Path(path).expanduser().resolve()
    require_source_file(source)
    digest = file_sha256(source)
    snapshot = source_table_snapshot(source, rule_id=rule_id)
    if snapshot is None:
        return {'kind': 'sciplot_semantic_table_evidence', 'version': 1, 'source': str(source),
                'sha256': digest, 'candidates': [], 'scientific_identity': {'confirmed': False, 'rule_candidates': []}}
    candidates = []
    for position, table in enumerate(snapshot['tables']):
        if not table['row_count']:
            continue
        frame = read_original_table(source, table['sheet'], digest)
        candidate = _candidate(frame, table['sheet'], position)
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
