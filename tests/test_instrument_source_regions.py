"""Original instrument regions precede scientific interpretation and display masks."""
import csv
from copy import deepcopy
import io

import pandas as pd
import pytest

from sciplot_core.semantic_sources.table_scanning import (
    _rheology_test_sections, rheology_instrument_regions,
)
from sciplot_core.source_inspection.input_errors import SourceInputError
from sciplot_core.source_inspection.semantic_evidence import inspect_semantic_tables


def instrument(path, counts=(3, 7), *, missing_tail=False, declared_count=999):
    rows = [["Project:", "Generated physical regions"], []]
    expected = []
    for test, count in enumerate(counts):
        sample = f"Alloy {test + 7}"
        test_row = len(rows)
        rows.extend([["Test:", sample], []])
        result_row = len(rows)
        rows.extend([["Result:", "Temperature ramp 1"], [],
                     ["Interval and data points:", "1", str(declared_count)]])
        header = len(rows)
        rows.extend([["Interval data:", "Point No.", "Time", "Temperature", "Storage Modulus",
                      "Loss Modulus", "Status", "Angular Frequency", "Absent response"], [], []])
        unit = len(rows)
        rows.extend([["", "", "[s]", "[°C]", "[Pa]", "[Pa]", "", "[rad/s]", "[unconfirmed]"], []])
        start = len(rows)
        points = []
        for point in range(count):
            temperature = (280, 280.1, 280, 279.5)[point % 4]
            storage = 100 * (test + 1) + point
            tail = missing_tail and point == count - 1
            rows.append(["", str(point + 1), str(point * 2), "" if tail else str(temperature),
                         "" if tail else str(storage), str(storage / 10), "TruStrain", "6.28", ""])
            points.append((None if tail else temperature, None if tail else storage))
        end = len(rows)
        expected.append({"test_name": sample, "test_row": test_row, "result_row": result_row,
                         "header_row": header, "unit_row": unit, "data_start_row": start,
                         "data_end_row": end, "point_count": count, "points": points})
        rows.extend([[], []])
    stream = io.StringIO()
    csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)
    path.write_text(stream.getvalue(), encoding="utf-16")
    return rows, expected


@pytest.mark.parametrize("counts", [(2,), (5, 1, 8), (1, 4, 2, 6, 3)])
def test_literal_tests_keep_independent_physical_domains_and_raw_cells(tmp_path, counts):
    source = tmp_path / "source.csv"
    rows, expected = instrument(source, counts, missing_tail=True)
    original = source.read_bytes()
    candidate, = inspect_semantic_tables(source)["candidates"]
    assert candidate["format"] == "instrument_intervals"
    assert len(candidate["blocks"]) == len(expected)
    assert "derived_coordinates" not in str(candidate)
    for index, (block, fact) in enumerate(zip(candidate["blocks"], expected, strict=True)):
        assert block["block_id"] == f"block:{index}" and block["order"] == index
        assert block["sample"] == block["label"] == block["test_name"] == fact["test_name"]
        assert block["test_row"] == fact["test_row"] and block["result_row"] == fact["result_row"]
        assert block["result"] == "Temperature ramp 1"
        assert block["table_selection"] == {"sheet": None, "header_rows": [fact["header_row"]],
            "unit_row": fact["unit_row"], "data_start_row": fact["data_start_row"], "data_end_row": fact["data_end_row"]}
        assert block["point_count"] == fact["point_count"]
        assert block["segments"] == []
        assert block["columns"][3]["header"] == "Temperature"
        assert block["columns"][3]["unit"] == "[°C]"
        assert block["columns"][3]["numeric"]["point_count"] == fact["point_count"] - 1
        assert block["columns"][8]["numeric"]["data_end_row"] is None
        assert block["columns"][8]["unit"] == "[unconfirmed]"
        raw = rows[fact["data_start_row"]:fact["data_end_row"]]
        assert len(raw) == fact["point_count"] and all(not row[0] for row in raw)
        assert [(None if not row[3] else float(row[3]), None if not row[4] else float(row[4]))
                for row in raw] == fact["points"]
        assert block["source_interval"]["header_row"] == fact["header_row"]
        assert "nominal_temperature" not in block["source_interval"]
    assert source.read_bytes() == original


