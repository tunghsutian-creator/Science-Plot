"""Confirmed source regions own slots; finite coordinates only describe points."""
from copy import deepcopy
import csv
from io import StringIO

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.managed_resolution import resolved_metadata, resolve_science
from sciplot_core.plot_engine.managed_state import resolved_ir
from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_transforms import builtin_executor
from sciplot_core.task_semantic_curve_bindings import bound_views
from sciplot_core.task_semantic_figure import _source_views, build_request
from sciplot_core.task_semantic_plan import selected_table_plan


def confirmed_pairs(tmp_path, *, missing_pair=False, end=9):
    """A user-confirmed table window, including an explicit all-missing record.

    This fixture supplies the existing confirmed-plan contract directly. It does
    not ask finite extents to discover a domain or infer that blank EOF is data.
    """
    rows = [["80", "0.12345678901234567", "80", "1.0000000000000002"],
            ["80", "0.10000000000000002", "", "2.3400000000000003"],
            ["75", "", "", "3.0"], ["70", "0.2", "", ""],
            ["", "0.3", "", ""], ["", "", "", ""]]
    if missing_pair:
        rows = [row[:2] + ["", ""] for row in rows]
    source = tmp_path / "confirmed.csv"
    stream = StringIO()
    writer = csv.writer(stream)
    writer.writerows([["Temperature", "Storage Modulus", "Temperature", "Loss Modulus"],
                     ["Amber"] * 4, ["C", "Pa", "C", "Pa"], *rows])
    source.write_text(stream.getvalue())
    region = {"sheet": None, "header_rows": [0], "sample_row": 1, "unit_row": 2,
              "data_start_row": 3, "data_end_row": end}
    columns = []
    for index, (header, quantity, unit) in enumerate([
        ("Temperature", "temperature", "C"), ("Storage Modulus", "storage_modulus", "Pa"),
        ("Temperature", "temperature", "C"), ("Loss Modulus", "loss_modulus", "Pa"),
    ]):
        present = [3 + row for row, values in enumerate(rows[:end - 3]) if values[index]]
        columns.append({"column_id": f"column:{index}", "column_index": index,
                        "header": header, "quantity": quantity, "unit": unit,
                        "numeric": {"point_count": len(present), "first_row": min(present) if present else None,
                                    "data_end_row": max(present) + 1 if present else None}})
    block = {"block_id": "block:0", "order": 0, "columns": columns, "column_indices": list(range(4)),
             "sample": "Amber", "label": "Amber", "table_selection": deepcopy(region),
             "data_start_row": 3, "data_end_row": end, "response_columns": ["column:1", "column:3"]}
    stage = {"stage_id": "block:0:segment:0", "block_id": "block:0", "data_start_row": 3,
             "data_end_row": end, "point_count": end - 3, "temperature_endpoints": {}}
    candidate = {"candidate_id": "table:0", "sheet": None, "format": "sample_column_blocks",
                 "table_selection": region, "columns": columns, "blocks": [block], "stages": [stage]}
    sources = [{"source_id": "source:0", "path": str(source), "sha256": file_sha256(source), "candidates": [candidate]}]
    intent = {"x": {"quantity": "temperature", "scale": "linear"},
              "y": {"quantity": "modulus", "quantity_members": ["storage_modulus", "loss_modulus"], "scale": "linear"},
              "curve_bindings": [{"source_id": "source:0", "table_id": "table:0", "block_id": "block:0",
                                  "x_column_id": f"column:{pair * 2}", "y_column_id": f"column:{pair * 2 + 1}",
                                  "y_quantity": quantity} for pair, quantity in enumerate(["storage_modulus", "loss_modulus"])]}
    return source, sources, intent


def exact(values):
    return [None if value is None else float(value).hex() for value in values]


def confirmed_state(tmp_path, sources, intent):
    # Resolve the already confirmed physical region; never reinspect the source
    # or ask the lowerer to infer a missing scientific plan.
    plan = selected_table_plan({"sources": sources, "intent": intent}, intent, {})
    assert plan["decisions"] == []
    return {"request": {"intent": intent}, "semantic_plan": plan, "semantic_choices": {},
            "intent_revision": 1, "task_dir": str(tmp_path / "task")}


