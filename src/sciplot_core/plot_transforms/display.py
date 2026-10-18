"""Bounded display-only PCHIP; original measurement arrays remain authoritative."""
import math
from typing import Any

import scipy  # type: ignore[import-untyped]
from scipy.interpolate import PchipInterpolator  # type: ignore[import-untyped]

from sciplot_core.plot_document.errors import fail

MAX_DISPLAY_POINTS = 100_000


def interpolate_display(x: list[float | None], y: list[float | None], *, method: str,
                        subdivisions: int, purpose: str, boundary: str) -> dict[str, Any]:
    """Pass original points exactly; no extrapolation, sorting, gap fill or fitting.

    Duplicate coordinates retain both measurements and split interpolation runs.
    Missing pairs retain an explicit gap. This result is only for drawing a line;
    point marks, statistics, scientific hashes and exported measurements use input.
    """
    if method != "pchip" or purpose != "display" or boundary != "preserve_gaps" or type(subdivisions) is not int or not 1 <= subdivisions <= 32:
        fail("display_interpolation_invalid", "Use bounded display-only PCHIP with explicit gap preservation and 1–32 subdivisions.", "/display/interpolation", "closed_display_contract")
    if len(x) != len(y) or not x:
        fail("display_interpolation_ragged", "Display interpolation needs nonempty equally sized coordinate arrays.", "/display/interpolation", "equal_point_count")
    if any(value is not None and (type(value) not in {int, float} or not math.isfinite(value)) for value in [*x, *y]):
        fail("display_interpolation_nonfinite", "Display coordinates must be finite measurements or explicit gaps.", "/display/interpolation", "finite_coordinates")
    if (len(x) - 1) * subdivisions + 1 > MAX_DISPLAY_POINTS:
        fail("display_interpolation_budget", "The declared display sampling exceeds its bounded point budget.", "/display/interpolation/subdivisions", "bounded_display_points", maximum=MAX_DISPLAY_POINTS)
    runs: list[list[int]] = []
    current: list[int] = []
    for index, (x_value, y_value) in enumerate(zip(x, y, strict=True)):
        if x_value is None or y_value is None:
            if current:
                runs.append(current)
                current = []
            continue
        if current:
            previous = x[current[-1]]
            assert previous is not None
            if x_value < previous:
                fail("display_interpolation_order", "PCHIP cannot reorder acquisition time; resolve stage coordinates explicitly first.", "/display/interpolation", "nondecreasing_coordinates")
            if x_value == previous:
                runs.append(current)
                current = []
        current.append(index)
    if current:
        runs.append(current)
    interpolators = {indices[0]: (indices, PchipInterpolator([x[i] for i in indices], [y[i] for i in indices], extrapolate=False))
                     for indices in runs if len(indices) >= 2}
    sampled_x: list[float | None] = []
    sampled_y: list[float | None] = []
    originals = []
    intervals: list[dict[str, int]] = []
    active: Any = None
    run_end = -1
    for index, (x_value, y_value) in enumerate(zip(x, y, strict=True)):
        if index in interpolators:
            indices, active = interpolators[index]
            run_end = indices[-1]
        originals.append(len(sampled_x))
        sampled_x.append(x_value)
        sampled_y.append(y_value)
        if index >= run_end or x_value is None or y_value is None:
            continue
        next_x, next_y = x[index + 1], y[index + 1]
        assert next_x is not None and next_y is not None
        begin = len(sampled_x)
        for step in range(1, subdivisions):
            coordinate = x_value + (next_x - x_value) * step / subdivisions
            value = float(active(coordinate))
            # Numeric evaluation must stay within the adjacent observed envelope.
            if not min(y_value, next_y) <= value <= max(y_value, next_y):
                fail("display_interpolation_overshoot", "Display interpolation escaped its adjacent measured envelope.", "/display/interpolation", "shape_preserving_interval")
            sampled_x.append(coordinate)
            sampled_y.append(value)
        intervals.append({"left_input_index": index, "right_input_index": index + 1,
                          "output_start": begin, "output_end": len(sampled_x)})
    return {"purpose": purpose, "algorithm": method,
            "implementation": "scipy.interpolate.PchipInterpolator", "implementation_version": scipy.__version__,
            "parameters": {"subdivisions": subdivisions, "boundary": boundary, "extrapolate": False},
            "x": sampled_x, "y": sampled_y, "original_indices": originals,
            "runs": [{"input_indices": indices} for indices in runs], "interpolated_intervals": intervals}
