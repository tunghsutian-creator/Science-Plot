from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.materials_rules.impact_metrics import _impact_metrics
from sciplot_core.semantic import read_impact_condition_payloads
from sciplot_core.semantic_sources.impact_sources import _read_impact_source


def test_impact_source_requires_unit_evidence_and_accepts_compact_header(
    tmp_path: Path,
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
            "Impact strength (kJ/m²)": [1.0, 2.0],
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
