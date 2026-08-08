"""Declare dma temperature rules."""

from __future__ import annotations

from sciplot_core.dma_temperature_contract import (
    DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT,
    DMA_TEMPERATURE_DEFAULT_Y_MIN,
    DMA_TEMPERATURE_RULE_ID,
    DMA_TEMPERATURE_TEMPLATE,
    DMA_TEMPERATURE_Y_LABEL,
)
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
        DMA_TEMPERATURE_RULE_ID,
        DMA_TEMPERATURE_RULE_ID,
        "rheology_dma",
        DMA_TEMPERATURE_TEMPLATE,
        RHEOLOGY_X_TEMPERATURE,
        AxisSpec(
            "Storage modulus",
            DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT,
            DMA_TEMPERATURE_Y_LABEL,
            aliases=("E'", "E′", "E prime", "storage modulus"),
        ),
        keywords=("dma", "eprime", "storagemodulus", "storagemodulusmpa"),
        path_keywords=("dma_temperature_sweep", "dma_temperature"),
        column_aliases=("temperature", "storage modulus", "E'", "E prime"),
        analysis=(
            AnalysisSpec(
                "storage_modulus_drop_temperature_C",
                "largest E′ drop candidate",
                ("temperature", "storage modulus"),
                "C",
            ),
        ),
        render_options={
            **_DEFAULT_RENDER_OPTIONS,
            "y_min": DMA_TEMPERATURE_DEFAULT_Y_MIN,
        },
        fixture_path=(
            "tests/fixtures/real_world/dma_temperature_sweep/Fig2b_storage_modulus_temperature.csv"
        ),
        fixture_status="ready",
        priority=30,
    ),
)
