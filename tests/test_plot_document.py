"""Semantic state, atomic patches, dependency invalidation and explicit bindings."""

from copy import deepcopy

import pytest

from sciplot_core.plot_document import (
    DocumentError, apply_patch, artifact_build_key, build_keys, document_schema, instantiate_template,
    invalidated_nodes, seal_document, validate_document, validate_template,
)


def document():
    return seal_document({
        "kind": "sciplot_document", "schema_version": 1, "plot_id": "plot-1", "revision": 4,
        "scientific": {"data_sources": [{"path": "/data/raw.csv", "sha256": "a" * 64}],
                       "transforms": [], "mappings": {"E2": {"x": "time", "y": "Gprime", "unit": "Pa"}},
                       "guards": {"point_counts": {"E2": 5}}, "provenance": {"method": "measured"}},
        "presentation": {"objects": {
            "series-e2": {"kind": "series", "label": "E2", "properties": {"style.line.width": "1pt", "style.line.color": "black"},
                          "capabilities": {"style.line.width": {"type": "physical_size", "risk": "presentation"},
                                           "style.line.color": {"type": "color", "risk": "presentation"}}},
            "series-e4": {"kind": "series", "label": "E4", "properties": {"style.line.width": "1pt"},
                          "capabilities": {"style.line.width": {"type": "physical_size", "risk": "presentation"}}},
            "title-1": {"kind": "title", "label": "Title", "properties": {"title.visible": True, "title.text": "Measured Gprime"},
                        "capabilities": {"title.visible": {"type": "boolean", "risk": "presentation"},
                                         "title.text": {"type": "string", "risk": "review"}}},
        }, "layout": {}, "theme": {}, "export_configuration": {"dpi": 600}},
        "coverage": {"mode": "legacy_shadow", "limitations": ["Unmapped native settings retained in baseline"]},
        "backend": {"baseline_sha256": "b" * 64, "log_path": "/tmp/session-1"},
    })


def patch(changes=None, **overrides):
    return {"plot_id": "plot-1", "base_revision": 4, "idempotency_key": "user-edit-1",
            "intent_class": "presentation", "changes": changes or [
                {"op": "set", "target": ["series-e2", "series-e4"], "property": "style.line.width", "value": "0.7pt"},
                {"op": "set", "target": ["title-1"], "property": "title.visible", "value": False},
            ], **overrides}


def test_semantic_batch_has_exact_diff_without_changing_science_or_revision():
    before = document()
    frozen = deepcopy(before)
    after, diff, risk = apply_patch(before, patch())
    assert before == frozen and after["revision"] == 4
    assert after["scientific"] == before["scientific"]
    assert after["scientific_hash"] == before["scientific_hash"]
    assert after["presentation_hash"] != before["presentation_hash"]
    assert [(item["target"], item["before"], item["after"]) for item in diff] == [
        ("series-e2", "1pt", "0.7pt"), ("series-e4", "1pt", "0.7pt"), ("title-1", True, False)]
    assert risk == "presentation"


def test_runtime_metadata_and_revision_do_not_change_domain_seals():
    original = document()
    changed = deepcopy(original)
    changed.update(revision=78, plot_id="different-instance")
    changed["backend"]["log_path"] = "/tmp/other"
    assert seal_document(changed)["scientific_hash"] == original["scientific_hash"]
    assert seal_document(changed)["presentation_hash"] == original["presentation_hash"]
    changed["scientific"]["mappings"]["E2"]["unit"] = "kPa"
    assert seal_document(changed)["scientific_hash"] != original["scientific_hash"]


@pytest.mark.parametrize("domain", ["scientific", "presentation"])
def test_modified_state_cannot_pass_an_old_seal(domain):
    value = document()
    value[domain]["guards" if domain == "scientific" else "layout"]["tampered"] = True
    with pytest.raises(DocumentError, match="does not match") as exc:
        validate_document(value)
    assert exc.value.reason_code == "document_hash_mismatch"


