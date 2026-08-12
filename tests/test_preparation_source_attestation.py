from __future__ import annotations

from sciplot_core.preparation_source_attestation import (
    SOURCE_ATTESTED_RULE_IDS,
    requires_preparation_source_attestation,
)


def test_preparation_source_attestation_has_one_exact_rule_owner() -> None:
    expected = frozenset(
        {
            "compression_curve",
            "dma_temperature_sweep",
            "flexural_curve",
            "rheology_temperature_sweep",
            "tensile_curve",
        }
    )

    assert SOURCE_ATTESTED_RULE_IDS == expected
    assert all(requires_preparation_source_attestation(value) for value in expected)
    assert not any(
        requires_preparation_source_attestation(value)
        for value in ("stress_relaxation", "dsc_curve", "", None)
    )