def test_test_sections_retain_original_empty_rows_and_index_identity():
    frame = pd.DataFrame([["Test:", "Duplicate"], [None, None], ["record", "a"],
                          ["Test:", "Duplicate"], [None, None], ["record", "b"]])
    before = frame.copy(deep=True)
    sections = _rheology_test_sections(frame, fallback="container")
    assert [name for name, _frame in sections] == ["Duplicate", "Duplicate"]
    assert [list(section.index) for _name, section in sections] == [[0, 1, 2], [3, 4, 5]]
    assert all(section.iloc[1].isna().all() for _name, section in sections)
    pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize("spacers", [0, 3])
def test_complete_export_wrappers_bound_the_previous_test_before_the_next_document(tmp_path, spacers):
    from sciplot_core.semantic_sources.rheology_sweep_sources import _read_rheology_temperature_comparison_samples
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    instrument(first, (2,))
    instrument(second, (5,))
    source = tmp_path / "combined.csv"
    source.write_text(first.read_text(encoding="utf-16") + "\n" * spacers
                      + second.read_text(encoding="utf-16").replace("Alloy 7", "Second literal Test"), encoding="utf-16")
    original = source.read_bytes()
    candidate, = inspect_semantic_tables(source)["candidates"]
    assert [block["test_name"] for block in candidate["blocks"]] == ["Alloy 7", "Second literal Test"]
    assert [block["point_count"] for block in candidate["blocks"]] == [2, 5]
    assert candidate["blocks"][0]["data_end_row"] < candidate["blocks"][1]["test_row"]
    samples = _read_rheology_temperature_comparison_samples(source)
    assert {sample.sample: len(sample.rows) for sample in samples} == {"Alloy 7": 2, "Second literal Test": 5}
    assert source.read_bytes() == original


@pytest.mark.parametrize("wrapper", ["orphan_project", "intervening_record", "unknown_wrapper"])
def test_document_boundary_never_discards_unknown_or_unbound_trailing_rows(tmp_path, wrapper):
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    instrument(first, (2,))
    instrument(second, (5,))
    tail = second.read_text(encoding="utf-16")
    if wrapper == "orphan_project":
        tail = "Project:\tUnbound next document\n\n"
    elif wrapper == "intervening_record":
        tail = tail.replace("Project:\tGenerated physical regions\n", "Project:\tGenerated physical regions\n\t999\t100\n", 1)
    else:
        tail = tail.replace("Project:", "Unrecognized wrapper:", 1)
    source = tmp_path / "combined.csv"
    source.write_text(first.read_text(encoding="utf-16") + tail, encoding="utf-16")
    with pytest.raises(SourceInputError) as error:
        inspect_semantic_tables(source)
    assert error.value.reason_code == "instrument_layout_unsupported"


@pytest.mark.parametrize("bracketed", [False, True])
def test_all_unknown_units_are_literal_metadata_or_an_explicit_layout_failure(tmp_path, bracketed):
    source = tmp_path / "source.csv"
    rows, expected = instrument(source, (3,))
    fact = expected[0]
    units = ["clock_units", "thermal_units", "response_units", "loss_units", "cycle_units", "other_units"]
    for column, unit in zip((2, 3, 4, 5, 7, 8), units, strict=True):
        rows[fact["unit_row"]][column] = f"[{unit}]" if bracketed else unit
    stream = io.StringIO()
    csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)
    source.write_text(stream.getvalue(), encoding="utf-16")
    if not bracketed:
        with pytest.raises(SourceInputError) as error:
            inspect_semantic_tables(source)
        assert error.value.reason_code == "instrument_layout_unsupported"
        return
    result = inspect_semantic_tables(source)
    block, = result["candidates"][0]["blocks"]
    assert block["table_selection"]["unit_row"] == fact["unit_row"]
    assert block["data_start_row"] == fact["data_start_row"] and block["point_count"] == 3
    assert block["columns"][3]["unit"] == "[thermal_units]"
    assert result["scientific_identity"]["confirmed"] is False