@pytest.mark.parametrize("value", ["0.7", "-1pt", "0pt", "nanpt", 0.7, True, None])
def test_width_failures_do_not_mutate_either_input(value):
    original = document()
    changes = patch()["changes"]
    changes[0]["value"] = value
    request = patch(changes)
    before, requested = deepcopy(original), deepcopy(request)
    with pytest.raises(DocumentError) as exc:
        apply_patch(original, request)
    assert exc.value.issues[0]["path"] == "/changes/0/value"
    assert original == before and request == requested


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {1: "bad"}, (1, 2)])
def test_non_json_values_fail_before_semantic_use(value):
    request = patch()
    request["changes"][0]["value"] = value
    with pytest.raises(DocumentError) as exc:
        apply_patch(document(), request)
    assert exc.value.reason_code == "document_invalid_json"


@pytest.mark.parametrize("prop", ["mapping.x", "mappings.series", "axis.scale", "scientific.units", "x", "y"])
def test_presentation_intent_cannot_change_scientific_binding(prop):
    with pytest.raises(DocumentError) as exc:
        apply_patch(document(), patch([{"op": "set", "target": ["series-e2"], "property": prop, "value": "swapped"}]))
    assert exc.value.reason_code == "document_scientific_edit_unsupported"


@pytest.mark.parametrize("overrides,code", [({"base_revision": 3}, "document_revision_conflict"),
                                           ({"plot_id": "plot-other"}, "document_identity_conflict")])
def test_identity_and_revision_guards(overrides, code):
    with pytest.raises(DocumentError) as exc:
        apply_patch(document(), patch(**overrides))
    assert exc.value.reason_code == code


def test_targets_are_exact_immutable_ids_not_labels_or_fuzzy_names():
    request = patch()
    request["changes"][0]["target"] = ["E2"]
    with pytest.raises(DocumentError) as exc:
        apply_patch(document(), request)
    assert exc.value.reason_code == "document_unknown_target"
    assert "series-e2" in exc.value.issues[0]["allowed"]


def test_late_invalid_target_does_not_leak_partially_applied_state():
    original = document()
    request = patch()
    request["changes"][1]["target"] = ["missing"]
    with pytest.raises(DocumentError):
        apply_patch(original, request)
    assert original == document()


def test_duplicate_target_property_is_rejected_instead_of_last_write_wins():
    request = patch()
    request["changes"].append(deepcopy(request["changes"][0]))
    with pytest.raises(DocumentError) as exc:
        apply_patch(document(), request)
    assert exc.value.reason_code == "document_duplicate_change"


def test_engine_raises_risk_for_text_and_extreme_width():
    for identifier, prop, value in [("title-1", "title.text", "New scientific claim"),
                                     ("series-e2", "style.line.width", "1000pt")]:
        _, diff, risk = apply_patch(document(), patch([{"op": "set", "target": [identifier], "property": prop, "value": value}]))
        assert risk == "review" and diff[0]["risk"] == "review"


def test_semantic_color_encoding_requires_scientific_executor():
    value = document()
    value["presentation"]["objects"]["series-e2"]["scientific_role"] = "temperature"
    value = seal_document(value)
    with pytest.raises(DocumentError) as exc:
        apply_patch(value, patch([{"op": "set", "target": ["series-e2"], "property": "style.line.color", "value": "red"}]))
    assert exc.value.reason_code == "document_scientific_edit_unsupported"


def test_capabilities_cannot_downgrade_registry_risk_or_add_native_paths():
    value = document()
    value["presentation"]["objects"]["title-1"]["capabilities"]["title.text"]["risk"] = "presentation"
    with pytest.raises(DocumentError) as exc:
        seal_document(value)
    assert exc.value.reason_code == "document_invalid_capability"
    value = document()
    value["presentation"]["objects"]["series-e2"]["capabilities"]["style.line.width"]["native_path"] = "/page1/graph1/E2"
    with pytest.raises(DocumentError):
        seal_document(value)


def test_noop_preserves_revision_hashes_and_emits_no_diff():
    before, _, _ = apply_patch(document(), patch())
    after, diff, risk = apply_patch(before, patch())
    assert after == before and diff == [] and risk == "presentation"


def graph():
    def node(name, kind, dependencies, **extras):
        return {"id": name, "kind": kind, "dependencies": dependencies, "parameters": {}, "version": "1", **extras}
    return {"kind": "sciplot_dependency_graph", "schema_version": 1, "nodes": [
        node("source", "source", [], content_hash="a" * 64), node("fit", "fit", ["source"]),
        node("style", "compile", [], content_hash="b" * 64), node("render", "render", ["fit", "style"]),
        node("export", "export", ["render"]),
    ]}


