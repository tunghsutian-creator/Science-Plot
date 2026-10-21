"""Actual semantic creation and saved current-view edits share one range writer."""
from copy import deepcopy
import json

import pytest

from sciplot_core.plot_engine.content_store import intern_document, resolve_document_content
from sciplot_core.plot_engine.current_unit_admission import prepare_current_update
from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata
from sciplot_core.plot_engine.managed_state import resolved_ir
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_ir.figure_document import figure_spec
from sciplot_core.task_semantic_creation import build_managed_request
from sciplot_core.task_semantic_plan import prepare_plan


def _create(paths, root):
    intent = {"x": {"quantity": "time", "header": "Time_s", "unit": "s"},
              "y": {"quantity": "temperature", "header": "Temperature_C", "unit": "C"}}
    state = {"task_dir": str(root / "task"), "request": {"intent": intent}, "intent_revision": 1,
             "semantic_plan": prepare_plan(paths, intent), "semantic_choices": {}}
    request = build_managed_request(state)
    document = create_managed_document(request["template_definition"], request["data_binding"], plot_id="same-final-science")
    document = resolved_metadata(document, rule_id=request["rule_id"], executors={})
    return resolve_science(root, document)[0]


def _patch(document, changes, *, scientific=False):
    return {"plot_id": document["plot_id"], "base_revision": document["revision"],
            "idempotency_key": "literal-current-edit", "intent_class": "scientific" if scientific else "presentation",
            "changes": [{"op": "set", "target": [target], "property": prop, "value": value}
                        for target, prop, value in changes]}


def _sources(tmp_path):
    a, b = tmp_path / "A.csv", tmp_path / "B.csv"
    a.write_text("Time_s,Temperature_C\n1,10\n2,12\n3,14\n")
    b.write_text("Time_s,Temperature_C\n10,30\n11,32\n12,34\n")
    return a, b


def _append(document, other):
    source = deepcopy(other["scientific"]["data_sources"][0])
    source["source_id"] = "raw:appended:B"
    return _patch(document, [("view:main", "source.append", {"source": source,
        "curves": [{"sample": "B", "x_column_index": 0, "y_column_index": 1, "label": "B / cooling"}]})], scientific=True)


def _domains(document):
    return {scale["id"]: scale["domain"] for scale in figure_spec(document)["scales"]}


def test_actual_initial_all_append_and_saved_append_have_equivalent_current_bounds(tmp_path):
    a, b = _sources(tmp_path)
    original = {path: path.read_bytes() for path in (a, b)}
    all_at_once = _create([a, b], tmp_path / "all")
    initial = _create([a], tmp_path / "first")
    other = _create([b], tmp_path / "other")
    assert figure_spec(initial)["domain_semantics"] == "current_view_v1"
    candidate, diff, _, execute = prepare_current_update(tmp_path / "first", initial, _append(initial, other))
    assert diff and execute
    assert diff[0]["after"]["preserved_domain_rules"] == {
        axis: {"minimum": {"mode": "auto"}, "maximum": {"mode": "auto"}} for axis in ("x", "y")}
    assert "preserved_scale_domains" not in diff[0]["after"]
    appended = resolve_science(tmp_path / "first", candidate)[0]
    expected = {"scale:x": [1.0, 12.55], "scale:y": [8.8, 35.2]}
    assert _domains(appended) == _domains(all_at_once) == expected

    compact = intern_document(tmp_path / "first", initial, minimum_bytes=2)
    saved = tmp_path / "saved.json"
    saved.write_text(json.dumps(compact))
    reopened = json.loads(saved.read_text())
    candidate, _, _, _ = prepare_current_update(tmp_path / "first", reopened, _append(reopened, other))
    after_reopen = resolve_science(tmp_path / "first", candidate)[0]
    assert _domains(after_reopen) == expected
    # Different control/provenance histories need not have the same whole hash.
    # The literal source arrays, their masks and current window must agree.
    for document, root in ((appended, tmp_path / "first"), (after_reopen, tmp_path / "first")):
        ir = resolved_ir(root, document)
        assert ir["datasets"]["raw:appended:B"]["columns"]["column:0"]["values"] == [10., 11., 12.]
        assert ir["datasets"]["raw:appended:B"]["columns"]["column:1"]["values"] == [30., 32., 34.]
    assert {path: path.read_bytes() for path in (a, b)} == original


