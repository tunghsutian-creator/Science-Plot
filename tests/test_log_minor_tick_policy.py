from __future__ import annotations

from sciplot_core.policy import (
    DEFAULT_LOG_MINOR_MULTIPLIERS,
    DEFAULT_LOG_MINOR_TICK_COUNT,
    RHEOLOGY_FREQUENCY_RENDER_OPTIONS,
    RHEOLOGY_TEMPERATURE_RENDER_OPTIONS,
)


def test_log_minor_ticks_use_sparse_five_subdivision_policy() -> None:
    assert DEFAULT_LOG_MINOR_TICK_COUNT == 5
    assert DEFAULT_LOG_MINOR_MULTIPLIERS == (2.0, 4.0, 6.0, 8.0)
    assert (
        RHEOLOGY_FREQUENCY_RENDER_OPTIONS["minor_tick_count"]
        == DEFAULT_LOG_MINOR_TICK_COUNT
    )
    assert (
        RHEOLOGY_TEMPERATURE_RENDER_OPTIONS["y_minor_tick_count"]
        == DEFAULT_LOG_MINOR_TICK_COUNT
    )