@pytest.mark.parametrize("explicit_rule", [False, True])
@pytest.mark.parametrize("missing_pair", [False, True])
def test_pair_binding_preserves_confirmed_region_without_finite_end_reinterpretation(tmp_path, explicit_rule, missing_pair):
    _, sources, intent = confirmed_pairs(tmp_path, missing_pair=missing_pair)
    if explicit_rule:
        intent["rule_id"] = "ordinary_xy"
    original = deepcopy(sources)
    views = bound_views(sources, intent)
    for _, view in views:
        assert view["table_selection"] == sources[0]["candidates"][0]["table_selection"]
        assert view["blocks"][0]["data_end_row"] == 9
        assert view["stages"][0]["data_end_row"] == 9
        assert view["stages"][0]["point_count"] == 6  # source slots, not finite XY pairs
    assert sources == original


@pytest.mark.parametrize("end", [7, 9])
def test_confirmed_source_cells_match_raw_and_resolved_ir_rows_masks_and_finite_bits(tmp_path, end):
    source, sources, intent = confirmed_pairs(tmp_path, end=end)
    original = source.read_bytes()
    expected_rows = list(csv.reader(StringIO(original.decode())))[3:end]
    expected = [[float(row[column]) if row[column] else None for row in expected_rows] for column in range(4)]
    wire = build_request(confirmed_state(tmp_path, sources, intent))
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="source-region")
    document = resolved_metadata(document, rule_id="ordinary_xy", executors={})
    document, _ = resolve_science(tmp_path / "store", document)
    ir = resolved_ir(tmp_path / "store", document)
    layers = ir["views"][0]["layers"]
    for pair, (binding, layer) in enumerate(zip(document["scientific"]["data_sources"], layers, strict=True)):
        raw = ir["datasets"][binding["source_id"]]
        derived = ir["datasets"][layer["dataset_id"]]
        for role, column in (("x", pair * 2), ("y", pair * 2 + 1)):
            assert exact(raw["columns"][f"column:{column}"]["values"]) == exact(expected[column])
            assert exact(derived["columns"][role]["values"]) == exact(expected[column])
        evidence = raw["provenance"]["sources"][0]
        assert evidence["rows"] == list(range(3, end))
        assert evidence["table_selection"] == binding["table_selection"]
        assert evidence["sha256"] == file_sha256(source)
        assert len(derived["columns"]["x"]["values"]) == end - 3
    finite_pairs = [sum(x is not None and y is not None for x, y in zip(expected[pair * 2], expected[pair * 2 + 1], strict=True))
                    for pair in range(2)]
    assert finite_pairs == [3, 1]
    # A saved explicit shorter selection remains shorter on a later resolution.
    reopened, _ = resolve_science(tmp_path / "store", document)
    assert resolved_ir(tmp_path / "store", reopened) == ir
    assert source.read_bytes() == original


def test_all_missing_selected_pair_retains_source_slots_but_cannot_claim_visible_measurements(tmp_path):
    source, sources, intent = confirmed_pairs(tmp_path, missing_pair=True)
    candidate = sources[0]["candidates"][0]
    binding = {key: sources[0][key] for key in ("source_id", "path", "sha256")}
    binding["table_selection"] = candidate["table_selection"]
    select = {"id": "select", "kind": "select", "inputs": [binding["source_id"]], "output": "selected",
              "parameters": {"columns": ["column:2", "column:3"]},
              "executor": builtin_executor(), "determinism": "deterministic"}
    raw = load_sources({"scientific": {"data_sources": [binding], "mappings": {}, "transforms": [select]}}, "ordinary_xy")
    dataset = raw[binding["source_id"]]
    assert dataset["provenance"]["sources"][0]["rows"] == list(range(3, 9))
    assert {name: column["values"] for name, column in dataset["columns"].items()} == {
        "column:2": [None] * 6, "column:3": [None] * 6}
    assert file_sha256(source) == binding["sha256"]
    with pytest.raises(ValueError) as rejected:
        build_request(confirmed_state(tmp_path, sources, intent))
    assert rejected.value.reason_code == "figure_empty_visible_layer"


