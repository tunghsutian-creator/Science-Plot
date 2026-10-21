"""Actual builder stage references bind Celsius facts to exact physical subdomains."""

from copy import deepcopy
import json

import pytest
from test_current_unit_admission import managed
from test_task_semantic_resolution import state

from sciplot_core.plot_document import seal_document
from sciplot_core.plot_engine.current_unit_admission import admit_current_units
from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_engine.original_coordinate import coordinate_origins
from sciplot_core.task_semantic_creation import build_managed_request
from sciplot_core.plot_transforms import resolve_transforms


def test_actual_multistage_c_binding_reopens_with_explicit_stage_source_references(tmp_path):
    source = tmp_path / "sensor-stages.csv"
    source.write_text("Time,sensor_C\ns,C\n0,20\n1,30\n0,10\n1,20\n")
    before = source.read_bytes()
    intent = {"x": {"quantity": "time", "unit": "s"},
              "y": {"quantity": "temperature", "header": "sensor_C", "unit": "K"},
              "stages": {"mode": "concatenate", "order": "source_order", "boundary": "preserve_endpoint"},
              "selection": {"blocks": [{"source_id": "source:0", "table_id": "table:0", "block_id": "block:0"}]}}
    task = state(source, intent, tmp_path)
    wire = build_managed_request(task)
    document = managed(wire)
    saved = tmp_path / "created.json"
    saved.write_text(json.dumps(document))
    reopened = json.loads(saved.read_text())
    semantic = reopened["scientific"]["provenance"]["binding"]["semantic_task"]
    stages = [stage for values in semantic["stages"].values() for stage in values]
    sources = reopened["scientific"]["data_sources"]
    assert len(sources) == len(stages) == 2
    assert {stage["source_id"] for stage in stages} == {item["source_id"] for item in sources}
    assert [(item["table_selection"]["data_start_row"], item["table_selection"]["data_end_row"]) for item in sources] == [(2, 4), (4, 6)]
    assert all(stage["table_selection"]["data_start_row"] == 2 and stage["table_selection"]["data_end_row"] == 6 for stage in stages)
    admit_current_units(tmp_path, reopened)
    datasets = load_sources(reopened, wire["rule_id"])
    result = resolve_transforms(reopened, datasets)
    layer = wire["template_definition"]["figure_spec"]["views"][0]["layers"][0]
    columns = result["datasets"][layer["dataset_id"]]["columns"]
    assert columns["x"]["values"] == [0.0, 1.0, 1.0, 2.0]
    assert columns["y"]["values"] == [293.15, 303.15, 283.15, 293.15]
    assert [row for item in sources for row in range(item["table_selection"]["data_start_row"], item["table_selection"]["data_end_row"])] == [2, 3, 4, 5]
    assert source.read_bytes() == before and reopened == document
    # A numeric subset and a similar stage ID alone must not authorize Celsius.
    # Inspect an unmapped conversion so public mapping facts cannot mask the
    # absence of the frozen stage-to-source reference being tested.
    stale = deepcopy(reopened)
    first = stale["scientific"]["transforms"]
    convert = next(node for node in first if node["kind"] == "convert_unit")
    recorded = stale["scientific"]["provenance"]["binding"]["semantic_task"]["stages"]
    for entries in recorded.values():
        for stage in entries:
            stage["source_id"] = "a:similar:but:unbound:stage"
    with pytest.raises(ValueError) as error:
        coordinate_origins(seal_document(stale), convert["output"], "y", "K", datasets=datasets)
    assert error.value.reason_code == "transform_unit_incompatible"
    for corruption in ("outside_full_block", "wrong_point_count", "boolean_point_count"):
        invalid = deepcopy(reopened)
        context = invalid["scientific"]["provenance"]["binding"]["semantic_task"]
        if corruption == "outside_full_block":
            # The actual source child and numeric data are unchanged. Forge a
            # narrower parent block which no longer contains that child, while
            # keeping the stage's copied full-block metadata self-consistent.
            for binding in context["resolution"]["bindings"]:
                binding["table_selection"]["data_start_row"] = 3
            for entries in context["stages"].values():
                for stage in entries:
                    stage["table_selection"]["data_start_row"] = 3
        else:
            for entries in context["stages"].values():
                for stage in entries:
                    stage["point_count"] = stage["point_count"] + 1 if corruption == "wrong_point_count" else True
        with pytest.raises(ValueError) as rejected:
            coordinate_origins(seal_document(invalid), convert["output"], "y", "K", datasets=datasets)
        assert rejected.value.reason_code == "transform_unit_incompatible", corruption
