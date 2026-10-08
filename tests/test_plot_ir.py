"""Managed semantic authority survives renderer deletion and presentation changes."""

from copy import deepcopy

import pytest

from sciplot_core.plot_document import DocumentError, build_keys, seal_document
from sciplot_core.plot_ir import apply_theme, compile_document, create_managed_document, validate_ir
from sciplot_core.plot_transforms import builtin_executor, resolve_transforms


def managed_example():
    def obj(kind, label, properties):
        types = {"style.line.width": "physical_size", "style.line.color": "color", "font.size": "physical_size",
                 "axis.limits": "number_pair", "legend.visible": "boolean", "legend.position": "number_pair"}
        return {"kind": kind, "label": label, "properties": properties,
                "capabilities": {name: {"type": types[name], "risk": "review" if name in {"axis.limits", "legend.position"} else "presentation"}
                                 for name in properties}}

    style = {"line_color": "#222222", "line_width_pt": .7, "line_style": "solid", "line_join": "round",
             "marker": "circle", "marker_size_pt": 3, "marker_color": "#222222", "marker_line_width_pt": .5,
             "line_visible": True, "marker_visible": False}
    objects = {"slot:A": obj("series", "placeholder A", {"style.line.width": "0.7pt", "style.line.color": "#222222"}),
               "slot:B": obj("series", "placeholder B", {"style.line.width": "0.7pt", "style.line.color": "#2255aa"}),
               "axis:x": obj("axis", "Time", {"font.size": "7pt", "axis.limits": [0, 3]}),
               "axis:y": obj("axis", "Normalized signal", {"font.size": "7pt", "axis.limits": [0, 1.2]}),
               "legend:main": obj("legend", "Samples", {"font.size": "6pt", "legend.visible": True, "legend.position": [.55, .85]})}
    axes = {name: {"id": "axis:" + name, "label": "Time" if name == "x" else "Normalized signal",
        "unit": "s" if name == "x" else "1", "scale": "linear", "limits": [0, 3] if name == "x" else [0, 1.2],
        "ticks": [0, 1, 2, 3] if name == "x" else [0, .5, 1], "font_family": "Arial", "font_size_pt": 7,
        "visible": True, "label_visible": True, "line_width_pt": .5, "line_color": "#000000",
        "tick_length_pt": 3, "tick_direction": "in"} for name in ("x", "y")}
    layout = {"kind": "cartesian", "dimensions": {"width_mm": 60, "height_mm": 55},
        "margins_mm": {"left": 12, "right": 3, "top": 5, "bottom": 10}, "axes": axes,
        "legend": {"id": "legend:main", "visible": True, "position": [.55, .85], "font_family": "Arial", "font_size_pt": 6},
        "annotations": [], "series_styles": {"slot:A": deepcopy(style), "slot:B": deepcopy(style)}, "background_color": "#ffffff"}
    template = {"kind": "sciplot_template", "schema_version": 1, "template_id": "ordinary-xy",
        "series_slots": ["slot:A", "slot:B"], "presentation": {"objects": objects, "layout": layout,
        "theme": {}, "export_configuration": {"formats": ["pdf", "tiff_300"]}}}
    selection = {"sheet": None, "header_rows": [0], "data_start_row": 2, "data_end_row": 5, "unit_row": 1}
    sources = [{"source_id": name, "sha256": char * 64, "path": "/original/" + name + ".csv", "table_selection": deepcopy(selection)}
               for name, char in (("A", "a"), ("B", "b"))]
    slots = {"slot:" + name: {"series_id": "series:" + name, "sample": name,
        "x": {"source_id": name + "-normalized", "column": "Time", "column_index": 0},
        "y": {"source_id": name + "-normalized", "column": "Signal", "column_index": 1},
        "x_unit": "s", "y_unit": "1"} for name in ("A", "B")}
    transforms = [{"id": "normalize-" + name, "kind": "normalize", "inputs": [name], "output": name + "-normalized",
        "parameters": {"columns": ["column:1"], "method": "max_abs", "output_unit": "1"},
        "executor": builtin_executor(), "determinism": "deterministic"} for name in ("A", "B")]
    binding = {"kind": "sciplot_binding", "schema_version": 1, "template_id": template["template_id"],
               "data_sources": sources, "slots": slots, "transforms": transforms, "guards": {}, "provenance": {}}
    datasets = {source["source_id"]: {"id": source["source_id"], "columns": {
        "column:0": {"label": "Time", "unit": "s", "values": [0, 1, 2]},
        "column:1": {"label": "Signal", "unit": "V", "values": [2, None, 4] if source["source_id"] == "A" else [1, 2, 3]}},
        "provenance": {"sources": [{"source_id": source["source_id"], "sha256": source["sha256"],
            "table_selection": deepcopy(selection), "column_indices": {"column:0": 0, "column:1": 1}, "rows": [2, 3, 4]}], "transforms": []}}
        for source in sources}
    return template, binding, datasets


def resolved_example():
    template, binding, datasets = managed_example()
    document = create_managed_document(template, binding, plot_id="example")
    return resolve_transforms(document, datasets), datasets