def test_every_result_and_interval_is_distinct_without_frequency_identity(tmp_path):
    source = tmp_path / "source.csv"
    rows, first = instrument(source, (2,))
    second_source = tmp_path / "second.csv"
    second_rows, _second = instrument(second_source, (5,))
    start = next(i for i, row in enumerate(second_rows) if row and row[0] == "Result:")
    rows.extend(second_rows[start:])
    stream = io.StringIO()
    csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)
    source.write_text(stream.getvalue(), encoding="utf-16")
    candidate, = inspect_semantic_tables(source)["candidates"]
    assert [block["test_row"] for block in candidate["blocks"]] == [first[0]["test_row"]] * 2
    assert [block["point_count"] for block in candidate["blocks"]] == [2, 5]
    assert [block["source_interval"]["interval_index"] for block in candidate["blocks"]] == [1, 2]
    assert len({block["result_row"] for block in candidate["blocks"]}) == 2
    assert candidate["blocks"][0]["data_end_row"] < candidate["blocks"][1]["data_start_row"]


@pytest.mark.parametrize("mutation", ["missing_header", "unknown_marker", "empty_test", "interior_spacer", "repeated_header", "metadata_in_body"])
def test_unsupported_instrument_structure_never_becomes_whole_file_numeric(tmp_path, mutation):
    source = tmp_path / "source.csv"
    rows, facts = instrument(source, (4,))
    fact = facts[0]
    if mutation == "missing_header":
        rows[fact["header_row"]][0] = "Unsupported interval:"
    elif mutation == "unknown_marker":
        rows = [["Interval:", "7"], ["Temperature", "Storage Modulus"], ["°C", "Pa"], [20, 100]]
    elif mutation == "empty_test":
        rows[fact["test_row"]][1] = ""
    elif mutation == "interior_spacer":
        rows[fact["data_start_row"] + 1] = []
    elif mutation == "repeated_header":
        rows[fact["data_start_row"] + 1] = ["", *rows[fact["header_row"]][1:]]
    else:
        rows[fact["data_start_row"] + 1] = ["Note:", "1", "700"]
    stream = io.StringIO()
    csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)
    source.write_text(stream.getvalue(), encoding="utf-16")
    original = source.read_bytes()
    with pytest.raises(SourceInputError) as error:
        inspect_semantic_tables(source)
    assert error.value.reason_code == "instrument_layout_unsupported"
    assert error.value.repair["action"] == "inspect_original_table"
    assert source.read_bytes() == original


def test_generic_domain_uses_declared_member_records_not_numeric_extent_or_formatting(tmp_path):
    from openpyxl import Workbook
    source = tmp_path / "source.xlsx"
    book = Workbook()
    sheet = book.active
    for row in [["Index", "Temperature", "Storage Modulus", "Absent response"],
                ["", "°C", "Pa", "Pa"], [1, 20, 100, None], [2, None, None, None],
                [3, "NA", None, None]]:
        sheet.append(row)
    sheet.cell(90, 2).number_format = "0.000"
    book.save(source)
    candidate, = inspect_semantic_tables(source)["candidates"]
    assert candidate["table_selection"]["data_start_row"] == 2
    assert candidate["table_selection"]["data_end_row"] == 5
    block, = candidate["blocks"]
    assert block["point_count"] == 3 and block["column_indices"] == [0, 1, 2, 3]
    assert block["table_selection"] == candidate["table_selection"]
    assert block["data_end_row"] == 5
    assert candidate["columns"][1]["numeric"]["data_end_row"] == 3
    assert candidate["columns"][3]["numeric"]["point_count"] == 0


def test_wrong_test_selection_revises_the_same_draft_from_original_regions(tmp_path, monkeypatch):
    from sciplot_core import task_control, task_semantic_creation as creation
    source = tmp_path / "source.csv"
    _rows, facts = instrument(source, (3, 6))
    original = source.read_bytes()
    intent = {"x": {"quantity": "temperature", "unit": "°C", "scale": "linear"},
              "y": {"quantity": "storage_modulus", "unit": "Pa", "scale": "log"},
              "selection": {"test_names": ["unobserved"]}}
    calls = []
    monkeypatch.setattr(creation, "execute_managed", lambda current, wire: calls.append(wire) or {
        "status": "blocked", "ready_to_use": False, "next_step": {"action": "retry_same_request"}})
    task = tmp_path / "draft"
    blocked = task_control.start_task({"version": 1, "action": "create", "sources": [str(source)], "intent": intent}, task_dir=task)
    assert blocked["blocker"]["reason_code"] == "semantic_source_selection_unmatched" and not calls
    assert [block["test_name"] for block in blocked["blocker"]["repair"]["available_blocks"]] == [fact["test_name"] for fact in facts]
    revised = deepcopy(intent)
    revised["selection"]["test_names"] = [facts[1]["test_name"]]
    continued = task_control.resume_task(task, {"expected_intent_revision": 1, "revise_intent": revised})
    assert continued["task_dir"] == str(task) and continued["intent_revision"] == 2
    assert continued["source_plan"]["selection"]["selected_point_count"] == 6
    assert len(calls) == 1
    assert source.read_bytes() == original


