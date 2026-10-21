from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.materials_rules.impact_metrics import _impact_metrics
from sciplot_core.semantic import read_impact_condition_payloads
from sciplot_core.semantic_sources.impact_sources import _read_impact_source


@pytest.mark.parametrize('unit', ['kJ/m2', 'kJ/m²', 'kJ/m^2', 'kJ m⁻²', 'kJ m^-2', 'kJ·m^{-2}', '[kJ/m²]', 'kJ/(m²)'])
def test_complete_impact_identity_spellings_preserve_literal_numbers(unit):
    from sciplot_core.semantic_sources.impact_sources import _validated_impact_unit

    assert _validated_impact_unit([unit]) == 'kJ/m2'


@pytest.mark.parametrize('unit', ['kJ/mm²', 'kJ/cm²', 'kJ/mm^2', 'kJ cm⁻²', 'kJ/m', 'J/m²', 'kJ/m² extra', 'kJ/m²/s'])
def test_impact_whole_and_raw_mapping_share_complete_unit_identity(tmp_path, unit):
    import hashlib
    from sciplot_core.data_mapping.table_choice import replicate_proposal_contents, select_table, source_table_snapshot

    source = tmp_path / 'impact.csv'
    source.write_text('Impact strength,Note\n' + unit + ',\nAmber,\n-0.0,first\n,missing\n2.5,last\n')
    original = source.read_bytes()
    sha = hashlib.sha256(original).hexdigest()
    with pytest.raises(ValueError, match='unsupported values'):
        _read_impact_source(source)
    snapshot = source_table_snapshot(source, rule_id='impact_metric')
    selection = {'sheet': None, 'header_rows': [0], 'unit_row': 1, 'sample_row': 2,
                 'data_start_row': 3, 'data_end_row': 6}
    facts = select_table(snapshot, selection)
    assert facts['columns'][0]['unit'] == unit
    with pytest.raises(ValueError, match='unsupported values'):
        replicate_proposal_contents(facts, [{'column_index': 0}])
    assert source.read_bytes() == original and hashlib.sha256(source.read_bytes()).hexdigest() == sha


def test_impact_raw_identity_does_not_invent_a_numeric_conversion(tmp_path):
    import hashlib
    from sciplot_core.data_mapping.table_choice import replicate_proposal_contents, select_table, source_table_snapshot

    source = tmp_path / 'impact.csv'
    source.write_text('Impact strength,Note\nkJ m⁻²,\nAmber,\n-0.0,first\n,missing\n2.5,last\n')
    original = source.read_bytes()
    selection = {'sheet': None, 'header_rows': [0], 'unit_row': 1, 'sample_row': 2,
                 'data_start_row': 3, 'data_end_row': 6}
    facts = select_table(source_table_snapshot(source, rule_id='impact_metric'), selection)
    contents = replicate_proposal_contents(facts, [{'column_index': 0}])
    assert contents['unit_overrides'] == {'Impact strength': 'kJ/m2'}
    assert 'transformations' not in contents
    reference = contents['sources'][0]
    assert reference.sha256 == hashlib.sha256(original).hexdigest()
    assert (reference.data_start_row, reference.data_end_row) == (3, 6)
    assert source.read_bytes() == original


@pytest.mark.parametrize('header', ['Impact strength (kJ/m²)', 'Impact strength kJ/m²', 'Impact strength kJ/(m²)'])
def test_impact_source_requires_unit_evidence_and_accepts_compact_header(
    tmp_path: Path, header: str,
) -> None:
    missing_unit = tmp_path / "missing_unit.xlsx"
    pd.DataFrame(
        [
            ["Re", "Re", "Note"],
            [None, None, "unit unavailable"],
            ["A", "B", None],
            [1.0, 2.0, None],
            [1.5, 2.5, None],
        ]
    ).to_excel(missing_unit, header=False, index=False)

    with pytest.raises(ValueError, match="Impact strength unit is missing"):
        read_impact_condition_payloads(missing_unit)

    explicit_header = tmp_path / "explicit_header.csv"
    pd.DataFrame(
        {
            "sample": ["A", "A"],
            header: [1.0, 2.0],
        }
    ).to_csv(explicit_header, index=False)

    payload = _read_impact_source(explicit_header)

    assert payload.unit == "kJ/m2"
    assert payload.samples == ("A",)
    assert payload.values == ((1.0, 2.0),)


def test_unitless_impact_analysis_keeps_counts_and_skips_statistics(
    tmp_path: Path,
) -> None:
    legacy_source = tmp_path / "legacy_impact.csv"
    pd.DataFrame(
        [
            ["Impact strength", "Impact strength"],
            [None, "kJ/m2"],
            ["A", "B"],
            [1.0, 3.0],
            [2.0, 4.0],
        ]
    ).to_csv(legacy_source, header=False, index=False)

    rows = {row["metric"]: row for row in _impact_metrics(legacy_source)}

    assert rows["impact_group_n[A]"]["value"] == 2
    assert rows["impact_group_median[A]"]["value"] == ""
    assert rows["impact_group_median[A]"]["unit"] == ""
    assert rows["impact_group_median[A]"]["status"] == "skipped"
    assert rows["impact_group_iqr[A]"]["value"] == ""
    assert rows["impact_group_iqr[A]"]["unit"] == ""
    assert rows["impact_group_iqr[A]"]["status"] == "skipped"
    assert rows["impact_group_median[B]"]["status"] == "ok"
