"""Pure current inside-best scoring and anchor projection over prepared geometry."""
import math
from typing import Any

from .native_key_budget import native_key_budget


def inside_best_geometry(
    curves: list[tuple[str, list[tuple[float, float]]]],
    options: dict[str, Any],
    *,
    margins_mm: dict[str, float],
    font_size_pt: float,
    key_length_mm: float,
    frame_visible: bool,
) -> tuple[list[tuple[float, float]], dict[str, float | int]] | None:
    """Project explicit axes and the retained physical footprint model.

    A relatively degenerate axis still needs the retained range fallback (which
    can extend a log domain to anchored decades). Ordinary explicit axes do not
    use that branch. Project each axis in its actual displayed direction.
    """
    bounds = [(float(options[f"{axis}_min"]), float(options[f"{axis}_max"]))
              for axis in ("x", "y")]
    if any(math.isclose(lo, hi) for lo, hi in bounds):
        return None
    transforms = [options[f"{axis}scale"] for axis in ("x", "y")]
    for index, axis in enumerate(("x", "y")):
        if options.get(f"reverse_{axis}") is True:
            bounds[index] = bounds[index][::-1]
    axis_ranges = [(math.log10(lo), math.log10(hi)) if transform == "log" else (lo, hi)
                   for (lo, hi), transform in zip(bounds, transforms, strict=True)]
    samples: list[tuple[float, float]] = []
    for _label, coordinates in curves:
        previous = None
        for x_value, y_value in coordinates:
            x, y = float(x_value), float(y_value)
            if (transforms[0] == "log" and x <= 0.) or (transforms[1] == "log" and y <= 0.):
                continue
            values = [math.log10(value) if scale == "log" else value
                      for value, scale in zip((x, y), transforms, strict=True)]
            (x_low, x_high), (y_low, y_high) = axis_ranges
            point = ((values[0] - x_low) / (x_high - x_low), (values[1] - y_low) / (y_high - y_low))
            if not all(math.isfinite(part) and 0. <= part <= 1. for part in point):
                continue
            samples.append(point)
            if previous is not None:
                for step in range(1, 5):
                    fraction = step / 5.0
                    samples.append((previous[0] + (point[0] - previous[0]) * fraction,
                                    previous[1] + (point[1] - previous[1]) * fraction))
            previous = point
    width_mm, height_mm = (max(1, int(float(size))) for size in options["size"].split("x", maxsplit=1))
    graph_width = max(float(width_mm) - margins_mm["left"] - margins_mm["right"], 1.)
    graph_height = max(float(height_mm) - margins_mm["top"] - margins_mm["bottom"], 1.)
    count = len(curves)
    longest = max((len(label) for label, _coordinates in curves), default=0)
    columns = 1 if count <= 4 or (width_mm <= 60.5 and longest >= 22) else 2
    rows = max(1, math.ceil(count / columns))
    box_width, box_height, font_height = native_key_budget(
        label_cells=longest, font_size_pt=font_size_pt, key_length_mm=key_length_mm,
        columns=columns, rows=rows, frame_visible=frame_visible, margin_size=.15,
    )
    return samples, {"columns": columns, "rows": rows, "font_height_mm": font_height,
                     "graph_width_mm": graph_width, "graph_height_mm": graph_height,
                     "box_width_mm": min(box_width, graph_width * .92),
                     "box_height_mm": min(box_height, graph_height * .82)}


