"""Schema constants for resolved figure plans."""

from __future__ import annotations

from typing import Final


RESOLVED_FIGURE_PLAN_KIND: Final = "sciplot_resolved_figure_plan"
RESOLVED_FIGURE_PLAN_VERSION: Final = 1
FIGURE_TASK_KIND: Final = "sciplot_figure_task"
FIGURE_TASK_V1_VERSION: Final = 1
FIGURE_TASK_V2_VERSION: Final = 2
FIGURE_TASK_VERSION: Final = FIGURE_TASK_V2_VERSION
FIGURE_OUTCOME_KIND: Final = "sciplot_figure_outcome"
FIGURE_OUTCOME_VERSION: Final = 1
SUPPORTED_FIGURE_PLAN_RULE_IDS = frozenset(
    {
        "dma_temperature_sweep",
        "dsc_curve",
        "impact_metric",
        "performance_comparison",
        "rheology_frequency_sweep",
        "rheology_temperature_sweep",
    }
)


__all__ = [
    "FIGURE_OUTCOME_KIND",
    "FIGURE_OUTCOME_VERSION",
    "FIGURE_TASK_KIND",
    "FIGURE_TASK_V1_VERSION",
    "FIGURE_TASK_V2_VERSION",
    "FIGURE_TASK_VERSION",
    "RESOLVED_FIGURE_PLAN_KIND",
    "RESOLVED_FIGURE_PLAN_VERSION",
    "SUPPORTED_FIGURE_PLAN_RULE_IDS",
]
