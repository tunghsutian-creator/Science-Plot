"""Exact saved regions reuse the original fact scope through each consumer."""
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from sciplot_core.data_mapping.original_tables import source_table_snapshot
from sciplot_core.data_mapping.source_mapping import _prepare_mapping_frames
from sciplot_core.data_mapping.table_choice import proposal_for_table_columns, select_table, verify_table_confirmation
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.mapping_contract import DataMappingProposal
from test_source_observation_scope import DISCONNECTED, only_cells, workbook


def region(sheet, end):
    return {"sheet": sheet, "header_rows": [0], "unit_row": 1, "sample_row": 2,
            "data_start_row": 3, "data_end_row": end}


def literal_view_id(source, sheet, start, end, columns):
    """Independent contract vector: exact physical cells, never display text."""
    payload = {"source_namespace": str(source.resolve()), "sheet": sheet,
               "data_start_row": start, "data_end_row": end, "columns": columns}
    return "group_" + hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode()).hexdigest()[:32]


def test_template_preparation_reads_only_the_declared_sheet(tmp_path, monkeypatch):
    from sciplot_core.plot_engine.template_creation_binding import prepare
    from test_plot_template_creation import template_request

    rows = [["Wavelength", "Absorbance", "Wavelength", "Absorbance"], ["nm", "a.u.", "nm", "a.u."],
            ["E2", "E2", "E4", "E4"], [400, 1, 400, 2], [450, 2, 450, 3], [500, 3, 500, 4]]
    source = workbook(tmp_path / "spectra.xlsx", [("Summary", DISCONNECTED), ("Measured", rows)])
    original = source.read_bytes()
    calls = only_cells(monkeypatch, {(source, "Measured")})
    request = template_request(source)
    request["data_binding"]["data_sources"][0]["table_selection"]["sheet"] = "Measured"
    _, task, _ = prepare(request)
    assert task["mapping"]["table_selection"] == region("Measured", 6)
    assert task["mapping"]["column_mapping"]["pairs"] == [{"x_column": 0, "y_column": 1}, {"x_column": 2, "y_column": 3}]
    assert set(calls) == {(source, "Measured")} and source.read_bytes() == original


def test_categorical_reload_keeps_exact_rows_and_full_discovery_remains_explicit(tmp_path, monkeypatch):
    from sciplot_core.studio_render.categorical_bindings import categorical_table_facts, read_categorical_frame

    source = workbook(tmp_path / "categories.xlsx", [("Summary", DISCONNECTED), ("Measured", [
        ["Sample", "Strength (MPa)"], ["B", "0.12345678901234567"], ["A", "1.0000000000000002"]])])
    original = source.read_bytes()
    calls = only_cells(monkeypatch, {(source, "Measured")})
    binding = {"source_sha256": file_sha256(source), "mode": "given_values", "sample_column": 0,
               "value_columns": [{"column_index": 1}],
               "table_selection": {"sheet": "Measured", "header_rows": [0], "data_start_row": 1, "data_end_row": 3}}
    frame = read_categorical_frame(source, binding).frame
    assert frame.values.tolist() == [["B", "0.12345678901234567"], ["A", "1.0000000000000002"]]
    assert list(frame.index) == [1, 2] and set(calls) == {(source, "Measured")}
    monkeypatch.undo()
    calls = only_cells(monkeypatch, {(source, "Measured"), (source, "Summary")})
    discovered = categorical_table_facts(source, {"mode": "given_values"})
    assert [table["sheet"] for table in discovered["tables"]] == ["Summary", "Measured"]
    assert set(calls) == {(source, "Measured"), (source, "Summary")} and source.read_bytes() == original


def test_explicit_append_and_reload_never_observe_unselected_workbook_cells(tmp_path, monkeypatch):
    from sciplot_core.plot_engine.managed_resolution import resolve_science
    from sciplot_core.plot_engine.managed_state import resolved_ir
    from sciplot_core.plot_engine.managed_updates import prepare_update
    from test_managed_source_append import append_request, bound_document

    document = bound_document(tmp_path)
    original_document = deepcopy(document)
    request = append_request(document, tmp_path)
    value = request["changes"][0]["value"]
    old_source = Path(value["source"]["path"])
    with old_source.open(newline="") as stream:
        rows = list(csv.reader(stream))
    source = workbook(tmp_path / "append.xlsx", [("Summary", DISCONNECTED), ("Appended", rows)])
    value["source"].update(path=str(source), sha256=file_sha256(source))
    value["source"]["table_selection"]["sheet"] = "Appended"
    original = source.read_bytes()
    allowed = {(Path(item["path"]), item["table_selection"]["sheet"]) for item in document["scientific"]["data_sources"]}
    calls = only_cells(monkeypatch, allowed | {(source, "Appended")})
    candidate, _, _, execute = prepare_update(document, request)
    assert execute and document == original_document
    candidate, _ = resolve_science(tmp_path / "store", candidate)
    data = resolved_ir(tmp_path / "store", candidate)["datasets"]["raw:B"]
    assert data["columns"]["column:0"]["values"] == [8, 5, 5, 2]
    assert data["columns"]["column:1"]["values"] == [7, None, 3, 9]
    assert data["provenance"]["sources"][0]["rows"] == [3, 4, 5, 6]
    assert (source, "Appended") in calls and source.read_bytes() == original


