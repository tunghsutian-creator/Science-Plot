"""Current house log-tick algorithm; the retained renderer is not imported."""
import math


def log_minor_ticks(minimum: float | None, maximum: float | None, *, scale: str,
                    major_ticks: tuple[float, ...], multipliers: tuple[float, ...]) -> list[float]:
    """Use open decades over the visible range, without changing the major ticks."""
    if scale != "log" or minimum is None or maximum is None:
        return []
    low, high = sorted((float(minimum), float(maximum)))
    if not math.isfinite(low) or not math.isfinite(high) or low <= 0 or high <= low:
        return []
    visible = sorted(float(value) for value in major_ticks
                     if math.isfinite(value) and low <= float(value) <= high)
    if len(visible) >= 2:
        low, high = visible[0], visible[-1]
    elif visible:
        return []
    ticks: list[float] = []
    for exponent in range(math.floor(math.log10(low)) - 1, math.ceil(math.log10(high)) + 2):
        decade = 10.0**exponent
        for multiplier in multipliers:
            value = multiplier * decade
            if low < value < high:
                ticks.append(value)
    return ticks
