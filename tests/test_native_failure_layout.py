"""Additional decorated axes reserve space before native compilation, never in the renderer."""

from copy import deepcopy

import pytest

from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_grammar import compile_figure
from test_house_style_grammar import house


def dual_figure():
    spec, data = house()
    spec["axis_layout_policy"] = "decorated_secondary_sides_v1"
    spec["scales"].append({"id": "scale:temperature", "dimension": "y", "transform": "linear",
                           "domain": [0, 250], "unit": "°C", "quantity": "temperature", "direction": "ascending"})
    view = spec["views"][0]
    view["axes"].append({"id": "axis:temperature", "scale_id": "scale:temperature", "side": "right",
                          "label": "Temperature (°C)", "visible": True, "label_visible": True,
                          "ticks": [0, 100, 200], "style": {}})
    data["raw:A"]["columns"]["column:2"] = {"label": "Temperature", "unit": "°C", "values": [199, 200, 201]}
    data["raw:A"]["provenance"]["sources"][0]["column_indices"]["column:2"] = 2
    temperature = deepcopy(view["layers"][0])
    temperature.update(id="layer:temperature", mappings={"x": "column:0", "y": "column:2"},
                       mapping_semantics={"x": "frequency", "y": "temperature"}, y_scale="scale:temperature",
                       label="Temperature", legend={"visible": False, "label": "Temperature"}, z_order=1)
    temperature["marks"] = [{"id": "mark:temperature-line", "type": "line", "style": {}}]
    view["layers"].append(temperature)
    view["layers"][0]["marks"][1]["style"] = {"marker_thin_factor": 2}
    return spec, data


def resolved(spec, data):
    return compile_figure(spec, data, scientific_hash="a" * 64, presentation_hash="b" * 64)


def test_house_additional_axis_budget_is_resolved_and_traceable_without_changing_base():
    base_spec, base_data = house()
    single = resolved(base_spec, base_data)
    spec, data = dual_figure()
    before = deepcopy(data)
    dual = resolved(spec, data)
    assert single["layout"]["panels"][0]["plot_mm"] == [14, 5.5, 41.5, 38.5]
    panel = dual["layout"]["panels"][0]
    assert panel["plot_mm"][0:2] == [14, 5.5]
    assert 60 - panel["plot_mm"][0] - panel["plot_mm"][2] >= 14
    assert dual["style_provenance"]["figure:additional_axis_layout"]["policy"] == "decorated_secondary_sides_v1"
    assert dual["style_provenance"]["figure:panel_margins_mm"] == single["style_provenance"]["figure:panel_margins_mm"]
    assert data == before and dual["datasets"] == single["datasets"] | {"raw:A": data["raw:A"]}
    assert dual == resolved(spec, data)


def test_hidden_secondary_axis_does_not_change_frame():
    spec, data = dual_figure()
    spec["views"][0]["axes"][-1]["visible"] = False
    ir = resolved(spec, data)
    assert ir["layout"]["panels"][0]["plot_mm"] == [14, 5.5, 41.5, 38.5]
    assert "figure:additional_axis_layout" not in ir["style_provenance"]


@pytest.mark.comprehensive
def test_real_dual_axis_and_sparse_markers_pass_native_export_and_reopen(tmp_path):
    spec, data = dual_figure()
    ir = resolved(spec, data)
    compiler = ManagedVeuszCompiler(warm=False)
    built = compiler.compile_ir(ir, tmp_path / "native")
    assert built["scientific_audit"]["status"] == "passed"
    assert built["publication_qa"]["status"] == "passed"
    from pathlib import Path
    native = Path(built["document"])
    reopened = compiler.inspect_ir(ir, native)
    assert reopened["status"] == "unchanged"
    assert reopened["scientific_audit"]["status"] == "passed"
    result = compiler.export_ir(ir, native, tmp_path / "exports")
    assert result["ready_to_use"] is True
    assert {item["format"] for item in result["exports"]} == {"pdf", "tiff_300"}
    assert all(Path(item["path"]).stat().st_size > 0 for item in result["exports"])


def test_missing_policy_preserves_historical_dual_axis_ir_and_unknown_policy_rejects():
    from sciplot_core.plot_layout import solve_layout
    from sciplot_core.plot_document import DocumentError
    from test_figure_layout import grid

    spec, views, axes = grid(1, 1)
    right = deepcopy(axes[-1])
    right.update(id="axis:right", side="right")
    margins = {"left": 14, "right": 4.5, "top": 5.5, "bottom": 11}
    old = solve_layout(spec, views, [*axes, right], panel_margins_mm=margins)
    assert old == solve_layout(spec, views, [*axes, right], panel_margins_mm=margins, secondary_axis_policy=None)
    assert old["panels"][0]["plot_mm"][2] == old["panels"][0]["cell_mm"][2] - 18.5
    selected = solve_layout(spec, views, [*axes, right], panel_margins_mm=margins,
                            secondary_axis_policy="decorated_secondary_sides_v1")
    assert selected["panels"][0]["plot_mm"][2] < old["panels"][0]["plot_mm"][2]
    with pytest.raises(DocumentError) as failure:
        solve_layout(spec, views, axes, panel_margins_mm=margins, secondary_axis_policy="future-unknown")
    assert failure.value.reason_code == "figure_layout_policy_invalid"


@pytest.mark.comprehensive
def test_historical_valid_dual_managed_reopens_and_exports_without_ir_conflict(tmp_path):
    import json
    from pathlib import Path

    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.plot_engine.storage import load_head
    from test_figure_document import request_for_figure

    request = request_for_figure(tmp_path)
    source = Path(request["data_binding"]["data_sources"][0]["path"])
    source.write_text("Frequency,Modulus,Temperature\nHz,Pa,°C\n0,1,199\n5,5,200\n10,15,201\n")
    request["data_binding"]["data_sources"][0]["sha256"] = file_sha256(source)
    spec, _ = dual_figure()
    spec.pop("axis_layout_policy")  # Historical projects have no newly introduced policy.
    spec["scales"][-1]["domain"] = [198, 202]
    spec["views"][0]["axes"][-1]["ticks"] = [199, 200, 201]
    request["template_definition"]["figure_spec"] = spec
    request["data_binding"]["slots"]["temperature"] = {
        "series_id": "layer:temperature", "sample": "Temperature",
        "x": {"source_id": "raw:A", "column": "Frequency", "column_index": 0},
        "y": {"source_id": "raw:A", "column": "Temperature", "column_index": 2},
        "x_unit": "Hz", "y_unit": "°C"}
    raw = source.read_bytes()
    service = PlotService()
    try:
        created = service.create(request)
        assert created["ready_to_use"] is True, created
        root = Path(created["plot"])
        old = load_head(root)
        native = Path(old["binding"]["document"])
        native_bytes = native.read_bytes()
        ir_path = Path(old["binding"]["ir_path"])
        ir_bytes = ir_path.read_bytes()
        ir = json.loads(ir_bytes)
        assert ir["layout"]["panels"][0]["plot_mm"] == [14, 5.5, 41.5, 38.5]
        assert "figure:additional_axis_layout" not in ir["style_provenance"]
    finally:
        service.close()
    reopened = PlotService()
    try:
        exported = reopened.export(root)
        assert exported["ready_to_use"] is True and exported["revision"] == 0, exported
        assert load_head(root)["document"] == old["document"]
        assert ir_path.read_bytes() == ir_bytes and native.read_bytes() == native_bytes
        assert source.read_bytes() == raw
    finally:
        reopened.close()
