from __future__ import annotations

from copy import deepcopy

import pytest

from sciplot_core.studio_core.axis_data_visibility import (
    axis_data_visibility_payload,
    validate_axis_data_visibility,
)


def _spec(*, effective_y_min: float) -> dict[str, object]:
    series = [
        {
            "x_values": [50.0, 100.0, 150.0],
            "y_values": [60.0, 20.0, -0.00076029],
        }
    ]
    axes = {
        "x": {"min": 45.0, "max": 155.0},
        "y": {"min": effective_y_min, "max": 80.0},
    }
    render_options = {"y_min": 0.0}
    return {
        "series_encoding_contract": {"kind": "ordinary-series-marker"},
        "series": series,
        "axes": axes,
        "render_options": render_options,
        "axis_data_visibility": axis_data_visibility_payload(
            series_specs=series,
            axes=axes,
            render_options=render_options,
        ),
    }


def test_visibility_distinguishes_relaxed_default_from_actual_clipping() -> None:
    relaxed = _spec(effective_y_min=-20.0)
    y_relaxed = relaxed["axis_data_visibility"]["axes"]["y"]  # type: ignore[index]
    clipped = _spec(effective_y_min=0.0)
    y_clipped = clipped["axis_data_visibility"]["axes"]["y"]  # type: ignore[index]

    assert y_relaxed["below_configured_min_count"] == 1
    assert y_relaxed["configured_min_relaxed"] is True
    assert y_relaxed["clipped_coordinate_count"] == 0
    assert y_clipped["below_configured_min_count"] == 1
    assert y_clipped["configured_min_relaxed"] is False
    assert y_clipped["clipped_coordinate_count"] == 1


def test_visibility_contract_is_recomputed_from_spec_axes_and_data() -> None:
    spec = _spec(effective_y_min=-20.0)
    validate_axis_data_visibility(spec)
    tampered = deepcopy(spec)
    tampered["axis_data_visibility"]["axes"]["y"][  # type: ignore[index]
        "clipped_coordinate_count"
    ] = 1

    with pytest.raises(ValueError, match="axis data visibility"):
        validate_axis_data_visibility(tampered)
