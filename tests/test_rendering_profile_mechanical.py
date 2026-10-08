"""Historical mechanical science identity and immutable fixture drift guards."""

import csv
import json
from pathlib import Path
import shutil

import pytest

from rendering_profile_mechanical import mechanical_request


FIXTURE = Path(__file__).parent / 'fixtures/rendering_profiles/mechanical-v1'


def test_prepared_summary_preserves_historical_values_and_all_replicates():
    request = mechanical_request(FIXTURE)
    spec = json.loads((FIXTURE / 'legacy/spec.json').read_text())
    settings = json.loads((FIXTURE / 'provenance/native-explicit-settings.json').read_text())
    provenance = request['data_binding']['provenance']['historical_transform']
    assert provenance['reexecuted'] is False
    assert len(provenance['original_workbooks']) == 4
    for index, group in enumerate(spec['categorical']['groups'], 1):
        source = request['data_binding']['data_sources'][index - 1]
        with Path(source['path']).open(newline='', encoding='utf-8') as stream:
            rows = list(csv.reader(stream))
        points = rows[3:8]
        native = settings[f'page1/graph1/categorical_bar_error_{index}_1']
        assert [float(value) for value in points[0][:4]] == [
            group['position'], group['bar_mean'], native['yPos'][0], native['yPos2'][0]]
        assert [float(row[4]) for row in points] == group['raw_values']
        assert len(points) == group['replicate_count'] == 5
        assert all(row[:4] == ['', '', '', ''] for row in points[1:])
    assert request['rule_id'] == 'tensile_curve'


@pytest.mark.parametrize('relative', ['raw/E0 2mm.xlsx', 'sources/E0-summary.csv', 'accepted.vsz'])
def test_changed_raw_summary_or_native_golden_is_rejected(tmp_path, relative):
    fixture = tmp_path / 'profile'
    shutil.copytree(FIXTURE, fixture)
    path = fixture / relative
    path.write_bytes(path.read_bytes() + b'\nchanged')
    with pytest.raises(AssertionError, match='Immutable mechanical fixture changed'):
        mechanical_request(fixture)
