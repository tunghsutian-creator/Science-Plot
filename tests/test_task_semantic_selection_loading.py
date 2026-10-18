"""Explicit generic blocks constrain numeric loading and sample lineage first."""
from copy import deepcopy
import hashlib

import pytest


def source_with_excluded_poison(tmp_path, poison):
    source = tmp_path / "mixed-original.csv"
    first_header = "Mass (Pa)" if poison == "unit" else "Mass"
    rows = [f"Time,{first_header},,Time,Mass,Status", "s,%,,s,%,",
            "Foreign,Foreign,,Selected,Selected,Foreign",
            "0,100,,0,80," + ("READY" if poison == "column" else "7"),
            "1,99,,1,79," + ("READY" if poison == "column" else "8"),
            "2,98,," + ("not-selected,not-selected," if poison == "row" else ",,")]
    source.write_text("\n".join(rows) + "\n")
    return source


def request_state(source, tmp_path, *, selected=True):
    from sciplot_core.task_semantic_plan import prepare_plan

    intent = {"x": {"quantity": "time", "unit": "s"}, "y": {"quantity": "mass", "unit": "%"}}
    if selected:
        intent["selection"] = {"blocks": [{"source_id": "source:0", "table_id": "table:0", "block_id": "block:1"}]}
    else:
        intent["stages"] = {"mode": "concatenate", "order": "source_order", "boundary": "preserve_endpoint"}
    return {"request": {"intent": intent}, "semantic_plan": prepare_plan([source], intent),
            "semantic_choices": {}, "intent_revision": 1, "task_dir": str(tmp_path / "task")}


@pytest.mark.parametrize("poison", ["column", "row", "unit", "sample"])
def test_explicit_generic_selection_binds_rows_columns_and_sample_before_load(tmp_path, monkeypatch, poison):
    from sciplot_core.plot_engine import managed_sources
    from sciplot_core.plot_engine.contracts import validate_create
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms
    from sciplot_core.task_semantic_figure import build_request

    source = source_with_excluded_poison(tmp_path, poison)
    original = source.read_bytes()
    current = request_state(source, tmp_path)
    selection_before = deepcopy(current["semantic_plan"]["selection"])
    calls = []
    original_loader = managed_sources.load_sources

    def bounded_loader(document, rule_id):
        scientific = document["scientific"]
        assert len(scientific["data_sources"]) == 1
        bound = scientific["data_sources"][0]
        assert bound["table_selection"]["data_start_row"] == 3
        assert bound["table_selection"]["data_end_row"] == 5
        consumers = [node for node in scientific["transforms"] if bound["source_id"] in node["inputs"]]
        assert len(consumers) == 1 and consumers[0]["kind"] == "select"
        assert consumers[0]["parameters"]["columns"] == ["column:3", "column:4"]
        result = original_loader(document, rule_id)
        assert set(result[bound["source_id"]]["columns"]) == {"column:3", "column:4"}
        assert result[bound["source_id"]]["provenance"]["sources"][0]["rows"] == [3, 4]
        calls.append(deepcopy(document))
        return result

    monkeypatch.setattr(managed_sources, "load_sources", bounded_loader)
    wire = validate_create(build_request(current))
    assert len(calls) == 1
    assert {slot["sample"] for slot in wire["data_binding"]["slots"].values()} == {"Selected"}
    assert wire["data_binding"]["data_sources"][0]["sha256"] == hashlib.sha256(original).hexdigest()
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="selected")
    resolved = resolve_transforms(document, bounded_loader(document, "tga_curve"))
    layer = wire["template_definition"]["figure_spec"]["views"][0]["layers"][0]
    dataset = resolved["datasets"][layer["dataset_id"]]
    assert dataset["columns"]["x"]["values"] == [0, 1]
    assert dataset["columns"]["y"]["values"] == [80, 79]
    assert current["semantic_plan"]["selection"]["excluded"][0]["block_id"] == "block:0"
    assert current["semantic_plan"]["selection"] == selection_before
    assert source.read_bytes() == original


def test_omitted_selection_retains_original_generic_binding_identity(tmp_path):
    from sciplot_core.task_semantic_figure import build_request

    source = tmp_path / "compatible.csv"
    source.write_text("Time,Mass,,Time,Mass\ns,%,,s,%\nSame,Same,,Same,Same\n0,100,,0,80\n1,99,,1,79\n")
    current = request_state(source, tmp_path, selected=False)
    wire = build_request(current)
    assert [item["source_id"] for item in wire["data_binding"]["data_sources"]] == ["source:0"]
    assert wire["data_binding"]["data_sources"][0]["table_selection"] == current["semantic_plan"]["sources"][0]["candidates"][0]["table_selection"]
    assert sum(node["kind"] == "row_slice" for node in wire["data_binding"]["transforms"]) == 2


def test_explicit_reset_stages_each_load_only_their_selected_original_region(tmp_path, monkeypatch):
    from sciplot_core.plot_engine import managed_sources
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms
    from sciplot_core.task_semantic_figure import build_request
    from sciplot_core.task_semantic_plan import prepare_plan

    source = tmp_path / "reset-stages.csv"
    source.write_text("Time,Mass,,Time,Mass,Status\ns,%,,s,%,\nOther,Other,,Chosen,Chosen,Other\n"
                      "0,100,,0,80,ready\n1,99,,1,79,ready\n2,98,,0,78,ready\n3,97,,1,77,ready\n"
                      "4,96,,excluded,excluded,ready\n")
    original = source.read_bytes()
    value = {"x": {"quantity": "time", "unit": "s"}, "y": {"quantity": "mass", "unit": "%"},
             "selection": {"blocks": [{"source_id": "source:0", "table_id": "table:0", "block_id": "block:1"}]},
             "stages": {"mode": "concatenate", "order": "source_order", "boundary": "preserve_endpoint"}}
    current = {"request": {"intent": value}, "semantic_plan": prepare_plan([source], value),
               "semantic_choices": {}, "intent_revision": 1, "task_dir": str(tmp_path / "task")}
    calls = []
    loader = managed_sources.load_sources

    def bounded(document, rule_id):
        for binding in document["scientific"]["data_sources"]:
            region = binding["table_selection"]
            calls.append((binding["source_id"], region["data_start_row"], region["data_end_row"]))
            assert (region["data_start_row"], region["data_end_row"]) in {(3, 5), (5, 7)}
        result = loader(document, rule_id)
        assert all(set(dataset["columns"]) == {"column:3", "column:4"} for dataset in result.values())
        return result

    monkeypatch.setattr(managed_sources, "load_sources", bounded)
    wire = build_request(current)
    assert [(start, end) for _identifier, start, end in calls] == [(3, 5), (5, 7)]
    assert len({identifier for identifier, _start, _end in calls}) == 2
    assert not any(node["kind"] == "row_slice" for node in wire["data_binding"]["transforms"])
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="stages")
    resolved = resolve_transforms(document, bounded(document, "tga_curve"))
    dataset_id = wire["data_binding"]["slots"]["layer:response:0"]["x"]["source_id"]
    dataset = resolved["datasets"][dataset_id]
    assert dataset["columns"]["x"]["values"] == [0, 1, 1, 2]
    assert dataset["columns"]["y"]["values"] == [80, 79, 78, 77]
    assert {slot["sample"] for slot in wire["data_binding"]["slots"].values()} == {"Chosen"}
    assert source.read_bytes() == original
