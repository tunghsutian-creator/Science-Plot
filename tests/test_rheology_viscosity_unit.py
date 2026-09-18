import math
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.semantic_sources.rheology_frequency_metrics import (
    complete_frequency_frame,
    complete_sweep_metrics,
)
from sciplot_core.semantic_sources.rheology_sweep_sources import (
    _read_rheology_frequency_comparison_samples,
)

from sciplot_core.policy import RHEOLOGY_METRIC_AXIS_LABELS
from sciplot_core.semantic import _unit_conversion


def test_complex_viscosity_keeps_mpa_seconds_as_canonical_unit() -> None:
    assert _unit_conversion("mPa·s", "mPa·s") == ("mPa·s", 1.0, "identity")
    assert RHEOLOGY_METRIC_AXIS_LABELS["complex_viscosity"] == ("|\\eta^{*}| (mPa·s)")


def test_complex_viscosity_normalizes_other_supported_units_to_mpa_seconds() -> None:
    assert _unit_conversion("Pa·s", "mPa·s") == (
        "mPa·s",
        1000.0,
        "Pa_s_to_mPa_s",
    )
    assert _unit_conversion("cP", "mPa·s") == (
        "mPa·s",
        1.0,
        "cP_to_mPa_s",
    )


def test_missing_viscosity_is_derived_from_original_frequency_and_moduli(tmp_path: Path) -> None:
    source = tmp_path / 'frequency'
    source.mkdir()
    raw = source / 'sample.csv'
    raw.write_text('Angular Frequency,Storage Modulus,Loss Modulus\nrad/s,kPa,kPa\n2,3,4\n4,6,8\n')
    before = raw.read_bytes()
    sample = _read_rheology_frequency_comparison_samples(source)[0]
    assert [row['complex_viscosity'] for row in sample.rows] == [2_500_000., 2_500_000.]
    assert sample.metric_units['complex_viscosity'] == 'mPa·s'
    assert sample.metric_conversions['complex_viscosity']['method'] == 'derived_complex_modulus_over_angular_frequency'
    assert raw.read_bytes() == before


@pytest.mark.parametrize('omega', [0., -1., float('nan'), float('inf')])
def test_invalid_frequency_never_produces_a_partial_viscosity_curve(omega: float) -> None:
    with pytest.raises(ValueError, match='positive finite'):
        complete_sweep_metrics([{'x': omega, 'complex_modulus': 5.}], {'complex_modulus': 'Pa'}, {}, x_label='Angular Frequency', x_unit='rad/s')


def test_reported_viscosity_and_nonfrequency_sweeps_are_not_reinterpreted() -> None:
    row = {'x': 2., 'storage_modulus': 3., 'loss_modulus': 4., 'complex_viscosity': 123.}
    complete_sweep_metrics([row], {'storage_modulus':'Pa', 'loss_modulus':'Pa', 'complex_viscosity':'mPa·s'}, {}, x_label='Angular Frequency', x_unit='rad/s')
    assert row['complex_viscosity'] == 123.
    row = {'x': 200., 'storage_modulus': 3., 'loss_modulus': 4.}
    complete_sweep_metrics([row], {'storage_modulus':'Pa', 'loss_modulus':'Pa'}, {}, x_label='Temperature', x_unit='C')
    assert 'complex_viscosity' not in row


def test_frequency_workbook_derivation_respects_hz_units_and_independent_samples() -> None:
    frame = pd.DataFrame([
        ['Frequency', 'Storage Modulus', 'Loss Modulus', 'Angular Frequency', 'Complex Modulus'],
        ['A', 'A', 'A', 'B', 'B'], ['Hz', 'kPa', 'kPa', 'rad/s', 'Pa'],
        [1., 3., 4., 2., 10.], [2., 6., 8., None, None],
    ])
    before = frame.copy(deep=True)
    result, ledger = complete_frequency_frame(frame)
    assert result.iloc[0].tolist() == ['Angular Frequency','Storage Modulus','Loss Modulus','Complex Viscosity','Angular Frequency','Complex Modulus','Complex Viscosity']
    assert result.iloc[3:5, 3].tolist() == pytest.approx([5_000_000/(2*math.pi)]*2)
    assert result.iat[3, 6] == 5000.
    assert result.iloc[3:5, 0].tolist() == pytest.approx([2*math.pi,4*math.pi])
    assert pd.isna(result.iat[4, 6])
    assert len(ledger) == 2
    pd.testing.assert_frame_equal(frame, before)
    frame.iat[1, 1] = 'Wrong sample'
    with pytest.raises(ValueError, match='sample identities'):
        complete_frequency_frame(frame)


def test_reported_workbook_viscosity_is_converted_without_modulus_replacement() -> None:
    frame = pd.DataFrame([['Frequency','Storage Modulus','Loss Modulus','Complex Viscosity'],['A']*4,['Hz','Pa','Pa','Pa·s'],[2.,3.,4.,123.]])
    result, ledger = complete_frequency_frame(frame)
    assert result.iat[3,3] == 123000.
    assert result.iat[3,0] == pytest.approx(4*math.pi)
    assert result.iat[2,3] == 'mPa·s'
    assert not ledger[0]['derivations']
    assert frame.iat[3,3] == 123.