def test_style_invalidation_never_recomputes_source_or_fit():
    assert invalidated_nodes(graph(), ["style"]) == ["style", "render", "export"]
    assert invalidated_nodes(graph(), ["source"]) == ["source", "fit", "render", "export"]
    original = build_keys(graph())
    changed = graph()
    changed["nodes"][2]["content_hash"] = "c" * 64
    updated = build_keys(changed)
    assert [key for key in original if original[key] != updated[key]] == ["style", "render", "export"]


@pytest.mark.parametrize("mutation,code", [
    (lambda nodes: nodes[1]["dependencies"].append("export"), "document_dependency_cycle"),
    (lambda nodes: nodes[1]["dependencies"].append("missing"), "document_dependency_missing"),
    (lambda nodes: nodes.append(deepcopy(nodes[0])), "document_dependency_duplicate"),
    (lambda nodes: nodes[0].pop("content_hash"), "document_dependency_source"),
])
def test_dependency_failures_are_explicit(mutation, code):
    value = graph()
    mutation(value["nodes"])
    with pytest.raises(DocumentError) as exc:
        build_keys(value)
    assert exc.value.reason_code == code


def test_versions_dpi_and_fonts_are_part_of_build_keys():
    kwargs = {"scientific_hash": "a" * 64, "presentation_hash": "b" * 64,
              "backend_versions": {"veusz": "3", "compiler": "1"}, "export_configuration": {"dpi": 600},
              "fonts": {"Arial": "font-file-hash"}}
    original = artifact_build_key(**kwargs)
    for field, value in [("backend_versions", {"veusz": "4"}), ("export_configuration", {"dpi": 300}),
                         ("fonts", {"Arial": "replacement-font"})]:
        assert artifact_build_key(**{**kwargs, field: value}) != original


def template_binding():
    presentation = document()["presentation"]
    template = {"kind": "sciplot_template", "schema_version": 1, "template_id": "two-curves",
                "presentation": presentation, "series_slots": ["series-e2", "series-e4"]}
    binding = {"kind": "sciplot_binding", "schema_version": 1, "template_id": "two-curves",
               "data_sources": [{"source_id": "raw", "sha256": "a" * 64, "path": "/raw.csv"}],
               "slots": {name: {"series_id": "bound-" + name, "sample": name,
                                "x": {"source_id": "raw", "column": "Time"},
                                "y": {"source_id": "raw", "column": name}, "x_unit": "s", "y_unit": "Pa"}
                         for name in template["series_slots"]}, "transforms": [], "guards": {}, "provenance": {}}
    return template, binding


def test_template_separates_explicit_source_binding_from_theme():
    template, binding = template_binding()
    original_template, original_binding = deepcopy(template), deepcopy(binding)
    document_a = instantiate_template(template, binding, plot_id="new-plot")
    theme = {"kind": "sciplot_theme", "schema_version": 1, "theme_id": "thin",
             "rules": [{"target": ["bound-series-e2", "bound-series-e4"], "property": "style.line.width", "value": "0.7pt"}]}
    document_b = instantiate_template(template, binding, plot_id="new-plot", theme=theme)
    assert document_a["scientific_hash"] == document_b["scientific_hash"]
    assert document_a["presentation_hash"] != document_b["presentation_hash"]
    assert document_b["scientific"]["mappings"]["bound-series-e2"]["y"]["column"] == "series-e2"
    assert template == original_template and binding == original_binding


def test_template_never_guesses_missing_bindings_or_scientific_changes():
    template, binding = template_binding()
    del binding["slots"]["series-e4"]
    with pytest.raises(DocumentError) as exc:
        instantiate_template(template, binding, plot_id="new-plot")
    assert exc.value.reason_code == "document_binding_mismatch"
    template, binding = template_binding()
    theme = {"kind": "sciplot_theme", "schema_version": 1, "theme_id": "claim",
             "rules": [{"target": ["title-1"], "property": "title.text", "value": "Different conclusion"}]}
    with pytest.raises(DocumentError) as exc:
        instantiate_template(template, binding, plot_id="new-plot", theme=theme)
    assert exc.value.reason_code == "document_theme_review_required"


