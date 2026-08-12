from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import sciplot_core.semantic as semantic_module
from sciplot_core.materials_rules import get_rule, iter_rules
from sciplot_core.readiness.rule_contract import rule_contract_hashes


EXPECTED_PREPARATION_ADAPTERS = {
    "performance_comparison": None,
    "impact_metric": "mechanical",
    "dsc_curve": "curve_family",
    "rheology_temperature_sweep": "rheology",
    "rheology_frequency_sweep": "rheology",
    "rheology_stress_relaxation": "rheology",
    "rheology_strain_sweep": "rheology",
    "rheology_stress_sweep": "rheology",
    "rheology_time_sweep": "rheology",
    "dma_frequency_sweep": None,
    "dma_temperature_sweep": "curve_family",
    "rheology_creep": "rheology",
    "dtg_curve": "curve_family",
    "compression_curve": "mechanical",
    "flexural_curve": "mechanical",
    "uvvis_spectrum": "curve_family",
    "tensile_curve": "mechanical",
    "tga_curve": "curve_family",
    "torque_curve": "mechanical",
    "xrd_pattern": "curve_family",
    "saxs_profile": "curve_family",
    "gpc_sec_chromatogram": "curve_family",
    "ftir_spectrum": "curve_family",
    "swelling_curve": "curve_family",
}


EXPECTED_SCIENTIFIC_SOURCE_ADAPTERS = {
    "dma_temperature_sweep": "dma_temperature",
    "dsc_curve": "registered_paired_curve",
    "dtg_curve": "registered_paired_curve",
    "ftir_spectrum": "ftir",
    "rheology_frequency_sweep": "rheology_frequency",
    "rheology_stress_relaxation": "stress_relaxation",
    "rheology_temperature_sweep": "rheology_temperature",
    "tga_curve": "registered_paired_curve",
    "uvvis_spectrum": "registered_paired_curve",
    "xrd_pattern": "registered_paired_curve",
    "saxs_profile": "registered_paired_curve",
    "gpc_sec_chromatogram": "gpc_sec",
}


def test_every_rule_declares_one_preparation_adapter_or_identity() -> None:
    assert {
        rule.rule_id: rule.preparation_adapter for rule in iter_rules()
    } == EXPECTED_PREPARATION_ADAPTERS

    original = get_rule("tga_curve")
    identity = replace(original, preparation_adapter=None)
    assert identity.to_payload() == original.to_payload()
    assert rule_contract_hashes(identity) == rule_contract_hashes(original)


def test_scientific_source_adapter_catalog_matches_rule_owned_seams() -> None:
    assert {
        rule.rule_id: rule.scientific_source_adapter
        for rule in iter_rules()
        if rule.scientific_source_adapter is not None
    } == EXPECTED_SCIENTIFIC_SOURCE_ADAPTERS


@pytest.mark.parametrize(
    ("rule_id", "expected_adapter"),
    [
        ("rheology_stress_relaxation", "rheology"),
        ("tga_curve", "curve_family"),
        ("torque_curve", "mechanical"),
    ],
)
def test_semantic_preparation_calls_only_the_selected_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rule_id: str,
    expected_adapter: str,
) -> None:
    calls = _install_handler_spies(monkeypatch)
    rule = get_rule(rule_id)

    result = semantic_module.prepare_semantic_source(
        tmp_path / "source.csv",
        output_dir=tmp_path / "out",
        semantic={"rule_id": rule.rule_id, "semantic_family": rule.semantic_family},
    )

    assert calls == [expected_adapter]
    assert result["transform_steps"][0]["operation"] == "identity"


def test_family_only_frequency_keeps_compatibility_without_a_family_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_handler_spies(monkeypatch)

    result = semantic_module.prepare_semantic_source(
        tmp_path / "source.csv",
        output_dir=tmp_path / "out",
        semantic={"semantic_family": "rheology_frequency"},
    )

    assert calls == ["rheology"]
    assert result["transform_steps"][0]["operation"] == "identity"


def test_selected_handler_errors_are_not_rewrapped_or_fallbacked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_handler_spies(monkeypatch)

    class SelectedHandlerError(ValueError):
        pass

    def fail_selected(_context: object) -> None:
        calls.append("curve_family_error")
        raise SelectedHandlerError("source contract failed")

    monkeypatch.setattr(
        semantic_module,
        "prepare_curve_family_source",
        fail_selected,
    )

    with pytest.raises(SelectedHandlerError, match="source contract failed"):
        semantic_module.prepare_semantic_source(
            tmp_path / "source.csv",
            output_dir=tmp_path / "out",
            semantic={"rule_id": "tga_curve", "semantic_family": "tga_curve"},
        )

    assert calls == ["curve_family_error"]


def _install_handler_spies(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    for adapter, attribute in (
        ("rheology", "prepare_rheology_source"),
        ("curve_family", "prepare_curve_family_source"),
        ("mechanical", "prepare_mechanical_source"),
    ):
        monkeypatch.setattr(
            semantic_module,
            attribute,
            lambda _context, selected=adapter: calls.append(selected),
        )
    return calls
