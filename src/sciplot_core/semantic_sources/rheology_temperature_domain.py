"""Compatibility adapter for the shared rheology sweep domain."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.semantic_sources.rheology_sweep_domain import (
    TEMPERATURE_RULE_ID,
    TEMPERATURE_SAMPLE_METRICS,
    ResolvedRheologySweepDomain,
    RheologySweepDomainError,
    RheologySweepSourceFacts,
    _resolve_rheology_temperature_domain,
)
from sciplot_core.semantic_sources.rheology_sweep_sources import (
    _read_rheology_temperature_comparison_samples,
)


ResolvedRheologyTemperatureDomain = ResolvedRheologySweepDomain
RheologyTemperatureDomainError = RheologySweepDomainError
TemperatureSourceFacts = RheologySweepSourceFacts


def resolve_rheology_temperature_domain(
    input_path: Path,
    *,
    request: dict[str, Any],
) -> ResolvedRheologyTemperatureDomain:
    """Resolve temperature data through the shared typed sweep domain."""

    return _resolve_rheology_temperature_domain(
        input_path,
        request=request,
        source_hasher=source_tree_sha256,
        automatic_reader=_read_rheology_temperature_comparison_samples,
    )


__all__ = [
    "ResolvedRheologyTemperatureDomain",
    "RheologyTemperatureDomainError",
    "TEMPERATURE_RULE_ID",
    "TEMPERATURE_SAMPLE_METRICS",
    "TemperatureSourceFacts",
    "resolve_rheology_temperature_domain",
]
