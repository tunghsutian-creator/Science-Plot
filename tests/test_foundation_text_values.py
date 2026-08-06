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
