"""Filesystem prose cannot stand in for a structured comparison source."""

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.materials_rules import compute_analysis_metrics, match_rule
from sciplot_core.render import inspect_payload
from sciplot_core.semantic import classify_source, prepare_semantic_source


def _impact_bytes(tmp_path: Path) -> bytes:
    source = tmp_path / "original.xlsx"
    with pd.ExcelWriter(source) as writer:
        for thickness, offset in (("2 mm", 0.0), ("4 mm", 10.0)):
            pd.DataFrame([
                ["Re", "Re"], ["kJ/m2", "kJ/m2"], ["V-PA", "E-PA"],
                [1.0 + offset, 2.0 + offset], [1.2 + offset, 2.2 + offset],
                [1.4 + offset, 2.4 + offset],
            ]).to_excel(writer, sheet_name=thickness, header=False, index=False)
    return source.read_bytes()


@pytest.mark.parametrize("parent", ["creation-role-final-smoke", "material_performance", "role"])
def test_parent_name_does_not_replace_impact_experiment(tmp_path, parent):
    original = _impact_bytes(tmp_path)
    observations = []
    for name in ("neutral", parent, "neutral-again"):
        source = tmp_path / name / "impact_metric" / "impact strength.xlsx"
        source.parent.mkdir(parents=True)
        source.write_bytes(original)
        semantics = classify_source(source)
        assert semantics["rule_id"] == "impact_metric"
        result = prepare_semantic_source(source, output_dir=source.parent / "prepared", semantic=semantics)
        parameters = result["transform_steps"][0]["parameters"]
        assert parameters["sample_order"] == ["V-PA (2 mm)", "E-PA (2 mm)", "V-PA (4 mm)", "E-PA (4 mm)"]
        assert parameters["replicate_count_total"] == 12
        metrics = compute_analysis_metrics(source_path=source, processed_source=source,
            semantic=semantics, output_dir=source.parent / "analysis")
        assert len(metrics) == 12
        assert source.read_bytes() == original
        observations.append((parameters["sample_order"], parameters["replicate_count_total"], metrics))
    assert observations[0] == observations[1] == observations[2]


@pytest.mark.parametrize("parent", ["creation-role-final-smoke", "material_performance", "unit"])
def test_parent_name_cannot_admit_an_unreadable_table(tmp_path, parent):
    original = b"not,a,usable,table\nthis is non-empty gibberish\n"
    for name in ("neutral", parent, "neutral-again"):
        source = tmp_path / name / "rheology_frequency_sweep" / "corrupt.csv"
        source.parent.mkdir(parents=True)
        source.write_bytes(original)
        with pytest.raises(ValueError, match="no supported numeric measurement layout"):
            inspect_payload(source)
        assert source.read_bytes() == original


@pytest.mark.parametrize("parent", ["neutral", "rheology_frequency_sweep", "creation-role-final-smoke"])
def test_comparison_headers_and_explicit_intent_keep_their_authority(tmp_path, parent):
    source = tmp_path / parent / "neutral.csv"
    source.parent.mkdir()
    source.write_text("Material,Role,Metric,Value,Unit\nA,sample,density,1,g/cm3\n", encoding="utf-8")
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    assert classify_source(source)["rule_id"] == "performance_comparison"
    assert classify_source(source, requested_rule_id="performance_comparison")["rule_id"] == "performance_comparison"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original


def test_comparison_contract_is_not_inferred_from_free_text():
    evidence = "/material_performance/role/metric/value/unit/not-a-contract.csv"
    result = match_rule(evidence=evidence, compact_evidence=evidence.replace("/", ""))
    assert result is None or result.rule_id != "performance_comparison"
    explicit = match_rule(evidence=evidence, compact_evidence=evidence, requested_rule_id="performance_comparison")
    assert explicit.rule_id == "performance_comparison"
