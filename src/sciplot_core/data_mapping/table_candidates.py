"""Evidence-backed wide-table proposals for caller review, never implicit choices."""

from pathlib import Path
from typing import Any

from sciplot_core.data_mapping.table_choice import _proposal_contents, _read, select_table
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources.paired_curve_table_metadata import axis_match, explicit_header_unit


def _response_evidence(snapshot: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    rule = get_rule(snapshot['rule_id'])
    aliases = (rule.y_axis.canonical_label, *rule.y_axis.aliases)
    matches: dict[tuple[str, str], tuple[str, str, dict[str, Any]]] = {}
    for table in snapshot['tables'][:8]:
        # Notes only: never derive quantity/unit evidence from measurement values.
        if table['row_count'] > 32:
            continue
        for row in table['rows']:
            for index, cell in enumerate(row['cells']):
                text = str(cell)
                literals = [text[pos:pos+len(alias)] for alias in aliases
                            if (pos := text.casefold().find(alias.casefold())) >= 0]
                if not literals:
                    continue
                quantity = max(literals, key=len)
                unit = explicit_header_unit(text)
                if rule.scientific_source_adapter == 'ftir':
                    from sciplot_core.semantic_sources.ftir_sources import _response_mode

                    try:
                        mode = _response_mode(text)
                    except ValueError:
                        return []
                    if mode == 'transmittance' and '%' in text:
                        unit = '%'
                if not unit:
                    continue
                evidence = {'kind': 'source_cell', 'sheet': table['sheet'],
                            'row_index': row['row_index'], 'column_index': index, 'text': text}
                matches.setdefault((quantity.casefold(), unit), (quantity, unit, evidence))
    return list(matches.values())


def wide_table_candidates(snapshot: dict[str, Any], diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    """Suggest shared-X rows and sample headers only with explicit, unique metadata."""
    metadata = _response_evidence(snapshot)
    if len(metadata) != 1:
        return []
    quantity, unit, note = metadata[0]
    rule = get_rule(snapshot['rule_id'])
    aliases = tuple(label for axis in (rule.x_axis, rule.y_axis)
                    for label in (axis.canonical_label, *axis.aliases))
    candidates = []
    source = Path(snapshot['source'])
    for table, numeric in zip(snapshot['tables'][:8], diagnostics['tables'], strict=True):
        if not 2 <= table['column_count'] <= 33:
            continue
        frame = _read(source, table['sheet'], snapshot['file_sha256'])
        # A complete single header row followed by the entire numeric region.
        if len(frame) < 3:
            continue
        x_columns = [i for i, value in enumerate(frame.iloc[0])
                     if axis_match(value, (rule.x_axis.canonical_label, *rule.x_axis.aliases))]
        if len(x_columns) != 1:
            continue
        x = x_columns[0]
        x_extent = next((item for item in numeric['columns'] if item['index'] == x), None)
        if not x_extent or x_extent['first_numeric_row'] != 1 or x_extent['data_end_row'] != len(frame) or x_extent['invalid_inside']:
            continue
        selection = {'sheet': table['sheet'], 'header_rows': [0], 'data_start_row': 1, 'data_end_row': len(frame)}
        columns = select_table(snapshot, selection)['columns']
        if not columns[x]['x_eligible']:
            continue
        declarations: list[dict[str, Any]] = []
        pairs: list[dict[str, Any]] = []
        for column in columns:
            index, sample = column['index'], column['header']
            if index == x:
                continue
            if not sample or axis_match(sample, aliases) or not column['numeric']['valid']:
                break
            sample_cell = {'kind': 'source_cell', 'sheet': table['sheet'], 'row_index': 0,
                           'column_index': index, 'text': sample}
            declarations.extend({'source_sha256': snapshot['file_sha256'], 'sheet': table['sheet'],
                                 'column_index': index, 'field': field, 'value': value, 'evidence': evidence}
                                for field, value, evidence in [('sample', sample, sample_cell),
                                                              ('quantity', quantity, note), ('unit', unit, note)])
            pairs.append({'x_column': x, 'y_column': index})
        else:
            samples = [columns[pair['y_column']]['header'] for pair in pairs]
            if len(set(samples)) != len(samples):
                continue
            resolved = select_table(snapshot, selection, declarations)
            try:
                _proposal_contents(resolved, pairs)
            except ValueError:
                continue
            mapping = {'source_sha256': snapshot['file_sha256'], 'table_selection': selection,
                       'metadata_confirmations': declarations, 'column_mapping': {'pairs': pairs}}
            candidates.append({'candidate_id': canonical_json_sha256(mapping, allow_nan=False),
                'table_selection': selection, 'points_per_pair': len(frame)-1,
                'x': {'column': x, 'quantity': columns[x]['header'], 'unit': columns[x]['unit']},
                'y': {'quantity': quantity, 'unit': unit, 'evidence': note},
                'pairs': [{'pair_index': i, **pair, 'sample': sample} for i, (pair, sample) in enumerate(zip(pairs, samples, strict=True))],
                'review_required': 'Check that this note applies to these sample columns and that all selected rows/samples match the request.',
                'mapping': mapping})
    return candidates