def score_inside_best(samples: list[tuple[float, float]], footprint: dict[str, float | int],
                      *, edge_padding_mm: float, clearance_mm: float) -> dict[str, Any]:
    """Preserve exact legacy corner scoring without importing its footprint owner."""
    graph_width_mm = float(footprint["graph_width_mm"])
    graph_height_mm = float(footprint["graph_height_mm"])
    width = float(footprint["box_width_mm"]) / graph_width_mm
    height = float(footprint["box_height_mm"]) / graph_height_mm
    horizontal_pad = min(edge_padding_mm / graph_width_mm, max(0.0, 1.0 - width))
    vertical_pad = min(edge_padding_mm / graph_height_mm, max(0.0, 1.0 - height))
    candidates = {
        "upper_right": (
            1.0 - horizontal_pad - width,
            1.0 - horizontal_pad,
            1.0 - vertical_pad - height,
            1.0 - vertical_pad,
        ),
        "lower_right": (
            1.0 - horizontal_pad - width,
            1.0 - horizontal_pad,
            vertical_pad,
            vertical_pad + height,
        ),
        "upper_left": (
            horizontal_pad,
            horizontal_pad + width,
            1.0 - vertical_pad - height,
            1.0 - vertical_pad,
        ),
        "lower_left": (
            horizontal_pad,
            horizontal_pad + width,
            vertical_pad,
            vertical_pad + height,
        ),
    }
    order = ("upper_right", "lower_right", "upper_left", "lower_left")
    metrics: dict[str, dict[str, Any]] = {}
    for name, rectangle in candidates.items():
        left, right, bottom, top = rectangle
        distances = [
            math.hypot(max(left - x, 0.0, x - right) * graph_width_mm,
                       max(bottom - y, 0.0, y - top) * graph_height_mm)
            for x, y in samples
        ]
        minimum = min(distances, default=float("inf"))
        overlaps = sum(distance <= 1e-9 for distance in distances)
        near = sum(distance < clearance_mm for distance in distances)
        proximity_load = sum(
            (clearance_mm - distance) / clearance_mm
            for distance in distances
            if clearance_mm > 0.0 and distance < clearance_mm
        )
        metrics[name] = {
            "rectangle_fraction": [round(value, 6) for value in rectangle],
            "overlap_samples": overlaps,
            "near_samples": near,
            "minimum_curve_clearance_mm": None
            if not math.isfinite(minimum)
            else round(minimum, 6),
            "clearance_deficit_mm": (
                0.0
                if not math.isfinite(minimum)
                else round(max(clearance_mm - minimum, 0.0), 6)
            ),
            "proximity_load": round(proximity_load, 6),
        }

    def score(name: str) -> tuple[Any, ...]:
        item = metrics[name]
        minimum = item["minimum_curve_clearance_mm"]
        safe = minimum is None or float(minimum) >= clearance_mm
        return (
            int(item["overlap_samples"] > 0),
            int(item["overlap_samples"]),
            int(not safe),
            float(item["proximity_load"]),
            float(item["clearance_deficit_mm"]),
            -(float(minimum) if minimum is not None else float("inf")),
            order.index(name),
        )

    selected = min(order, key=score) if samples else "lower_right"
    selected_metrics = metrics[selected]
    minimum = selected_metrics["minimum_curve_clearance_mm"]
    return {
        "position": selected,
        "method": "final_size_physical_clearance_v1",
        "required_curve_clearance_mm": clearance_mm,
        "edge_padding_mm": edge_padding_mm,
        "minimum_curve_clearance_mm": minimum,
        "clearance_status": (
            "safe"
            if minimum is None or float(minimum) >= clearance_mm
            else "best_available_needs_reserve"
        ),
        "footprint": {key: round(float(value), 6) for key, value in footprint.items()},
        "candidates": metrics,
    }


def anchor_fraction(placement: dict[str, Any]) -> list[float]:
    """Project the rounded footprint into a graph-local bottom-left anchor."""
    footprint = placement["footprint"]
    graph_width = max(float(footprint["graph_width_mm"]), 1.0)
    graph_height = max(float(footprint["graph_height_mm"]), 1.0)
    width = min(float(footprint["box_width_mm"]), graph_width)
    height = min(float(footprint["box_height_mm"]), graph_height)
    edge = max(float(placement.get("edge_padding_mm") or 0.0), 0.0)
    horizontal = min(edge / graph_width, max(0.0, 1.0 - width / graph_width))
    vertical = min(edge / graph_height, max(0.0, 1.0 - height / graph_height))
    position = str(placement["position"])
    return [horizontal if position.endswith("left") else max(0.0, 1.0 - horizontal - width / graph_width),
            vertical if position.startswith("lower") else max(0.0, 1.0 - vertical - height / graph_height)]