def test_rebuild_is_pure_identical_and_keeps_missing_values_and_stable_ids():
    resolved, raw = resolved_example()
    document = resolved["document"]
    first = compile_document(document)
    rebuilt = resolve_transforms(document, raw)["document"]
    second = compile_document(rebuilt)
    assert first == second
    assert first["series"][0]["y"] == [.5, None, 1]
    assert [series["id"] for series in first["series"]] == ["series:A", "series:B"]
    assert rebuilt["scientific_hash"] == document["scientific_hash"]
    assert "backend" not in first and "native_path" not in str(first)
    unrelated = deepcopy(document)
    unrelated.update(plot_id="other-id", revision=123, backend={"name": "unrelated"})
    assert compile_document(unrelated)["ir_hash"] == first["ir_hash"]


def test_theme_changes_only_presentation_and_does_not_invalidate_transform_nodes():
    resolved, _ = resolved_example()
    paper = resolved["document"]
    theme = {"kind": "sciplot_theme", "schema_version": 1, "theme_id": "presentation", "rules": [
        {"target": ["axis:x", "axis:y"], "property": "font.size", "value": "12pt"},
        {"target": ["series:A", "series:B"], "property": "style.line.width", "value": "1.2pt"}]}
    changed = apply_theme(paper, theme)
    assert changed["scientific"] == paper["scientific"] and changed["scientific_hash"] == paper["scientific_hash"]
    assert changed["presentation_hash"] != paper["presentation_hash"]
    ir = compile_document(changed)
    assert ir["axes"]["x"]["font_size_pt"] == 12 and ir["series"][0]["style"]["line_width_pt"] == 1.2
    reverted = apply_theme(changed, {**theme, "theme_id": "paper", "rules": []})
    assert compile_document(reverted)["series"][0]["style"]["line_width_pt"] == .7
    assert reverted["scientific_hash"] == paper["scientific_hash"]


def test_only_changed_source_and_its_downstream_transform_are_reexecuted():
    resolved, datasets = resolved_example()
    document, datasets = deepcopy(resolved["document"]), deepcopy(datasets)
    document["scientific"]["data_sources"][0]["sha256"] = "c" * 64
    datasets["A"]["provenance"]["sources"][0]["sha256"] = "c" * 64
    datasets["A"]["columns"]["column:1"]["values"][0] = 3
    changed = resolve_transforms(seal_document(document), datasets, cache=resolved["cache"])
    assert changed["executed"] == ["normalize-A"] and changed["reused"] == ["normalize-B"]
    before, after = build_keys(resolved["graph"]), build_keys(changed["graph"])
    assert {key for key in before if before[key] != after[key]} == {
        "source:A", "transform:normalize-A", "mapping:series:A", "compile", "render", "export"}


def test_parameter_change_has_new_science_output_and_only_its_own_descendants():
    resolved, raw = resolved_example()
    changed = deepcopy(resolved["document"])
    changed["scientific"]["transforms"][0]["parameters"].update(method="constant", constant=8)
    output = resolve_transforms(seal_document(changed), raw, cache=resolved["cache"])
    assert output["executed"] == ["normalize-A"] and output["reused"] == ["normalize-B"]
    assert compile_document(output["document"])["series"][0]["y"] == [.25, None, .5]
    assert output["document"]["scientific_hash"] != resolved["document"]["scientific_hash"]
    assert output["document"]["scientific"]["provenance"]["transform_execution"][0]["status"] == "complete"


def test_compiler_uses_supplied_verified_cas_payload_with_canonical_scientific_hash(tmp_path):
    from sciplot_core.plot_engine.content_store import intern_document, resolve_document_content

    resolved, _ = resolved_example()
    canonical = intern_document(tmp_path, resolved["document"], minimum_bytes=1024)
    restored = resolve_document_content(tmp_path, canonical)
    result = compile_document(canonical, restored["scientific"]["provenance"]["datasets"])
    assert result["scientific_hash"] == canonical["scientific_hash"]
    with pytest.raises(DocumentError, match="Resolve"):
        compile_document(canonical)


@pytest.mark.parametrize("mutation", ["unknown_field", "coordinate_swap", "bad_hash", "wrong_unit"])
def test_ir_rejects_unrepresented_or_misbound_content(mutation):
    resolved, _ = resolved_example()
    ir = compile_document(resolved["document"])
    if mutation == "unknown_field":
        ir["native_spec"] = {}
    elif mutation == "coordinate_swap":
        ir["series"][0]["y"][0] = 99
    elif mutation == "bad_hash":
        ir["ir_hash"] = "0" * 64
    else:
        ir["axes"]["x"]["unit"] = "min"
    with pytest.raises(DocumentError):
        validate_ir(ir)


@pytest.mark.parametrize("mutation", ["guard", "export", "clipping", "unrepresented", "unused_source"])
def test_managed_compilation_does_not_ignore_unsupported_scientific_or_presentation_state(mutation):
    resolved, _ = resolved_example()
    document = deepcopy(resolved["document"])
    if mutation == "guard":
        document["scientific"]["guards"] = {"unknown_calculation": True}
    elif mutation == "export":
        document["presentation"]["export_configuration"] = {"formats": ["tiff_600"]}
    elif mutation == "clipping":
        document["presentation"]["objects"]["axis:x"]["properties"]["axis.limits"] = [0, 1]
    elif mutation == "unrepresented":
        document["presentation"]["objects"]["annotation:opaque"] = {
            "kind": "annotation", "label": "Invisible to layout", "properties": {}, "capabilities": {}}
    else:
        document["scientific"]["data_sources"].append({**document["scientific"]["data_sources"][0], "source_id": "unused"})
    with pytest.raises(DocumentError):
        compile_document(seal_document(document))
