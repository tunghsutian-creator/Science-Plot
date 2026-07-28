"""Build deterministic rheology and generic axis defaults."""

from __future__ import annotations

import math
from collections.abc import Iterable

from sciplot_core.policy.frame_export import (
    DEFAULT_LOG_TICK_FORMAT,
    LOG_NEAR_DECADE_RATIO,
    DEFAULT_LINEAR_TARGET_MAJOR_TICKS,
    DEFAULT_LINEAR_AXIS_PADDING_FRACTION,
)

RHEOLOGY_FREQUENCY_X_LABEL = "ω (rad s⁻¹)"


RHEOLOGY_FREQUENCY_X_RENDER_LABEL = "\\omega (rad s^{-1})"


RHEOLOGY_FREQUENCY_TICK_FORMAT = DEFAULT_LOG_TICK_FORMAT


LINEAR_NICE_STEPS = (1.0, 2.0, 5.0)


LOG_DISPLAY_STEPS = (1.0, 2.0, 5.0)


LINEAR_OUTER_PADDING_FRACTION = 0.05


BAR_ZERO_BASELINE_NO_LOWER_PADDING = True


RHEOLOGY_METRIC_AXIS_LABELS: dict[str, str] = {
    "storage_modulus": "\\italic{G}′ (Pa)",
    "loss_modulus": "\\italic{G}″ (Pa)",
    "loss_factor": "tan \\delta",
    "tan_delta": "tan \\delta",
    "complex_modulus": "|\\italic{G}^{*}| (Pa)",
    "complex_viscosity": "|\\eta^{*}| (mPa·s)",
}


def anchored_log_decade_ticks(values: Iterable[object]) -> tuple[float, ...]:
    """Return labeled decades that visibly bracket positive log-scale data."""

    positive: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            positive.append(number)
    if not positive:
        return ()
    minimum = min(positive)
    maximum = max(positive)
    lower_exponent = math.floor(math.log10(minimum))
    lower_decade = 10.0**lower_exponent
    if minimum / lower_decade > 5.0:
        lower_exponent += 1
    upper_exponent = math.ceil(math.log10(maximum))
    if upper_exponent > lower_exponent:
        preceding_decade = 10.0 ** (upper_exponent - 1)
        if maximum / preceding_decade <= LOG_NEAR_DECADE_RATIO:
            upper_exponent -= 1
    ticks = [10.0**exponent for exponent in range(lower_exponent, upper_exponent + 1)]
    if len(ticks) == 1 and maximum > minimum:
        only = ticks[0]
        ticks = [only / 10.0, only] if only >= maximum else [only, only * 10.0]
    return tuple(ticks)


def compact_linear_axis(
    values: Iterable[object],
    *,
    target_major_ticks: int = DEFAULT_LINEAR_TARGET_MAJOR_TICKS,
    padding_fraction: float = DEFAULT_LINEAR_AXIS_PADDING_FRACTION,
) -> tuple[float, float, tuple[float, ...]] | None:
    """Build a compact linear range with four to six readable major ticks."""

    finite: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            finite.append(number)
    if not finite:
        return None
    data_min = min(finite)
    data_max = max(finite)
    if math.isclose(data_min, data_max):
        half_span = max(abs(data_min) * 0.05, 1.0)
        data_min -= half_span
        data_max += half_span
    span = data_max - data_min
    padding = span * max(float(padding_fraction), 0.0)
    display_min = data_min - padding
    display_max = data_max + padding
    desired_count = max(int(target_major_ticks), 2)
    raw_step = span / max(desired_count - 1, 1)
    exponent = math.floor(math.log10(raw_step))
    steps = sorted(
        {
            mantissa * 10.0**candidate_exponent
            for candidate_exponent in range(exponent - 1, exponent + 2)
            for mantissa in (1.0, 2.0, 2.5, 5.0, 10.0)
        }
    )
    candidates: list[tuple[tuple[float, ...], tuple[float, ...]]] = []
    for step in steps:
        start_index = math.ceil(display_min / step - 1e-12)
        end_index = math.floor(display_max / step + 1e-12)
        if end_index < start_index:
            continue
        ticks = tuple(
            round(index * step, 12) for index in range(start_index, end_index + 1)
        )
        if len(ticks) < 2:
            continue
        count_penalty = 0.0 if 4 <= len(ticks) <= 6 else 100.0
        score = (
            count_penalty,
            float(abs(len(ticks) - desired_count)),
            abs(math.log(step / raw_step)),
        )
        candidates.append((score, ticks))
    ticks = (
        min(candidates, key=lambda item: item[0])[1]
        if candidates
        else (data_min, data_max)
    )
    return float(display_min), float(display_max), ticks


def rheology_metric_axis_label(value: object) -> str | None:
    """Resolve common rheology metric names and symbols to Veusz math labels."""

    text = str(value or "").strip()
    folded = text.casefold()
    token = "".join(character for character in folded if character.isalnum())
    if any(term in folded for term in ("tan δ", "tanδ", "tan delta")) or token in {
        "lossfactor",
        "tandelta",
    }:
        return RHEOLOGY_METRIC_AXIS_LABELS["loss_factor"]
    if any(term in folded for term in ("η", "eta")) or token in {
        "complexviscosity",
        "viscosity",
    }:
        return RHEOLOGY_METRIC_AXIS_LABELS["complex_viscosity"]
    if (
        "complex modulus" in folded
        or "g*" in folded
        or "g∗" in folded
        or token == "complexmodulus"
    ):
        return RHEOLOGY_METRIC_AXIS_LABELS["complex_modulus"]
    if (
        "loss modulus" in folded
        or "g″" in folded
        or 'g"' in folded
        or "g''" in folded
        or token == "lossmodulus"
    ):
        return RHEOLOGY_METRIC_AXIS_LABELS["loss_modulus"]
    if (
        "storage modulus" in folded
        or "g′" in folded
        or "g'" in folded
        or token == "storagemodulus"
    ):
        return RHEOLOGY_METRIC_AXIS_LABELS["storage_modulus"]
    return RHEOLOGY_METRIC_AXIS_LABELS.get(token)
