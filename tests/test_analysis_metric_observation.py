"""A metric operation observes one original table and keeps distinct science."""

import csv
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.materials_rules import compute_analysis_metrics, get_rule, semantic_payload_from_rule
from sciplot_core.materials_rules import metric_tables


def _source(path: Path, *, changed: bool = False) -> None:
    frame = pd.DataFrame([
        ['Temperature', 'Storage Modulus', 'Loss Factor'] * 2,
        ['C', 'Pa', '1'] * 2, ['B', 'B', 'B', 'A', 'A', 'A'],
        [30, 30, 42 if changed else .5, 20, 80, None],
        [10, 100, 2, 0, 100, .7], [20, 70, 2, 10, 90, 1],
        [20, 60, 9, 10, 85, 1], [40, 10, .1, 30, 20, .3],
        [None, 5, None, 40, 10, .7],
    ])
    if path.suffix == '.xlsx':
        frame.to_excel(path, header=False, index=False)
    else:
        frame.to_csv(path, header=False, index=False)


def _compute(source: Path, output: Path):
    return compute_analysis_metrics(source_path=source, processed_source=None,
        semantic=semantic_payload_from_rule(get_rule('rheology_temperature_sweep'), confidence=1),
        output_dir=output)


def _expected(*, changed: bool = False):
    reasons = (
        'Maximum finite loss factor in the canonical trace; this value is not interpreted as Tg.',
        'Temperature of the maximum finite loss factor; endpoint maxima are retained and this is not interpreted as Tg.',
        'Temperature at the most negative discrete storage-modulus gradient.',
    )
    values = (
        ('maximum_tan_delta', (42. if changed else 9., 1.), '1'),
        ('temperature_at_maximum_tan_delta_C', (30. if changed else 20., 10.), '°C'),
        ('softening_temperature_candidate', (10., 30.), '°C'),
    )
    return [{'metric': f'{name}[{sample}]', 'value': value, 'unit': unit, 'status': 'ok', 'reason': reason}
        for (name, pair, unit), reason in zip(values, reasons, strict=True)
        for sample, value in zip(('B', 'A'), pair, strict=True)]


@pytest.mark.parametrize('suffix', ['.csv', '.xlsx'], ids=['csv', 'xlsx'])
def test_temperature_analysis_observes_once_and_new_operation_observes_again(tmp_path, monkeypatch, suffix):
    source = tmp_path / ('original' + suffix)
    _source(source)
    observed = []
    read = metric_tables.read_raw_table

    def observe(path):
        observed.append(path)
        return read(path)

    monkeypatch.setattr(metric_tables, 'read_raw_table', observe)
    before = source.read_bytes()
    rows = _compute(source, tmp_path / 'first')
    assert observed == [source]
    assert rows == _expected()
    assert source.read_bytes() == before
    with (tmp_path / 'first/tables/analysis_metrics.csv').open(newline='') as stream:
        saved = list(csv.DictReader(stream))
    assert saved == [{key: str(value) for key, value in row.items()} for row in rows]
    _source(source, changed=True)
    changed = source.read_bytes()
    assert changed != before
    assert _compute(source, tmp_path / 'second') == _expected(changed=True)
    assert observed == [source, source]
    assert source.read_bytes() == changed


@pytest.mark.parametrize('fault', ['permission', 'unsupported-format'])
def test_metric_observation_preserves_the_original_read_refusal(tmp_path, monkeypatch, fault):
    source = tmp_path / ('original.csv' if fault == 'permission' else 'original.invalid')
    source.write_text('not a supported table')
    refusal = PermissionError('generated original table refusal')
    if fault == 'permission':
        def refuse(_path):
            raise refusal
        monkeypatch.setattr(metric_tables, 'read_raw_table', refuse)
    with pytest.raises((PermissionError, ValueError)) as caught:
        _compute(source, tmp_path / 'output')
    if fault == 'permission':
        assert caught.value is refusal
    else:
        assert type(caught.value) is ValueError
        assert str(caught.value) == 'Unsupported file format: .invalid'
    assert not (tmp_path / 'output').exists()
    assert source.read_text() == 'not a supported table'


