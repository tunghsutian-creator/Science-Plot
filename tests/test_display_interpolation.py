"""Display-only PCHIP cannot replace measurements or invent endpoint trends."""
from copy import deepcopy

import pytest

from sciplot_core.plot_document import DocumentError


def interpolate(xs, ys, **options):
    from sciplot_core.plot_transforms.display import interpolate_display
    return interpolate_display(xs, ys, method="pchip", subdivisions=4, purpose="display", boundary="preserve_gaps", **options)


def test_shape_preserving_line_passes_exact_original_points_without_mutating_them():
    xs, ys = [0, 1, 3, 4], [1, 9, 10, 10]
    before = deepcopy((xs, ys))
    result = interpolate(xs, ys)
    assert result["purpose"] == "display" and result["algorithm"] == "pchip"
    assert result["original_indices"] == [0, 4, 8, 12]
    assert [result["x"][i] for i in result["original_indices"]] == xs
    assert [result["y"][i] for i in result["original_indices"]] == ys
    assert result["x"][0] == 0 and result["x"][-1] == 4
    for interval in range(3):
        assert all(min(ys[interval:interval + 2]) <= y <= max(ys[interval:interval + 2]) for y in result["y"][interval * 4:interval * 4 + 5])
    assert (xs, ys) == before
    assert result["parameters"] == {"subdivisions": 4, "boundary": "preserve_gaps", "extrapolate": False}


def test_missing_values_and_duplicate_stage_endpoint_are_retained_without_cross_gap_fit():
    xs, ys = [0, 1, 1, 2, 3, 4, 5], [0, 1, 7, 8, None, 5, 6]
    result = interpolate(xs, ys)
    assert [result["x"][i] for i in result["original_indices"]] == xs
    assert [result["y"][i] for i in result["original_indices"]] == ys
    assert len(result["runs"]) == 3
    assert result["runs"][0]["input_indices"] == [0, 1]
    assert result["runs"][1]["input_indices"] == [2, 3]
    assert result["runs"][2]["input_indices"] == [5, 6]


@pytest.mark.parametrize("xs,ys", [([0, 2, 1], [0, 1, 2]), ([0, 1], [1]), ([0, float('inf')], [1, 2])])
def test_display_interpolation_rejects_reordering_ragged_and_nonfinite_input(xs, ys):
    with pytest.raises(DocumentError):
        interpolate(xs, ys)


def test_display_sampling_has_bounded_cost_and_rejects_scientific_purpose():
    from sciplot_core.plot_transforms.display import interpolate_display
    with pytest.raises(DocumentError):
        interpolate_display([0, 1], [0, 1], method="pchip", subdivisions=4, purpose="scientific", boundary="preserve_gaps")
    with pytest.raises(DocumentError):
        interpolate_display([0, 1], [0, 1], method="pchip", subdivisions=100000, purpose="display", boundary="preserve_gaps")
