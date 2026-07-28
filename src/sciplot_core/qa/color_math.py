"""Convert and compare colors under luminance and color-vision models."""

from __future__ import annotations

import math
from typing import Any


_CVD_MATRICES: dict[str, tuple[tuple[float, float, float], ...]] = {
    "protanopia": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deuteranopia": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.01182, 0.04294, 0.968881),
    ),
    "tritanopia": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.3039),
    ),
}


def _srgb_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(value: float) -> float:
    clipped = min(max(value, 0.0), 1.0)
    return (
        12.92 * clipped
        if clipped <= 0.0031308
        else 1.055 * clipped ** (1.0 / 2.4) - 0.055
    )


def _simulate_cvd(
    rgb: list[float], matrix: tuple[tuple[float, float, float], ...]
) -> list[float]:
    linear = [_srgb_to_linear(float(value)) for value in rgb]
    simulated = [
        sum(row[index] * linear[index] for index in range(3)) for row in matrix
    ]
    return [_linear_to_srgb(value) for value in simulated]


def _lab(rgb: list[float]) -> tuple[float, float, float]:
    red, green, blue = (_srgb_to_linear(float(value)) for value in rgb)
    x = (0.4124564 * red + 0.3575761 * green + 0.1804375 * blue) / 0.95047
    y = 0.2126729 * red + 0.7151522 * green + 0.072175 * blue
    z = (0.0193339 * red + 0.119192 * green + 0.9503041 * blue) / 1.08883

    def transform(value: float) -> float:
        return (
            value ** (1.0 / 3.0) if value > 0.008856 else 7.787 * value + 16.0 / 116.0
        )

    fx, fy, fz = transform(x), transform(y), transform(z)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def _delta_e(left: list[float], right: list[float]) -> float:
    lab_left = _lab(left)
    lab_right = _lab(right)
    return math.sqrt(
        sum((a - b) ** 2 for a, b in zip(lab_left, lab_right, strict=True))
    )


def _relative_luminance(rgb: list[float]) -> float:
    red, green, blue = (_srgb_to_linear(float(value)) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _rgb_matches(
    left: list[float], right: list[float], tolerance: float = 2.5 / 255.0
) -> bool:
    return all(
        abs(float(a) - float(b)) <= tolerance for a, b in zip(left, right, strict=True)
    )


def _sample_color_scale(
    control_colors: list[dict[str, Any]], count: int = 16
) -> list[list[float]]:
    controls = [
        item.get("rgb") for item in control_colors if isinstance(item.get("rgb"), list)
    ]
    if len(controls) < 2:
        return []
    samples: list[list[float]] = []
    for index in range(count):
        position = index / max(count - 1, 1) * (len(controls) - 1)
        left_index = min(int(math.floor(position)), len(controls) - 2)
        fraction = position - left_index
        left = controls[left_index]
        right = controls[left_index + 1]
        samples.append(
            [
                float(a) + (float(b) - float(a)) * fraction
                for a, b in zip(left, right, strict=True)
            ]
        )
    return samples


def _turn_count(values: list[float], tolerance: float = 0.005) -> int:
    signs: list[int] = []
    for left, right in zip(values, values[1:], strict=False):
        delta = right - left
        if abs(delta) <= tolerance:
            continue
        sign = 1 if delta > 0 else -1
        if not signs or signs[-1] != sign:
            signs.append(sign)
    return max(len(signs) - 1, 0)