def test_recipe_and_observer_share_bounds_without_changing_temperature_interval_policy(tmp_path):
    from sciplot_core.semantic_sources.rheology_sweep_sources import _read_rheology_temperature_comparison_samples
    source = tmp_path / "source.csv"
    _rows, expected = instrument(source, (3, 6))
    samples = _read_rheology_temperature_comparison_samples(source)
    assert {sample.sample for sample in samples} == {fact["test_name"] for fact in expected}
    for sample in samples:
        fact = next(fact for fact in expected if fact["test_name"] == sample.sample)
        assert [(row["x"], row["storage_modulus"]) for row in sample.rows] == fact["points"]
        assert sample.x_conversion["source_unit_authority"] == "adjacent_unit_row"
        assert sample.metric_conversions["storage_modulus"]["source_unit_authority"] == "adjacent_unit_row"
    candidate, = inspect_semantic_tables(source)["candidates"]
    assert [block["point_count"] for block in candidate["blocks"]] == [3, 6]


@pytest.mark.parametrize("text,expected", [("FS 210 °C", ("210", 210.)),
    ("Frequency Sweep -12.5℃", ("-12.5", -12.5)), ("fs +7 °C", ("+7", 7.)),
    ("Temperature ramp 1", None), ("FS 7 K", None), ("prefix FS 7 °C", None)])
def test_registered_frequency_condition_text_parser_keeps_its_existing_semantics(text, expected):
    from sciplot_core.semantic_sources.rheology_sweep_sources import frequency_result_condition
    assert frequency_result_condition(text) == expected


def test_no_instrument_markers_leave_generic_disconnected_guard_unchanged():
    from sciplot_core.semantic_sources.paired_curve_data_block import first_paired_curve_data_block
    frame = pd.DataFrame([["Temperature", "Storage Modulus"], [20, 100], [None, None], [30, 200]])
    assert rheology_instrument_regions(frame) is None
    with pytest.raises(ValueError, match="disconnected"):
        first_paired_curve_data_block(frame, data_start=1, pairs=((0, 1),))


def test_semantic_observer_and_plan_reject_an_unconfirmed_disconnected_generic_domain(tmp_path):
    from sciplot_core.task_semantic_plan import prepare_plan
    source = tmp_path / "disconnected.csv"
    source.write_text("Temperature,Storage Modulus\n°C,Pa\n20,100\n,\n30,200\n")
    original = source.read_bytes()
    for inspect in (lambda: inspect_semantic_tables(source), lambda: prepare_plan([source], {
        "x": {"quantity": "temperature", "unit": "°C", "scale": "linear"},
        "y": {"quantity": "storage_modulus", "unit": "Pa", "scale": "log"},
    })):
        with pytest.raises(SourceInputError) as error:
            inspect()
        assert error.value.reason_code == "semantic_table_region_ambiguous"
        assert error.value.repair["row_index"] == 3
    assert source.read_bytes() == original


def test_existing_confirmed_selection_keeps_its_nullable_domain_without_reinspection(tmp_path):
    from sciplot_core.data_mapping.table_choice import read_original_table, select_table, source_table_snapshot
    source = tmp_path / "confirmed.csv"
    source.write_text("Temperature,Storage Modulus\n°C,Pa\n20,100\n,\n30,200\n")
    snapshot = source_table_snapshot(source)
    selection = {"sheet": None, "header_rows": [0], "unit_row": 1, "data_start_row": 2, "data_end_row": 5}
    selected = select_table(snapshot, selection)
    assert selected["table_selection"] == selection
    assert [column["numeric"]["point_count"] for column in selected["columns"]] == [3, 3]
    assert [column["numeric"]["invalid_count"] for column in selected["columns"]] == [1, 1]
    frame = read_original_table(source, None, snapshot["file_sha256"])
    assert len(frame.iloc[selection["data_start_row"]:selection["data_end_row"]]) == 3
    assert list(frame.iloc[3]) == ["", ""]
