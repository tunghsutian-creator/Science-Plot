from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from sciplot_core.data_mapping import column_choice
from sciplot_core.data_mapping.column_choice import (
    column_choice_snapshot,
    proposal_for_column_choice,
)
from sciplot_core.data_mapping.raw_tables import _map_columns, _read_raw_table
from sciplot_core.foundation.file_hashing import file_sha256


def _snapshot(tmp_path: Path, text: str, *, name: str = "UVvis.csv") -> dict:
    source = tmp_path / name
    source.write_text(text, encoding="utf-8")
    snapshot = column_choice_snapshot(source, "uvvis_spectrum")
    assert snapshot is not None
    return snapshot


def _proposal(tmp_path: Path, snapshot: dict, x: int = 0, y: int = 1):
    request = tmp_path / "request.json"
    request.write_text('{"input":"UVvis.csv"}\n')
    return proposal_for_column_choice(
        snapshot, x_column=x, y_column=y, request_path=request,
        proposal_id="selected_columns", created_at="2026-09-10T08:00:00+00:00",
    )


def test_single_header_keeps_duplicate_names_and_original_blank_column_indices(tmp_path):
    snapshot = _snapshot(tmp_path,
        "Wavelength (nm),Absorbance (a.u.),,Wavelength (nm),Absorbance (a.u.),Notes\n"
        "400,1.00,,405,3.00, NA \n425,2.00,,430,4.00,N/A\n450,1.00,,455,5.00, null \n")
    assert snapshot["layout"] == "single_header" and snapshot["header_row"] == 0
    assert [column["index"] for column in snapshot["columns"]] == list(range(6))
    assert snapshot["columns"][0]["header"] == snapshot["columns"][3]["header"]
    assert snapshot["columns"][2]["header"] == ""
    assert not snapshot["columns"][2]["x_eligible"]
    assert snapshot["rows"][1]["cells"] == ["400", "1.00", "", "405", "3.00", " NA "]
    assert snapshot["rows"][2]["cells"][5] == "N/A"
    before = Path(snapshot["source"]).read_bytes()
    proposal = _proposal(tmp_path, snapshot, 3, 4)
    assert [column.source_column_index for column in proposal.columns] == [3, 4]
    assert proposal.sample_labels == {"source": "UVvis"}
    assert proposal.unit_overrides == {"Wavelength (nm)": "nm", "Absorbance (a.u.)": "a.u."}
    assert proposal.transformations == () and proposal.request_patch == {}
    assert proposal.executable is False and proposal.requires_confirmation
    raw = _read_raw_table(proposal.sources[0], Path(snapshot["source"]))
    mapped = _map_columns(raw, proposal.columns)
    assert mapped.values.tolist() == [["405", "3.00"], ["430", "4.00"], ["455", "5.00"]]
    assert Path(snapshot["source"]).read_bytes() == before


def test_three_rows_bind_sample_headers_and_copy_declared_units(tmp_path):
    snapshot = _snapshot(tmp_path,
        "Wavelength\tAbsorbance\t\tWavelength\tAbsorbance\n"
        "nm\ta.u.\t\tnm\ta.u.\nE0\tE0\t\tE3\tE3\n"
        "400\t1\t\t405\t3\n425\t2\t\t430\t4\n450\t1\t\t455\t5\n",
        name="UVvis.tsv")
    assert snapshot["layout"] == "three_row" and snapshot["header_row"] == 2
    assert snapshot["columns"][3]["sample"] == "E3"
    proposal = _proposal(tmp_path, snapshot, 3, 4)
    assert proposal.sources[0].header_row == 2
    assert [column.expected_header for column in proposal.columns] == ["E3", "E3"]
    assert [column.output_column for column in proposal.columns] == ["Wavelength (nm)", "Absorbance (a.u.)"]
    assert proposal.sample_labels == {"source": "E3"}
    assert proposal.sources[0].sha256 == file_sha256(Path(snapshot["source"]))
    raw = _read_raw_table(proposal.sources[0], Path(snapshot["source"]))
    assert _map_columns(raw, proposal.columns).values.tolist() == [["405", "3"], ["430", "4"], ["455", "5"]]
    with pytest.raises(ValueError, match="different samples"):
        _proposal(tmp_path, snapshot, 0, 4)


