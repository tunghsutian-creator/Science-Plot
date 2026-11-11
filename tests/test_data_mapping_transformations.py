"""Scientific values, unit admission, and replicate counts in mapping operations."""

import pandas as pd
import pytest

from sciplot_core.data_mapping.transformations import _apply_transformation
from sciplot_core.mapping_contract import DeclarativeTransformation


def apply(frame, operation, parameters, units=None):
    return _apply_transformation(frame, units or {}, DeclarativeTransformation(operation, parameters))


def test_unit_conversion_requires_current_unit_and_rejects_repeated_conversion():
    frame = pd.DataFrame({"stress": [1., None]})
    parameters = {"column": "stress", "from_unit": "Pa", "to_unit": "MPa"}
    for output in ({}, {"output_column": "converted"}):
        with pytest.raises(ValueError, match="current unit"):
            apply(frame, "unit_convert", parameters | output, {"stress": "MPa"})
    converted, units, _ = apply(frame, "unit_convert", parameters, {"stress": "[Pa]"})
    assert converted.stress.iloc[0] == pytest.approx(1e-6)
    assert pd.isna(converted.stress.iloc[1])
    assert units == {"stress": "MPa"}
    with pytest.raises(ValueError, match="current unit"):
        apply(converted, "unit_convert", parameters, units)
    alias, _, _ = apply(frame, "unit_convert", parameters | {"from_unit": "[Pa]"}, {"stress": "Pa"})
    pd.testing.assert_frame_equal(alias, converted)
    declared, _, _ = apply(frame, "unit_convert", parameters)
    pd.testing.assert_frame_equal(declared, converted)
    pd.testing.assert_frame_equal(frame, pd.DataFrame({"stress": [1., None]}))


def test_aggregate_counts_match_each_statistic_without_missing_observations():
    frame = pd.DataFrame({"sample": ["a", "a", "a", "b"],
                          "stress": [10., None, 30., None],
                          "strain": [None, 2., None, None]})
    for method in ("mean", "median"):
        parameters = {"group_by": ["sample"], "value_columns": ["stress"], "method": method}
        single, units, _ = apply(frame, "aggregate_replicates", parameters, {"stress": "Pa", "strain": "1"})
        assert single.replicate_count.tolist() == [2, 0]
        assert single.stress.iloc[0] == 20
        assert pd.isna(single.stress.iloc[1])
        assert units == {"stress": "Pa"}
        multi, _, _ = apply(frame, "aggregate_replicates", parameters | {
            "value_columns": ["stress", "strain"], "count_column": "n"})
        assert multi.n_stress.tolist() == [2, 0]
        assert multi.n_strain.tolist() == [1, 0]
        assert multi.strain.iloc[0] == 2
        assert multi.stress.iloc[0] == 20
        without, _, _ = apply(frame, "aggregate_replicates", parameters | {"include_count": False})
        assert without.columns.tolist() == ["sample", "stress"]


def test_aggregate_count_names_cannot_overwrite_group_or_value_columns():
    frame = pd.DataFrame({"sample": ["a"], "stress": [10.], "n_stress": [20.]})
    for parameters in (
        {"value_columns": ["stress"], "count_column": "sample"},
        {"value_columns": ["stress"], "count_column": "stress"},
        {"value_columns": ["stress", "n_stress"], "count_column": "n"},
    ):
        with pytest.raises(ValueError, match="count column already exists"):
            apply(frame, "aggregate_replicates", {"group_by": ["sample"]} | parameters)
