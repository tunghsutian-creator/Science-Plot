"""Assemble domain rule catalogs in the stable public rule order."""

from __future__ import annotations


from sciplot_core.materials_rules.comparison_rules import COMPARISON_RULES
from sciplot_core.materials_rules.rheology_rules import RHEOLOGY_RULES
from sciplot_core.materials_rules.mechanical_rules import MECHANICAL_RULES
from sciplot_core.materials_rules.thermal_rules import THERMAL_RULES
from sciplot_core.materials_rules.dma_temperature_rules import DMA_TEMPERATURE_RULES
from sciplot_core.materials_rules.spectroscopy_rules import SPECTROSCOPY_RULES
from sciplot_core.materials_rules.swelling_rules import SWELLING_RULES
from sciplot_core.materials_rules.dma_frequency_rules import DMA_FREQUENCY_RULES

from sciplot_core.materials_rules.models import SemanticRule

RULES: tuple[SemanticRule, ...] = (
    COMPARISON_RULES
    + RHEOLOGY_RULES
    + MECHANICAL_RULES
    + THERMAL_RULES
    + DMA_TEMPERATURE_RULES
    + SPECTROSCOPY_RULES
    + SWELLING_RULES
    + DMA_FREQUENCY_RULES
)

_RULE_BY_ID = {rule.rule_id: rule for rule in RULES}
