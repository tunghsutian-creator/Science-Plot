from __future__ import annotations

import numpy as np
import pandas as pd

from sciplot_core.foundation.text_values import clean_text


def test_clean_text_normalizes_scalar_missing_values() -> None:
    for value in (None, pd.NA, pd.NaT, np.nan):
        assert clean_text(value) == ""


def test_clean_text_preserves_non_missing_scalars_and_containers() -> None:
    assert clean_text(np.int64(3)) == "3"
    assert clean_text("  sample  ") == "sample"
    assert clean_text(["sample", "reference"]) == "['sample', 'reference']"


def test_scalar_fast_path_preserves_numeric_text_and_special_value_semantics(monkeypatch):
    calls = []
    original = pd.isna
    def record(value):
        calls.append(value)
        return original(value)
    monkeypatch.setattr(pd, 'isna', record)
    assert [clean_text(value) for value in ['nan', ' NA ', 0, -1, 1.25, True, float('inf'), float('nan')]] == [
        'nan', 'NA', '0', '-1', '1.25', 'True', 'inf', '']
    assert not calls
    assert clean_text(pd.NA) == ''
    assert calls