@pytest.mark.parametrize("x,y", [(True, 1), (0, False), (0.0, 1), (-1, 1), (0, 9), (0, 0), (1, 0)])
def test_invalid_or_wrong_role_indices_are_rejected(tmp_path, x, y):
    snapshot = _snapshot(tmp_path, "Wavelength (nm),Absorbance (a.u.)\n400,1\n450,2\n")
    with pytest.raises(ValueError):
        _proposal(tmp_path, snapshot, x, y)


def test_source_drift_and_forged_column_evidence_are_rejected(tmp_path):
    snapshot = _snapshot(tmp_path, "Wavelength (nm),Absorbance (a.u.)\n400,1\n450,2\n")
    forged = deepcopy(snapshot)
    forged["columns"][1]["unit"] = "counts"
    with pytest.raises(ValueError, match="evidence changed"):
        _proposal(tmp_path, forged)
    source = Path(snapshot["source"])
    source.write_text(source.read_text().replace("450,2", "450,20"))
    with pytest.raises(ValueError, match="evidence changed"):
        _proposal(tmp_path, snapshot)


def test_source_mutation_during_read_invalidates_snapshot(tmp_path, monkeypatch):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength (nm),Absorbance (a.u.)\n400,1\n450,2\n")
    original_reader = column_choice._read_raw_table

    def mutating_reader(reference, path, **kwargs):
        raw = original_reader(reference, path, **kwargs)
        path.write_text(path.read_text().replace("450,2", "450,20"))
        return raw

    monkeypatch.setattr(column_choice, "_read_raw_table", mutating_reader)
    with pytest.raises(ValueError, match="source changed while reading"):
        column_choice_snapshot(source, "uvvis_spectrum")


@pytest.mark.parametrize("text", [
    "Wavelength,Absorbance\n400,1\n450,2\n",
    "Wavelength (nm),Absorbance (a.u.)\n400,1\n450,NaN\n",
    "Wavelength (nm),Absorbance (a.u.)\n400,1\n450,inf\n",
    "Wavelength,Absorbance\nnm,a.u.\nE0,E3\n400,1\n450,2\n",
    "Wavelength (nm),Absorbance (a.u.)\n400,1\n450,\n",
])
def test_unsupported_layouts_units_missing_values_and_nonfinite_data_fail_closed(tmp_path, text):
    source = tmp_path / "UVvis.csv"
    source.write_text(text)
    assert column_choice_snapshot(source, "uvvis_spectrum") is None


def test_only_supported_rule_text_suffix_and_bounded_columns_are_available(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength (nm),Absorbance (a.u.)\n400,1\n450,2\n")
    assert column_choice_snapshot(source, "ftir_spectrum") is None
    assert column_choice_snapshot(source, "unknown_rule") is None
    other = tmp_path / "UVvis.txt"
    other.write_bytes(source.read_bytes())
    assert column_choice_snapshot(other, "uvvis_spectrum") is None
    source.write_text(
        "Wavelength (nm),Absorbance (a.u.)," + ",".join(["metadata"] * 63) + "\n"
        + ",".join(["1"] * 65) + "\n")
    assert column_choice_snapshot(source, "uvvis_spectrum") is None


def test_preview_is_limited_to_six_original_rows(tmp_path):
    snapshot = _snapshot(tmp_path, "Wavelength (nm),Absorbance (a.u.)\n" + "400,1\n" * 10)
    assert [row["row_index"] for row in snapshot["rows"]] == list(range(6))


def test_pending_registered_rule_cannot_offer_column_choices(tmp_path, monkeypatch):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength (nm),Absorbance (a.u.)\n400,1\n450,2\n")
    pending = replace(column_choice.get_rule("uvvis_spectrum"), fixture_status="pending")
    monkeypatch.setattr(column_choice, "get_rule", lambda rule_id: pending)
    assert column_choice_snapshot(source, "uvvis_spectrum") is None


def test_source_drift_after_snapshot_revalidation_rejects_proposal(tmp_path, monkeypatch):
    snapshot = _snapshot(tmp_path, "Wavelength (nm),Absorbance (a.u.)\n400,1\n450,2\n")
    original_snapshot = column_choice.column_choice_snapshot

    def mutate_after_read(source, rule_id):
        current = original_snapshot(source, rule_id)
        source.write_text(source.read_text().replace("450,2", "450,20"))
        return current

    monkeypatch.setattr(column_choice, "column_choice_snapshot", mutate_after_read)
    with pytest.raises(ValueError, match="changed while creating the proposal"):
        _proposal(tmp_path, snapshot)
