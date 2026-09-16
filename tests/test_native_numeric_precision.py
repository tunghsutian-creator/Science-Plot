"""New curve specs reject precision loss; old saved specs keep their contract."""

from types import SimpleNamespace

import pytest

from sciplot_core.veusz_worker.numeric_evidence import _dataset_evidence


def test_new_numeric_contract_rejects_six_decimal_serialization():
    original = [4.01729999999999, 1.12345678901234, 1e-120, -0.0]
    saved = [float(f"{value:.6e}") for value in original]
    document = SimpleNamespace(data={"x": SimpleNamespace(data=saved, dimensions=1)}, _sciplot_exact_1d=True)
    with pytest.raises(ValueError, match="differs"):
        _dataset_evidence(document, dataset_name="x", expected_values=original, dimensions=1)
    document.data["x"].data = original
    assert _dataset_evidence(document, dataset_name="x", expected_values=original, dimensions=1)["shape"] == [4]


def test_legacy_numeric_contract_still_checks_reopened_values_exactly():
    original = [4.01729999999999, 1.12345678901234]
    saved = [float(f"{value:.6e}") for value in original]
    document = SimpleNamespace(data={"x": SimpleNamespace(data=saved, dimensions=1)})
    assert _dataset_evidence(document, dataset_name="x", expected_values=original, dimensions=1)["shape"] == [2]
    document.data["x"].data[1] += 1e-12
    with pytest.raises(ValueError, match="differs"):
        _dataset_evidence(document, dataset_name="x", expected_values=original, dimensions=1)
