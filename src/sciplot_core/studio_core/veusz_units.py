"""Convert physical point, millimetre, and transparency values for Veusz."""

from __future__ import annotations

import math


def _pt(value: float) -> str:
    return f"{float(value):g}pt"


def _cm_from_mm(value: float) -> str:
    return f"{float(value) / 10.0:g}cm"


def _alpha_to_transparency(alpha: float) -> int:
    if not math.isfinite(alpha):
        return 0
    bounded = min(max(float(alpha), 0.0), 1.0)
    return int(round((1.0 - bounded) * 100.0))
