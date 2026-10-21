import math
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.semantic_sources.rheology_frequency_metrics import (
    complete_frequency_frame,
    complete_sweep_metrics,
    derive_complex_viscosity,
    is_rheology_component_header,
    is_rheology_magnitude_header,
    validate_complex_viscosity_units,
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


@pytest.mark.parametrize(
    'component',
    ['Im(Complex Viscosity)', 'Re(Complex Viscosity)',
     'Imaginary Complex Viscosity', 'Real Complex Viscosity'],
)
def test_viscosity_components_are_not_magnitude_sources(
    tmp_path: Path, component: str,
) -> None:
    source = tmp_path / 'frequency.csv'
    source.write_text(
        f'Angular Frequency,Storage Modulus,Loss Modulus,{component}\n'
        'rad/s,kPa,kPa,mPa·s\n2,3,4,123\n4,6,8,456\n'
    )
    before = source.read_bytes()
    sample = _read_rheology_frequency_comparison_samples(source)[0]
    assert [row['complex_viscosity'] for row in sample.rows] == [2_500_000.] * 2
    assert sample.metric_conversions['complex_viscosity']['method'] == (
        'derived_complex_modulus_over_angular_frequency'
    )
    assert source.read_bytes() == before


@pytest.mark.parametrize('header', ['Complex Viscosity', '|η*|', 'Complex Viscosity Magnitude'])
def test_explicit_magnitude_is_selected_after_an_imaginary_component(
    tmp_path: Path, header: str,
) -> None:
    source = tmp_path / 'frequency.csv'
    source.write_text(
        f'Angular Frequency,Im(Complex Viscosity),{header},Storage Modulus,Loss Modulus\n'
        'rad/s,mPa·s,Pa·s,Pa,Pa\n2,123,7,3,4\n'
    )
    sample = _read_rheology_frequency_comparison_samples(source)[0]
    assert sample.rows[0]['complex_viscosity'] == 7000.
    evidence = sample.metric_conversions['complex_viscosity']
    assert evidence['method'] == 'Pa_s_to_mPa_s'
    assert evidence['source_header'] == header
    assert evidence['source_column'] == 2
    assert evidence['source_unit_authority'] == 'adjacent_unit_row'


def test_imaginary_viscosity_alone_does_not_offer_a_magnitude(tmp_path: Path) -> None:
    source = tmp_path / 'frequency.csv'
    source.write_text(
        'Angular Frequency,Storage Modulus,Im(Complex Viscosity)\n'
        'rad/s,Pa,mPa·s\n2,3,123\n'
    )
    sample = _read_rheology_frequency_comparison_samples(source)[0]
    assert 'complex_viscosity' not in sample.metric_units
    assert 'complex_viscosity' not in sample.rows[0]


@pytest.mark.parametrize('units', ['rad/s,,Pa', ',Pa,Pa', 'rad/s,Pa,'])
def test_viscosity_derivation_requires_explicit_source_units(
    tmp_path: Path, units: str,
) -> None:
    source = tmp_path / 'frequency.csv'
    source.write_text(
        f'Angular Frequency,Storage Modulus,Loss Modulus\n{units}\n2,3,4\n'
    )
    with pytest.raises(ValueError, match='explicit.*unit'):
        _read_rheology_frequency_comparison_samples(source)


def test_magnitude_header_units_are_evidence_not_default_assumptions(tmp_path: Path) -> None:
    source = tmp_path / 'frequency.csv'
    source.write_text('Angular Frequency [rad/s],Complex Viscosity [Pa·s]\n2,7\n')
    sample = _read_rheology_frequency_comparison_samples(source)[0]
    assert sample.rows[0]['complex_viscosity'] == 7000.
    assert sample.metric_conversions['complex_viscosity']['source_unit_authority'] == 'header'
    assert sample.x_conversion['source_unit_authority'] == 'header'


def test_conflicting_magnitude_units_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / 'frequency.csv'
    source.write_text(
        'Angular Frequency,Complex Viscosity [Pa·s]\nrad/s,mPa·s\n2,7\n'
    )
    with pytest.raises(ValueError, match='Conflicting.*unit'):
        _read_rheology_frequency_comparison_samples(source)


def test_shared_magnitude_derivation_uses_explicit_units_including_hz() -> None:
    assert derive_complex_viscosity(
        2., 3., 4., frequency_unit='Hz', storage_unit='kPa', loss_unit='kPa',
    ) == pytest.approx(5000. / (4. * math.pi))
    assert derive_complex_viscosity(
        2., 3., 4., frequency_unit='rad/s', storage_unit='Pa', loss_unit='Pa',
        output_unit='mPa·s',
    ) == 2500.


@pytest.mark.parametrize(
    'change',
    [dict(omega=0.), dict(omega=-1.), dict(storage=float('inf')),
     dict(loss=float('nan')), dict(frequency_unit=''), dict(storage_unit='psi'),
     dict(loss_unit=''), dict(output_unit='cP')],
)
def test_shared_magnitude_derivation_rejects_unsupported_evidence(change: dict) -> None:
    arguments = dict(
        omega=2., storage=3., loss=4., frequency_unit='rad/s',
        storage_unit='Pa', loss_unit='Pa',
    )
    arguments.update(change)
    with pytest.raises(ValueError):
        derive_complex_viscosity(**arguments)


@pytest.mark.parametrize('quantity', ['Viscosity', 'Modulus'])
def test_component_identity_cannot_pass_a_magnitude_check(quantity: str) -> None:
    header = f'Im(Complex {quantity}) [Pa·s]'
    assert is_rheology_component_header(header)
    assert not is_rheology_magnitude_header(
        header, metric=f'complex_{quantity.casefold()}',
    )


def test_imaginary_modulus_is_not_used_to_derive_viscosity(tmp_path: Path) -> None:
    source = tmp_path / 'frequency.csv'
    source.write_text(
        'Angular Frequency,Im(Complex Modulus),Storage Modulus,Loss Modulus\n'
        'rad/s,Pa,Pa,Pa\n2,123,3,4\n'
    )
    sample = _read_rheology_frequency_comparison_samples(source)[0]
    assert sample.rows[0]['complex_modulus'] == 5.
    assert sample.rows[0]['complex_viscosity'] == 2500.
    assert sample.metric_conversions['complex_modulus']['method'] == (
        'derived_from_storage_and_loss_modulus'
    )


def test_viscosity_unit_preflight_requires_no_observation_or_fabricated_point() -> None:
    assert validate_complex_viscosity_units(
        frequency_unit='Hz', storage_unit='kPa', loss_unit='MPa', output_unit='mPa s',
    ) == (2. * math.pi, 1000., 1_000_000.)


@pytest.mark.parametrize(
    'change',
    [dict(frequency_unit=''), dict(storage_unit=''), dict(loss_unit=''),
     dict(frequency_unit='s'), dict(storage_unit='Pa·s'), dict(output_unit='Pa')],
)
def test_viscosity_unit_preflight_rejects_unsupported_units_without_data(change: dict) -> None:
    units = dict(frequency_unit='rad/s', storage_unit='Pa', loss_unit='Pa', output_unit='Pa s')
    units.update(change)
    with pytest.raises(ValueError):
        validate_complex_viscosity_units(**units)