def test_append_instrument_region_proof_keeps_full_catalog_ordinal(tmp_path, monkeypatch):
    from sciplot_core.plot_engine.append_source_regions import confirm_append_region
    from test_instrument_source_regions import instrument

    rows, facts = instrument(tmp_path / "instrument.csv", (3, 4))
    source = workbook(tmp_path / "instrument.xlsx", [("Summary", DISCONNECTED), ("Acquisition", rows)])
    calls = only_cells(monkeypatch, {(source, "Acquisition")})
    snapshot = source_table_snapshot(source, sheets=["Acquisition"])
    fact = facts[1]
    selection = {"sheet": "Acquisition", "header_rows": [fact["header_row"]], "unit_row": fact["unit_row"],
                 "data_start_row": fact["data_start_row"], "data_end_row": fact["data_end_row"]}
    binding = {"path": str(source), "sha256": file_sha256(source), "table_selection": selection}
    proof = confirm_append_region(snapshot, binding, [{"sample": fact["test_name"], "x_column_index": 3, "y_column_index": 4}])
    assert proof["table_id"] == "table:1" and proof["block_id"] == "block:1"
    assert proof["table_selection"] == selection and set(calls) == {(source, "Acquisition")}
    with pytest.raises(ValueError) as error:
        confirm_append_region(snapshot, binding, [{"sample": "Invented", "x_column_index": 3, "y_column_index": 4}])
    assert error.value.reason_code == "managed_append_sample_conflict"


@pytest.mark.parametrize("kind", ["pairs", "replicates"])
def test_saved_multiple_sheet_mapping_replays_every_explicit_region_and_no_other_sheet(tmp_path, monkeypatch, kind):
    if kind == "pairs":
        first = [["Wavelength", "Absorbance"], ["nm", "a.u."], ["A", "A"], [400, 1], [450, 2], [500, 3]]
        second = [["Wavelength", "Absorbance"], ["nm", "a.u."], ["B", "B"], [410, 8], [460, 9]]
        choices = [{"x_column": 0, "y_column": 1}, {"x_column": 0, "y_column": 1, "table_selection": region("Second", 5)}]
        rule = "uvvis_spectrum"
    else:
        first = [["Re"], ["kJ/m²"], ["A"], [1], [None], [2], [None], [3]]
        second = [["Re"], ["kJ/m²"], ["B"], [8], [9], [10]]
        choices = [{"column_index": 0}, {"column_index": 0, "table_selection": region("Second", 6)}]
        rule = "impact_metric"
    source = workbook(tmp_path / "multiple.xlsx", [("First", first), ("Unselected", DISCONNECTED), ("Second", second)])
    original = source.read_bytes()
    calls = only_cells(monkeypatch, {(source, "First"), (source, "Second")})
    snapshot = source_table_snapshot(source, rule_id=rule, sheets=["First", "Second"])
    selected = select_table(snapshot, region("First", len(first)))
    request = tmp_path / "request.json"
    request.write_text("{}")
    arguments = {"request_path": request, "proposal_id": "multiple", "created_at": "2026-10-21T00:00:00+00:00", kind: choices}
    columns = [0, 1] if kind == "pairs" else [0]
    current_ids = [literal_view_id(source, "First", 3, len(first), columns),
                   literal_view_id(source, "Second", 3, len(second), columns)]
    for structured in (True, False):
        proposal = proposal_for_table_columns(selected, **arguments, structured_identity=structured)
        ids = current_ids if structured else ["series_000", "series_001"]
        assert [reference.source_id for reference in proposal.sources] == ids
        assert proposal.sample_labels == {ids[0]: "A", ids[1]: "B"}
        assert [(reference.sheet, reference.data_start_row, reference.data_end_row)
                for reference in proposal.sources] == [("First", 3, len(first)), ("Second", 3, len(second))]
        payload = proposal.to_dict()
        if not structured:
            assert "display_labels" not in payload and all("identity" not in item for item in payload["sources"])
        saved = DataMappingProposal.from_dict(json.loads(json.dumps(payload)))
        assert saved.to_dict() == payload
        verify_table_confirmation(saved, source)
        _, frames, _, _, _ = _prepare_mapping_frames(saved, source_root=tmp_path)
        assert set(frames) == set(ids)
        if kind == "pairs":
            assert frames[ids[0]].values.tolist() == first[3:]
            assert frames[ids[1]].values.tolist() == second[3:]
        else:
            assert [len(frames[key]) for key in ids] == [5, 3]
            assert frames[ids[0]].iloc[:, 0].isna().tolist() == [False, True, False, True, False]
            assert frames[ids[0]].iloc[:, 0].dropna().tolist() == [1, 2, 3]
            assert frames[ids[1]].iloc[:, 0].tolist() == [8, 9, 10]
    assert set(calls) == {(source, "First"), (source, "Second")} and source.read_bytes() == original
    bad = deepcopy(choices)
    bad[1]["table_selection"]["sheet"] = "Missing"
    with pytest.raises(ValueError):
        proposal_for_table_columns(selected, **{**arguments, kind: bad})
    if kind == "replicates":
        with pytest.raises(ValueError, match="Overlapping"):
            proposal_for_table_columns(selected, **{**arguments, kind: [choices[0], choices[0]]})