def test_append_keeps_independent_confirmed_ranges_and_missing_slots(tmp_path):
    before_root, after_root = tmp_path / "first", tmp_path / "second"
    before_root.mkdir()
    after_root.mkdir()
    _, sources, intent = confirmed_pairs(before_root, end=7)
    second, appended_sources, _ = confirmed_pairs(after_root)
    wire = build_request(confirmed_state(tmp_path, sources, intent))
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="independent-regions")
    document = resolved_metadata(document, rule_id="ordinary_xy", executors={})
    document, _ = resolve_science(tmp_path / "store", document)
    before = resolved_ir(tmp_path / "store", document)
    region = appended_sources[0]["candidates"][0]["table_selection"]
    request = {"plot_id": document["plot_id"], "base_revision": document["revision"], "idempotency_key": "append-region",
               "intent_class": "scientific", "changes": [{"op": "set", "target": ["view:main"], "property": "source.append",
                   "value": {"source": {"source_id": "raw:appended", "path": str(second), "sha256": file_sha256(second),
                                        "table_selection": region},
                             "curves": [{"sample": "Amber", "x_column_index": 0, "y_column_index": 1,
                                         "y_quantity": "storage_modulus", "label": "Next"}]}}]}
    changed, _, _, execute = prepare_update(document, request)
    assert execute
    changed, _ = resolve_science(tmp_path / "store", changed)
    after = resolved_ir(tmp_path / "store", changed)
    assert all(after["datasets"][name] == dataset for name, dataset in before["datasets"].items())
    raw = after["datasets"]["raw:appended"]
    assert raw["provenance"]["sources"][0]["rows"] == list(range(3, 9))
    assert raw["columns"]["column:0"]["values"] == [80., 80., 75., 70., None, None]
    assert exact(raw["columns"]["column:1"]["values"]) == exact([
        float("0.12345678901234567"), float("0.10000000000000002"), None, .2, .3, None])
    assert [len(after["datasets"][layer["dataset_id"]]["columns"][layer["mappings"]["x"]]["values"])
            for layer in after["views"][0]["layers"]] == [4, 4, 6]


def instrument_views(tmp_path, tag, *, distinct_tests=False):
    _, sources, _ = confirmed_pairs(tmp_path)
    candidate = sources[0]["candidates"][0]
    candidate["format"] = tag
    first = candidate["blocks"][0]
    first.update(test_row=0, source_interval={"interval": 1}, result="First observed result")
    second = {**deepcopy(first), "block_id": "block:1", "order": 1, "data_start_row": 12, "data_end_row": 15,
              "table_selection": {**first["table_selection"], "data_start_row": 12, "data_end_row": 15},
              "label": "Amber · second result", "source_interval": {"interval": 2}, "result": "Second observed result"}
    if distinct_tests:
        second["test_row"] = 10
    candidate["blocks"].append(second)
    candidate["stages"].append({"stage_id": "block:1:segment:0", "block_id": "block:1",
                                "data_start_row": 12, "data_end_row": 15, "point_count": 3, "temperature_endpoints": {}})
    return sources


@pytest.mark.parametrize("tag", ["instrument_intervals", "rheology_frequency_intervals"])
def test_instrument_layout_defaults_to_independent_physical_blocks_even_with_same_sample(tmp_path, tag):
    sources = instrument_views(tmp_path, tag)
    original = deepcopy(sources)
    views = _source_views(sources, {}, {"x": {"quantity": "temperature"}, "y": {"quantity": "storage_modulus"}})
    assert len(views) == 2
    assert len({source["source_id"] for source, _ in views}) == 2
    for index, (_, view) in enumerate(views):
        block = original[0]["candidates"][0]["blocks"][index]
        assert view["sample_view"] is True
        assert view["blocks"] == [block]
        assert view["table_selection"] == block["table_selection"]
        assert [stage["block_id"] for stage in view["stages"]] == [block["block_id"]]
    assert sources == original


@pytest.mark.parametrize("confirmed_choice", [False, True])
def test_only_explicit_time_stage_assembly_keeps_instrument_blocks_together(tmp_path, confirmed_choice):
    sources = instrument_views(tmp_path, "instrument_intervals")
    intent = {"x": {"quantity": "time"}, "y": {"quantity": "storage_modulus"}}
    choices = {"stage_mode": "concatenate"} if confirmed_choice else {}
    if not confirmed_choice:
        intent["stages"] = {"mode": "concatenate"}
    views = _source_views(sources, choices, intent)
    assert len(views) == 1 and views[0][1]["sample_view"] is True
    assert views[0][1]["blocks"] == sources[0]["candidates"][0]["blocks"]
    assert views[0][1]["stages"] == sources[0]["candidates"][0]["stages"]


def test_explicit_stage_authorization_preserves_selected_test_identity_and_order(tmp_path):
    sources = instrument_views(tmp_path, "instrument_intervals", distinct_tests=True)
    intent = {"x": {"quantity": "time"}, "y": {"quantity": "storage_modulus"},
              "stages": {"mode": "concatenate", "order": "source_order"},
              "selection": {"blocks": [{"source_id": "source:0", "table_id": "table:0", "block_id": f"block:{index}"}
                                       for index in range(2)]}}
    views = _source_views(sources, {}, intent)
    assert len(views) == 1
    assert [block["test_row"] for block in views[0][1]["blocks"]] == [0, 10]
    assert views[0][1]["stages"] == sources[0]["candidates"][0]["stages"]
