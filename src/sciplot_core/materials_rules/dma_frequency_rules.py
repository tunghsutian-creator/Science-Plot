"""Declare dma frequency rules."""

from __future__ import annotations

from sciplot_core.policy import (
    RHEOLOGY_FREQUENCY_RENDER_OPTIONS,
)
from sciplot_core.materials_rules.models import (
    AxisSpec,
    AnalysisSpec,
    SemanticRule,
    _rule,
)

from sciplot_core.materials_rules.catalog_axes import (
    RHEOLOGY_X_FREQUENCY,
)

DMA_FREQUENCY_RULES: tuple[SemanticRule, ...] = (
    _rule(
        "dma_frequency_sweep",
        "dma_frequency_sweep",
        "rheology_dma",
        "point_line",
        RHEOLOGY_X_FREQUENCY,
        AxisSpec(
            "Storage modulus",
            "Pa",
            "Storage modulus, E′ (Pa)",
            aliases=("E'", "storage modulus", "E′"),
            priority_labels=("E'", "Storage Modulus", "E′", "tanδ", 'E"'),
            scale="log",
        ),
        keywords=(
            "dmafreq",
            "dma frequency sweep",
            "E' frequency",
            "dmafrequencysweep",
        ),
        path_keywords=(
            "/dma_freq/",
            "dma frequency",
            "dma_frequency_sweep",
            "dma_frequency",
        ),
        column_aliases=(
            "angular frequency",
            "frequency",
            "storage modulus",
            "loss modulus",
            "tan delta",
        ),
        experiment_families=("dma",),
        render_options=RHEOLOGY_FREQUENCY_RENDER_OPTIONS,
        analysis=(
            AnalysisSpec(
                "terminal_storage_modulus_frequency",
                "highest-frequency E′ value",
                ("frequency", "storage modulus"),
                "Pa",
            ),
        ),
        fixture_path=(
            "tests/fixtures/real_world/dma_frequency_sweep/benchmark_vitrimer_20C_digitized.csv"
        ),
        fixture_status="ready",
        priority=30,
        reason=(
            "DMA frequency sweep (isothermal) with source-identified storage "
            "modulus E′ vs angular frequency."
        ),
        scientific_source_adapter="registered_paired_curve",
        figure_plan_adapter="registered_single_curve",
        preparation_adapter="curve_family",
    ),
)