def test_saved_auto_fixed_rules_preserve_late_ticks_and_display_through_append_hide_show(tmp_path):
    a, b = _sources(tmp_path)
    root = tmp_path / "store"
    initial = _create([a], root)
    other = _create([b], tmp_path / "other")
    late = _patch(initial, [
        ("scale:y", "scale.domain", {"minimum": {"mode": "auto"}, "maximum": {"mode": "fixed", "value": 50}}),
        ("axis:y", "axis.ticks", [10, 12]),
        ("axis:x", "axis.label", "Elapsed acquisition time"),
        ("layer:response:0", "series.display_label", "Original / alias"),
    ], scientific=True)
    edited = prepare_current_update(root, initial, late)[0]
    edited = intern_document(root, edited, minimum_bytes=2)
    edited = json.loads(json.dumps(edited))
    candidate = prepare_current_update(root, edited, _append(edited, other))[0]
    appended = resolve_science(root, candidate)[0]
    spec = figure_spec(appended)
    assert _domains(appended) == {"scale:x": [1., 12.55], "scale:y": [8.8, 50.]}
    assert spec["views"][0]["axes"][1]["ticks"] == [10, 12]
    assert spec["views"][0]["axes"][0]["label"] == "Elapsed acquisition time"
    assert spec["views"][0]["layers"][0]["label"] == "Original / alias"
    new_layer = spec["views"][0]["layers"][-1]["id"]
    compact = intern_document(root, appended, minimum_bytes=2)
    hidden = prepare_current_update(root, compact, _patch(compact, [(new_layer, "series.visible", False)]))[0]
    assert hidden["scientific_hash"] == compact["scientific_hash"]
    assert _domains(hidden) == {"scale:x": [1., 3.1], "scale:y": [9.8, 50.]}
    shown = prepare_current_update(root, hidden, _patch(hidden, [(new_layer, "series.visible", True)]))[0]
    assert _domains(shown) == _domains(compact)
    assert shown["scientific_hash"] == compact["scientific_hash"]
    assert resolve_document_content(root, shown)["scientific"]["data_sources"] == appended["scientific"]["data_sources"]


def test_fixed_tick_conflict_refuses_without_mutating_saved_science_or_rules(tmp_path):
    a, b = _sources(tmp_path)
    root = tmp_path / "store"
    document = _create([a, b], root)
    edited = prepare_current_update(root, document, _patch(document, [("axis:x", "axis.ticks", [1, 12])]))[0]
    compact = intern_document(root, edited, minimum_bytes=2)
    before = deepcopy(compact)
    with pytest.raises(ValueError) as error:
        prepare_current_update(root, compact, _patch(compact, [("layer:response:1", "series.visible", False)]))
    assert error.value.reason_code == "figure_fixed_ticks_domain_conflict"
    assert compact == before


def test_scoped_current_view_reads_expose_rules_and_their_actual_numeric_projection(tmp_path, monkeypatch):
    from jsonschema import Draft202012Validator
    from test_managed_description_scopes import _service
    from sciplot_core.plot_engine import service as service_module

    owner, root, _ = _service(tmp_path, monkeypatch)
    a, b = _sources(tmp_path)
    document = _create([a, b], tmp_path / "science")
    service_module.load_head(root)["document"] = document
    before = deepcopy(document)
    spec = figure_spec(document)
    summary = owner.describe(root, description={"scope": "summary"})
    assert summary["domain_semantics"] == "current_view_v1"
    for target, prop in (("scale:x", "scale.domain"), ("axis:x", "axis.ticks")):
        edit = owner.describe(root, description={"scope": "edit", "target": target, "property": prop})
        Draft202012Validator(edit["figure_edit_contract"][target][prop]["value_schema"]).validate(edit["current_value"])
        assert edit["domain_semantics"] == "current_view_v1"
        assert edit["target_context"]["domain"] == [1., 12.55]
        if prop == "scale.domain":
            assert edit["current_value"] == {"minimum": {"mode": "auto"}, "maximum": {"mode": "auto"}}
        else:
            assert edit["current_value"] == {"mode": "automatic"}
            assert edit["target_context"]["ticks"] == spec["views"][0]["axes"][0]["ticks"]
    assert document == before
