"""Generated reader controls retain historical inference and exact text modes."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.performance_comparison.source_tables import _read_source_frame
from sciplot_core.source_tables.parsing import coerce_numeric_series


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_performance_source_reader_preserves_exact_text_and_legacy_inference(
    tmp_path: Path, suffix: str
) -> None:
    text = "0.12345678901234567"
    frame = pd.DataFrame(
        {
            "Material": ["A", "B"],
            "Role": ["sample", "reference"],
            "Metric": ["rho", "rho"],
            "Value": [text, "7.0"],
            "Unit": ["g/cm^3", "g/cm^3"],
        }
    )
    source = tmp_path / f"observations.{suffix}"
    if suffix == "xlsx":
        frame.to_excel(source, index=False)
        historical = pd.read_excel(source)
    else:
        frame.to_csv(source, index=False)
        historical = pd.read_csv(source, engine="python")
    original = source.read_bytes()
    legacy = _read_source_frame(source)
    exact = _read_source_frame(source, exact_numeric=True)
    pd.testing.assert_frame_equal(legacy, historical)
    assert exact["Value"].tolist() == [text, "7.0"]
    assert coerce_numeric_series(exact["Value"]).tolist() == [float(text), 7.0]
    assert exact["Unit"].tolist() == frame["Unit"].tolist()
    assert source.read_bytes() == original
