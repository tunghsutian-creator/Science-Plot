"""Order rheology sweep samples deterministically."""

from __future__ import annotations

from sciplot_core.foundation.text_values import (
    token as _token,
)


from sciplot_core.semantic_sources.models import (
    RheologySweepSample,
)


def _sweep_sample_order_key(sample: RheologySweepSample) -> tuple[float, str]:
    storage_points = [
        (row["x"], row["storage_modulus"])
        for row in sample.rows
        if "x" in row and "storage_modulus" in row
    ]
    if not storage_points:
        return (float("inf"), sample.sample.casefold())
    reference_x = max(x_value for x_value, _storage in storage_points)
    _x_value, storage = min(storage_points, key=lambda item: abs(item[0] - reference_x))
    return (storage, sample.sample.casefold())


def _ordered_sweep_samples(
    samples: list[RheologySweepSample],
    series_order: object = None,
) -> list[RheologySweepSample]:
    if not isinstance(series_order, list | tuple):
        return samples
    order = {
        _token(sample): index
        for index, sample in enumerate(series_order)
        if isinstance(sample, str) and sample.strip()
    }
    if not order:
        return samples
    fallback = len(order)
    return sorted(
        samples,
        key=lambda sample: (
            order.get(_token(sample.sample), fallback),
            sample.sample.casefold(),
        ),
    )
