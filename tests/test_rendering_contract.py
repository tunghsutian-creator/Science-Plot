"""Rendering authority must match old sources, survive overrides, and reject drift."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from sciplot_core.rendering_contract import (
    COMPOSITION_CONTRACT_ID, audit_legacy_sources, binding_schema, contract_binding,
    contract_value, load_contract, rendering_contract_schema, require_binding,
    resolved_style_defaults, resolved_style_provenance,
)
from sciplot_core.rendering_contract.composition import extract_composition_contract
from sciplot_core.rendering_contract.extraction import extract_house_contract, seal_contract
from sciplot_core.rendering_contract import registry
from sciplot_core.rendering_contract import legacy_algorithms

ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_is_exact_programmatic_extraction_of_existing_authority() -> None:
    assert load_contract() == extract_house_contract(ROOT)
    Draft202012Validator(rendering_contract_schema()).validate(load_contract())
    assert audit_legacy_sources(ROOT)["status"] == "passed"


def test_old_frame_and_physical_metrics_are_retained() -> None:
    assert [contract_value("canvas." + key) for key in ["width_mm", "height_mm"]] == [60, 55]
    assert [contract_value("frame." + key + "_mm") for key in ["left", "right", "top", "bottom"]] == [14, 4.5, 5.5, 11]
    assert resolved_style_defaults("axis") == {
        "font_family": "Arial", "font_size_pt": 7, "font_weight": "normal", "color": "#111111",
        "line_width_pt": 0.8, "tick_length_pt": 2.8, "major_tick_width_pt": 0.8,
        "minor_tick_width_pt": 0.8, "minor_tick_length_pt": 1.5, "label_padding_pt": 2,
        "tick_label_padding_pt": 1.4, "minor_tick_count": 20, "tick_direction": "out",
        "tick_color": "#000000", "grid_visible": False, "minor_grid_visible": False, "minor_ticks_visible": True}
    assert resolved_style_defaults("legend")["font_size_pt"] == 6
    assert resolved_style_defaults("line")["line_width_pt"] == 1.2
    assert resolved_style_defaults("line")["line_opacity"] == 0.92
    assert resolved_style_defaults("point")["marker_opacity"] == 0.95


def test_original_palette_and_marker_sequences_and_opaque_categorical_fill() -> None:
    assert [resolved_style_defaults("line", i)["line_color"] for i in range(3)] == ["#222222", "#3568C0", "#C83E4D"]
    assert [resolved_style_defaults("point", i)["marker"] for i in range(5)] == ["circle", "square", "diamond", "triangle", "circle"]
    assert resolved_style_defaults("point")["marker_thin_factor"] == 1
    assert resolved_style_defaults("bar", 1) == {"border_width_pt": 0.7, "fill_color": "#AFC6ED",
                                               "border_color": "#7898D1", "fill_opacity": 1.0}


def test_unspecified_house_rules_are_not_misreported_as_established_defaults() -> None:
    snapshot = load_contract()
    assert snapshot["properties"]["export.tiff_compression"]["value"] == "unspecified"
    with pytest.raises(ValueError, match="does not specify"):
        contract_value("errorbar.cap_width_pt")
    native = resolved_style_provenance("errorbar")["cap_width_pt"]
    assert native["status"] == "adapter_baseline"
    assert "ErrorBarLine" in native["source_symbol"]
    assert resolved_style_provenance("band")["fill_opacity"]["status"] == "adapter_baseline"
    assert resolved_style_provenance("text")["align_v"]["value"] == "bottom"


def test_contract_binding_is_closed_and_content_bound() -> None:
    binding = contract_binding()
    assert require_binding(binding) == load_contract()
    with pytest.raises(ValueError, match="requires its pinned version"):
        require_binding({**binding, "content_hash": "0" * 64})
    with pytest.raises(ValidationError):
        Draft202012Validator(binding_schema()).validate({**binding, "native_path": "/page1"})
    with pytest.raises(ValueError, match="Unsupported"):
        load_contract("sciplot-unknown-v1")
    changed = load_contract()
    changed["properties"]["line.width_pt"]["value"] = 9
    assert contract_value("line.width_pt") == 1.2


def test_resealed_resource_cannot_change_existing_contract_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    changed = load_contract()
    changed["properties"]["line.width_pt"]["value"] = 9
    changed = seal_contract(changed)
    styles = tmp_path / "styles"
    styles.mkdir()
    (styles / (changed["contract_id"] + ".json")).write_text(json.dumps(changed))
    registry._snapshot.cache_clear()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(registry, "files", lambda _: tmp_path)
            with pytest.raises(ValueError, match="identity mismatch"):
                load_contract()
    finally:
        registry._snapshot.cache_clear()


def test_source_drift_is_a_failure_not_an_automatic_contract_rewrite(tmp_path: Path) -> None:
    files = {record["source_file"] for record in load_contract()["properties"].values() if record["source_file"]}
    for relative in files:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    source = tmp_path / "src/sciplot_core/policy/frame_export.py"
    source.write_text(source.read_text().replace("UNIFIED_LINE_WIDTH_PT = 1.2", "UNIFIED_LINE_WIDTH_PT = 1.3"))
    result = audit_legacy_sources(tmp_path)
    assert result["status"] == "failed"
    diff = {item["property"]: item for item in result["differences"]}
    assert diff["line.width_pt"]["pinned"]["value"] == 1.2
    assert diff["line.width_pt"]["current_source"]["value"] == 1.3
    assert load_contract()["properties"]["line.width_pt"]["value"] == 1.2


def test_composition_policy_is_distinct_and_never_claims_legacy_multi_panel_equivalence() -> None:
    composition = load_contract(COMPOSITION_CONTRACT_ID)
    assert composition == extract_composition_contract()
    assert composition["authority"] == "new_composition_policy"
    assert composition["content_hash"] != load_contract()["content_hash"]
    assert contract_value("gap_x_mm", contract_binding(COMPOSITION_CONTRACT_ID)) == 6
    assert "not a legacy" in composition["properties"]["gap_x_mm"]["notes"]


def test_shared_legacy_algorithms_have_a_separate_package_relative_compiler_pin() -> None:
    binding = contract_binding()
    result = legacy_algorithms.require_legacy_algorithms(binding)
    manifest = legacy_algorithms.extract_algorithm_binding(ROOT / "src/sciplot_core")
    assert result["content_hash"] == manifest["content_hash"]
    assert result["rendering_contract"] == binding
    assert result["checked_sources"] == len(manifest["sources"]) == 24
    assert "policy/plot_contract.json" in manifest["sources"]
    assert "studio_render/value_parsing.py" in manifest["sources"]


def test_axis_notation_override_is_honored_and_derived_tick_policy_is_traced() -> None:
    from sciplot_core.plot_grammar.house import StyleResolver, axis_flow

    resolver = StyleResolver({"rendering_contract": contract_binding()})
    axis = {"id": "axis:test", "ticks": [1.0, 10.0, 100.0],
            "style": resolver.resolve("axis:test", "axis", [], {"minor_tick_count": 9, "tick_notation": "general"})}
    axis_flow(axis, {"transform": "log", "domain": [1.0, 100.0]}, resolver)
    assert axis["tick_notation"] == "general"
    assert axis["style"]["minor_tick_count"] == 9
    assert axis["minor_ticks"] == [2, 4, 6, 8, 20, 40, 60, 80]
    assert resolver.trace["axis:test:tick_policy"]["source"] == "object override"
    linear = {"id": "axis:linear", "ticks": [0.0, 10.0],
              "style": resolver.resolve("axis:linear", "axis", [], {"tick_notation": "power10"})}
    axis_flow(linear, {"transform": "linear", "domain": [0.0, 10.0]}, resolver)
    assert linear["tick_notation"] == "power10"
    assert linear["minor_ticks"] == []


@pytest.mark.parametrize("source", ["policy/frame_export.py", "policy/plot_contract.json", "studio_render/value_parsing.py"])
def test_same_document_binding_rejects_changed_old_policy_or_algorithm_on_new_runtime(
    source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sciplot_core.plot_document import DocumentError
    from sciplot_core.plot_grammar.house import StyleResolver

    binding = contract_binding()
    manifest = legacy_algorithms.extract_algorithm_binding(ROOT / "src/sciplot_core")
    for relative in manifest["sources"]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "src/sciplot_core" / relative, target)
    changed = tmp_path / source
    original = changed.read_text()
    if source == "policy/frame_export.py":
        changed.write_text(original.replace("DEFAULT_LOG_MINOR_MULTIPLIERS = (2.0, 4.0, 6.0, 8.0)",
                                            "DEFAULT_LOG_MINOR_MULTIPLIERS = (2.0, 3.0, 6.0, 8.0)"))
    elif source.endswith(".json"):
        payload = json.loads(original)
        payload["styles"]["nature"]["spacing"]["axes_labelpad"] = 9
        changed.write_text(json.dumps(payload))
    else:
        changed.write_text(original.replace("ticks.append(value)", "ticks.append(value * 1.1)"))
    assert original != changed.read_text()
    resource_files = legacy_algorithms.files
    # A changed installed runtime starts with an empty one-time verification
    # cache. The persistent service rejects live source drift before this step.
    legacy_algorithms._checked_algorithms.cache_clear()
    try:
        monkeypatch.setattr(legacy_algorithms, "files", lambda package: tmp_path if package == "sciplot_core" else resource_files(package))
        assert require_binding(binding) == load_contract()
        with pytest.raises(DocumentError) as caught:
            StyleResolver({"rendering_contract": binding})
        assert caught.value.reason_code == "rendering_contract_algorithm_drift"
    finally:
        legacy_algorithms._checked_algorithms.cache_clear()
