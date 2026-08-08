"""Shared scientific and task identity for DMA temperature sweeps."""

from __future__ import annotations

from typing import Any, Final


DMA_TEMPERATURE_RULE_ID: Final = "dma_temperature_sweep"
DMA_TEMPERATURE_RECIPE: Final = "rheology_dma"
DMA_TEMPERATURE_SELECTION_POLICY: Final = "dma_temperature_storage_modulus_single_task"
DMA_TEMPERATURE_FIGURE_ID: Final = "storage_modulus_vs_temperature"
DMA_TEMPERATURE_ARTIFACT_STEM: Final = "temp_storage_modulus"
DMA_TEMPERATURE_DOCUMENT_STEM: Final = DMA_TEMPERATURE_FIGURE_ID
DMA_TEMPERATURE_TEMPLATE: Final = "point_line"
DMA_TEMPERATURE_X_METRIC: Final = "temperature"
DMA_TEMPERATURE_Y_METRIC: Final = "storage_modulus"
DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT: Final = "°C"
DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT: Final = "Pa"
DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT: Final = "MPa"
DMA_TEMPERATURE_CANONICAL_TO_DISPLAY_FACTOR: Final = 1.0e-6
DMA_TEMPERATURE_DEFAULT_Y_MIN: Final = 0.0
DMA_TEMPERATURE_X_LABEL: Final = "Temperature (°C)"
DMA_TEMPERATURE_Y_LABEL: Final = "Storage modulus, E′ (MPa)"
DMA_TEMPERATURE_MODULUS_TO_PA: Final = {
    "gpa": ("GPa", 1.0e9),
    "mpa": ("MPa", 1.0e6),
    "kpa": ("kPa", 1.0e3),
    "pa": ("Pa", 1.0),
}


def dma_temperature_experiment_plan() -> dict[str, Any]:
    """Return the exact one-figure Study Model recommendation."""

    return {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": DMA_TEMPERATURE_FIGURE_ID,
                "title": "Storage modulus vs temperature",
                "metric": DMA_TEMPERATURE_Y_METRIC,
                "x_metric": DMA_TEMPERATURE_X_METRIC,
                "y_metric": DMA_TEMPERATURE_Y_METRIC,
                "default_template": DMA_TEMPERATURE_TEMPLATE,
            },
        ),
    }


__all__ = [
    "DMA_TEMPERATURE_ARTIFACT_STEM",
    "DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT",
    "DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT",
    "DMA_TEMPERATURE_CANONICAL_TO_DISPLAY_FACTOR",
    "DMA_TEMPERATURE_DEFAULT_Y_MIN",
    "DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT",
    "DMA_TEMPERATURE_DOCUMENT_STEM",
    "DMA_TEMPERATURE_FIGURE_ID",
    "DMA_TEMPERATURE_MODULUS_TO_PA",
    "DMA_TEMPERATURE_RECIPE",
    "DMA_TEMPERATURE_RULE_ID",
    "DMA_TEMPERATURE_SELECTION_POLICY",
    "DMA_TEMPERATURE_TEMPLATE",
    "DMA_TEMPERATURE_X_METRIC",
    "DMA_TEMPERATURE_X_LABEL",
    "DMA_TEMPERATURE_Y_METRIC",
    "DMA_TEMPERATURE_Y_LABEL",
    "dma_temperature_experiment_plan",
]
