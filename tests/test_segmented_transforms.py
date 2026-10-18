"""Stage operations retain each original point and explicit time-boundary policy."""
from copy import deepcopy

import pytest

from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_transforms import builtin_executor, execute_node, validate_node


def dataset(identifier="raw", *, times=(0, 1, 0, 1), values=(100, 99, 98, 97), unit="s", rows=None):
    count = len(times)
    return {"id": identifier, "columns": {
        "time": {"label": "Time", "unit": unit, "values": list(times)},
        "signal": {"label": "Mass", "unit": "%", "values": list(values)},
    }, "provenance": {"sources": [{"source_id": identifier, "sha256": "a" * 64,
        "table_selection": {"sheet": None, "header_rows": [0], "data_start_row": 2, "data_end_row": count + 2},
        "column_indices": {"time": 2, "signal": 0}, "rows": list(rows or range(2, count + 2))}], "transforms": []}}


def node(kind, parameters, inputs=("raw",), output="derived"):
    return {"id": output, "kind": kind, "inputs": list(inputs), "output": output,
            "parameters": parameters, "executor": builtin_executor(), "determinism": "deterministic"}


def test_time_reset_segments_are_candidates_with_original_rows_and_no_automatic_order():
    from sciplot_core.source_tables.segmented_series import segment_candidates

    raw = dataset(times=(0, 2, 4, 0, 2, None, 0, 3), values=tuple(range(8)))
    before = deepcopy(raw)
    result = segment_candidates(raw, time_column="time")
    assert [(s["start_index"], s["end_index"]) for s in result["segments"]] == [(0, 3), (3, 5), (6, 8)]
    assert [s["source_rows"] for s in result["segments"]] == [[2, 3, 4], [5, 6], [8, 9]]
    assert result["unassigned_indices"] == [5]
    assert result["questions"][0]["field"] == "stage_order"
    assert "boundary" in {q["field"] for q in result["questions"]}
    assert result["segments"][1]["reason"] == "time_reset"
    assert raw == before


def test_slice_concatenate_and_convert_retains_duplicate_endpoints_and_original_lineage():
    raw = dataset()
    original = deepcopy(raw)
    first, _ = execute_node(node("row_slice", {"start": 0, "end": 2}, output="first"), {"raw": raw})
    second, _ = execute_node(node("row_slice", {"start": 2, "end": 4}, output="second"), {"raw": raw})
    joined, key = execute_node(node("concat_time", {"time_column": "time", "boundary": "preserve_endpoint", "first_origin": "zero"}, ("first", "second")), {"first": first, "second": second})
    assert joined["columns"]["time"]["values"] == [0, 1, 1, 2]
    assert joined["columns"]["signal"]["values"] == [100, 99, 98, 97]
    details = joined["provenance"]["transforms"][-1]["details"]
    assert details["offsets"] == [0, 1]
    assert [r[0]["row"] for r in details["row_origins"]] == [2, 3, 4, 5]
    assert details["input_point_counts"] == [2, 2]
    converted, other_key = execute_node(node("convert_unit", {"columns": ["time"], "from_unit": "s", "to_unit": "min"}, ("derived",), "minutes"), {"derived": joined})
    assert converted["columns"]["time"]["values"] == [0, 1 / 60, 1 / 60, 2 / 60]
    assert converted["columns"]["time"]["unit"] == "min"
    assert converted["columns"]["signal"] == raw["columns"]["signal"]
    assert other_key != key
    assert raw == original
    assert len(joined["provenance"]["sources"]) == 1


def test_alternate_column_layout_and_next_sample_policy_do_not_depend_on_task_fixture():
    first = dataset("up", times=(4, 6, 8), values=(3, 1, 2), unit="min")
    second = dataset("down", times=(7, 10), values=(2, 5), unit="min")
    joined, _ = execute_node(node("concat_time", {"time_column": "time", "boundary": "next_sample", "first_origin": "preserve"}, ("up", "down")), {"up": first, "down": second})
    assert joined["columns"]["time"]["values"] == [4, 6, 8, 11, 14]
    assert joined["columns"]["signal"]["values"] == [3, 1, 2, 2, 5]
    assert {row[0]["source_id"] for row in joined["provenance"]["transforms"][-1]["details"]["row_origins"]} == {"up", "down"}


@pytest.mark.parametrize("kind,parameters", [
    ("row_slice", {"start": 1, "end": 1}),
    ("row_slice", {"start": 0, "end": 5}),
    ("convert_unit", {"columns": ["time"], "from_unit": "min", "to_unit": "h"}),
    ("convert_unit", {"columns": ["time"], "from_unit": "s", "to_unit": "K"}),
    ("time_offset", {"time_column": "time", "offset": 2, "unit": "min"}),
])
def test_invalid_range_or_dimension_or_stale_unit_is_rejected(kind, parameters):
    with pytest.raises(DocumentError):
        execute_node(node(kind, parameters), {"raw": dataset()})


def test_concat_fails_closed_on_missing_nonmonotone_and_incompatible_columns():
    params = {"time_column": "time", "boundary": "next_sample", "first_origin": "zero"}
    for second in [dataset("other", times=(0, None), values=(1, 2)), dataset("other", times=(2, 1), values=(1, 2)), dataset("other", times=(0, 1), values=(1, 2), unit="min")]:
        with pytest.raises(DocumentError):
            execute_node(node("concat_time", params, ("raw", "other")), {"raw": dataset(times=(0, 1), values=(1, 2)), "other": second})
    with pytest.raises(DocumentError):
        validate_node(node("concat_time", {"time_column": "time", "boundary": "guess", "first_origin": "zero"}, ("a", "b")))


def test_offset_requires_declared_time_unit_and_never_modifies_other_columns():
    raw = dataset(times=(0, 2), values=(8, None))
    output, _ = execute_node(node("time_offset", {"time_column": "time", "offset": 3, "unit": "s"}), {"raw": raw})
    assert output["columns"]["time"]["values"] == [3, 5]
    assert output["columns"]["signal"] == raw["columns"]["signal"]


def test_multi_input_graph_cache_binds_both_sources_and_complete_execution_provenance():
    from sciplot_core.plot_document import seal_document
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms
    from test_plot_ir import managed_example

    template, binding, raw = managed_example()
    params = {"time_column": "column:0", "boundary": "next_sample", "first_origin": "zero"}
    binding["transforms"] = [node("concat_time", params, ("A", "B"), "joined")]
    binding["slots"] = {key: {**slot,
        "x": {"source_id": "joined", "column": "Time", "column_index": 0},
        "y": {"source_id": "joined", "column": "Signal", "column_index": 1}, "y_unit": "V"}
        for key, slot in binding["slots"].items()}
    document = create_managed_document(template, binding, plot_id="stages")
    first = resolve_transforms(document, raw)
    assert first["datasets"]["joined"]["columns"]["column:0"]["values"] == [0, 1, 2, 3, 4, 5]
    assert len(first["datasets"]["joined"]["provenance"]["sources"]) == 2
    assert len(first["document"]["scientific"]["provenance"]["transform_execution"][0]["input_hashes"]) == 2
    second = resolve_transforms(first["document"], raw, cache=first["cache"])
    assert second["reused"] == ["joined"] and not second["executed"]
    changed = deepcopy(raw)
    changed["B"]["columns"]["column:1"]["values"][0] = 9
    third = resolve_transforms(seal_document(first["document"]), changed, cache=first["cache"])
    assert third["executed"] == ["joined"] and not third["reused"]
    assert third["datasets"]["joined"]["columns"]["column:1"]["values"][-3:] == [9, 2, 3]
