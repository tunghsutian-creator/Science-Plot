"""Declare dma temperature rules."""

from __future__ import annotations

from sciplot_core.policy import (
    DEFAULT_RENDER_OPTIONS as _DEFAULT_RENDER_OPTIONS,
)
from sciplot_core.materials_rules.models import (
    AxisSpec,
    AnalysisSpec,
    SemanticRule,
    _rule,
)

from sciplot_core.materials_rules.catalog_axes import (
    RHEOLOGY_X_TEMPERATURE,
)

DMA_TEMPERATURE_RULES: tuple[SemanticRule, ...] = (
    _rule(
        "dma_temperature_sweep",
        "dma_temperature_sweep",
        "rheology_dma",
        "point_line",
        RHEOLOGY_X_TEMPERATURE,
        AxisSpec(
            "Storage modulus",
            "MPa",
            "Storage modulus, E′ (MPa)",
            aliases=("E'", "storage modulus", "tan delta"),
        ),
        keywords=("dma", "storagemodulusmpa", "tanδ", "tandelta"),
        path_keywords=("dma_temperature_sweep", "dma_temperature"),
        column_aliases=("temperature", "storage modulus", "loss factor", "tan delta"),
        analysis=(
            AnalysisSpec(
                "storage_modulus_drop_temperature_C",
                "largest E′ drop candidate",
                ("temperature", "storage modulus"),
                "C",
            ),
        ),
        render_options={**_DEFAULT_RENDER_OPTIONS, "y_min": 0.0},
        fixture_path=(
            "tests/fixtures/real_world/dma_temperature_sweep/Fig2b_storage_modulus_temperature.csv"
        ),
        fixture_status="ready",
        priority=30,
    ),
)
