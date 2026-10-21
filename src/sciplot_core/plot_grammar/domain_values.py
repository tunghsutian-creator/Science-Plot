"""Numeric ordinary-axis projection shared by current-view creation and updates."""
import math


def linear_ticks(domain: list[float]) -> list[float]:
    low, high = domain
    magnitude = 10 ** math.floor(math.log10((high - low) / 5))
    step = next(item * magnitude for item in (1, 2, 2.5, 5, 10) if item * magnitude >= (high - low) / 5)
    first = math.ceil(low / step) * step
    return [round(first + index * step, 12) for index in range(12) if first + index * step <= high + step * 1e-9]


def numeric_axis(values: list[float], *, quantity: str, transform: str, dimension: str,
                 minimum: float | None = None, maximum: float | None = None) -> tuple[list[float], list[float]]:
    """Project explicit endpoints or ordinary defaults; never remove an observation."""
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("An axis requires finite drawable coordinates.")
    if transform == "linear":
        low, high = min(values), max(values)
        span = high - low or max(abs(high) * .05, 1)
        automatic = [low if quantity == "time" else low - span * .05, high + span * .05]
    elif transform == "log":
        if any(value <= 0 for value in values):
            raise ValueError("Logarithmic drawable coordinates must be positive.")
        from sciplot_core.studio_render.axis_limits import compute_axis_limits

        limits = compute_axis_limits([values], kind="line", x_values=[values], xscale="log", yscale="log")
        automatic = list(limits.xlim if dimension == "x" else limits.ylim)
    else:
        raise ValueError("Only linear and log current-view transforms are supported.")
    domain = [float(automatic[0] if minimum is None else minimum), float(automatic[1] if maximum is None else maximum)]
    if not all(math.isfinite(value) for value in domain) or not domain[0] < domain[1] or transform == "log" and domain[0] <= 0:
        raise ValueError("The current endpoint rules do not produce a finite increasing domain.")
    if transform == "linear":
        ticks = linear_ticks(domain)
    else:
        from sciplot_core.policy.axis_defaults import anchored_log_decade_ticks

        ticks = [value for value in anchored_log_decade_ticks(values) if domain[0] <= value <= domain[1]]
    return domain, ticks