def test_distinct_metric_calculators_do_not_mutate_the_shared_observation():
    from sciplot_core.materials_rules.curve_extrema_metrics import (
        _paired_extreme_position_metrics_from_series,
        _paired_steepest_drop_position_metrics_from_series,
    )
    from sciplot_core.materials_rules.curve_peak_metrics import _peak_y_metrics_from_series

    frame = pd.DataFrame({'x': [2., 0., 1., 1., float('nan')], 'y': [1., 3., 2., 2., 4.]})
    before = frame.copy(deep=True)
    series = [('Original', frame)]
    assert _peak_y_metrics_from_series(series, metric_name='peak', y_unit='Pa')[0]['value'] == 3.
    assert _paired_extreme_position_metrics_from_series(series,
        metric_name='position', x_unit='C', extreme='maximum')[0]['value'] == 0.
    assert _paired_steepest_drop_position_metrics_from_series(series,
        metric_name='drop', x_unit='C')[0]['value'] == 0.
    pd.testing.assert_frame_equal(frame, before)
    assert series[0][0] == 'Original' and series[0][1] is frame
    raw = pd.DataFrame([['Temperature', 'Loss Factor'], ['C', '1'], ['Original', 'Original'],
        [0, 3], [1, None], [2, 1]])
    raw_before = raw.copy(deep=True)
    projected = metric_tables._labeled_paired_curve_table(
        raw, x_tokens=('temperature',), y_tokens=('loss factor',))
    assert projected[0][1].to_numpy().tolist() == [[0., 3.], [2., 1.]]
    pd.testing.assert_frame_equal(raw, raw_before)


def test_loss_factor_refusal_is_not_replaced_by_later_storage_observation(tmp_path, monkeypatch):
    from sciplot_core.materials_rules import analysis

    source = tmp_path / 'original.csv'
    _source(source)
    events = []
    read, project = metric_tables.read_raw_table, metric_tables._labeled_paired_curve_table
    calculate = analysis._peak_y_metrics_from_series
    refusal = ArithmeticError('generated loss-factor calculation refusal')

    def observe(path):
        events.append('read')
        return read(path)

    def project_loss(raw, **options):
        events.append(options['y_tokens'])
        if options['y_tokens'] == ('storage modulus',):
            raise AssertionError('A later storage projection replaced the original refusal')
        return project(raw, **options)

    def refuse_loss(*_args, **_kwargs):
        events.append('loss-factor calculation')
        raise refusal

    monkeypatch.setattr(metric_tables, 'read_raw_table', observe)
    monkeypatch.setattr(metric_tables, '_labeled_paired_curve_table', project_loss)
    monkeypatch.setattr(analysis, '_peak_y_metrics_from_series', refuse_loss)
    with pytest.raises(ArithmeticError) as caught:
        _compute(source, tmp_path / 'output')
    assert caught.value is refusal
    assert events == ['read', ('loss factor', 'tan delta'), 'loss-factor calculation']
    assert not (tmp_path / 'output').exists()
    events.clear()

    def calculate_loss(*args, **options):
        events.append('loss-factor calculation')
        return calculate(*args, **options)

    monkeypatch.setattr(analysis, '_peak_y_metrics_from_series', calculate_loss)
    semantic = semantic_payload_from_rule(get_rule('rheology_temperature_sweep'), confidence=1)
    semantic['axis_plan'].pop('x')
    with pytest.raises(KeyError) as missing:
        compute_analysis_metrics(source_path=source, processed_source=None,
            semantic=semantic, output_dir=tmp_path / 'missing-unit')
    assert missing.value.args == ('x',)
    assert events == ['read', ('loss factor', 'tan delta'), 'loss-factor calculation']


def test_missing_nonfinite_points_keep_skipped_metrics_without_inventing_a_curve(tmp_path, monkeypatch):
    source = tmp_path / 'sparse.csv'
    pd.DataFrame([['Temperature', 'Storage Modulus', 'Loss Factor'], ['C', 'Pa', '1'],
        ['Original'] * 3, [0, None, None], [1, float('inf'), None]]).to_csv(source, header=False, index=False)
    read = metric_tables.read_raw_table
    observed = []

    def observe(path):
        observed.append(path)
        return read(path)

    monkeypatch.setattr(metric_tables, 'read_raw_table', observe)
    before = source.read_bytes()
    rows = _compute(source, tmp_path / 'output')
    assert observed == [source]
    assert [row['status'] for row in rows] == ['skipped'] * 3
    assert [row['value'] for row in rows] == [''] * 3
    assert rows[-1]['reason'] == 'At least three distinct finite paired points are required.'
    assert source.read_bytes() == before