def test_template_series_all_require_explicit_slots():
    template, _ = template_binding()
    template["series_slots"] = []
    with pytest.raises(DocumentError):
        validate_template(template)


def test_public_schema_is_a_snapshot_not_mutable_validation_authority():
    schema = document_schema()
    schema["properties"]["plot_id"]["pattern"] = ".*"
    value = document()
    value["plot_id"] = "spaces cannot become an id"
    with pytest.raises(DocumentError):
        validate_document(value)


def test_physical_size_whitespace_is_canonical_but_units_and_numeric_lexeme_preserved():
    value = document()
    changes = [{"op": "set", "target": ["series-e2"], "property": "style.line.width", "value": " 1 pt "}]
    unchanged, diff, _ = apply_patch(value, patch(changes))
    assert unchanged == value and diff == []
    changes[0]["value"] = " .70 mm "
    changed, diff, _ = apply_patch(value, patch(changes))
    assert changed["presentation"]["objects"]["series-e2"]["properties"]["style.line.width"] == ".70mm"
    assert diff[0]["after"] == ".70mm" and changes[0]["value"] == " .70 mm "


def test_unchanged_semantic_color_is_a_noop_but_changed_color_stays_protected():
    value = document()
    value["presentation"]["objects"]["series-e2"]["scientific_role"] = "temperature"
    value = seal_document(value)
    changes = [{"op": "set", "target": ["series-e2"], "property": "style.line.color", "value": "black"}]
    unchanged, diff, risk = apply_patch(value, patch(changes))
    assert unchanged == value and not diff and risk == "presentation"


@pytest.mark.parametrize("text", ["", "   ", "x" * 501])
def test_backend_advertised_text_bounds_fail_before_native_work(text):
    value = document()
    value["presentation"]["objects"]["title-1"]["capabilities"]["title.text"].update(
        min_length=1, max_length=500, non_blank=True)
    value = seal_document(value)
    with pytest.raises(DocumentError) as exc:
        apply_patch(value, patch([{"op": "set", "target": ["title-1"], "property": "title.text", "value": text}]))
    assert exc.value.issues[0]["max_length"] == 500


def test_axis_direction_is_preserved_as_immutable_capability():
    value = document()
    value["presentation"]["objects"]["axis:ppm"] = {"kind": "axis", "label": "ppm",
        "properties": {"axis.limits": [12, 0]},
        "capabilities": {"axis.limits": {"type": "number_pair", "risk": "review", "direction": "descending"}}}
    value = seal_document(value)
    changes = [{"op": "set", "target": ["axis:ppm"], "property": "axis.limits", "value": [10, 1]}]
    changed, _, risk = apply_patch(value, patch(changes))
    assert risk == "review" and changed["scientific_hash"] == value["scientific_hash"]
    changes[0]["value"] = [1, 10]
    with pytest.raises(DocumentError) as exc:
        apply_patch(value, patch(changes))
    assert exc.value.issues[0]["direction"] == "descending"


def test_annotation_positions_keep_relative_and_axes_modes_and_units_separate():
    value = document()
    obj = {"kind": "annotation", "label": "Peak note", "properties": {"annotation.position": [8, 100]},
        "capabilities": {"annotation.position": {"type": "number_pair", "risk": "review",
            "coordinate_mode": "axes", "units": {"x": "ppm", "y": "a.u."}}}}
    value["presentation"]["objects"]["note:peak"] = obj
    value = seal_document(value)
    changes = [{"op": "set", "target": ["note:peak"], "property": "annotation.position", "value": [7, 200]}]
    changed, _, _ = apply_patch(value, patch(changes))
    assert changed["presentation"]["objects"]["note:peak"]["capabilities"] == obj["capabilities"]
    invalid = deepcopy(value)
    del invalid["presentation"]["objects"]["note:peak"]["capabilities"]["annotation.position"]["units"]
    with pytest.raises(DocumentError, match="explicit units"):
        seal_document(invalid)
    relative = deepcopy(value)
    relative["presentation"]["objects"]["note:peak"]["properties"]["annotation.position"] = [0.4, 0.8]
    relative["presentation"]["objects"]["note:peak"]["capabilities"]["annotation.position"] = {
        "type": "number_pair", "risk": "review", "coordinate_mode": "relative"}
    with pytest.raises(DocumentError):
        apply_patch(seal_document(relative), patch(changes))
