"""Literal controls for physical identity, scientific samples and display text."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from sciplot_core.data_mapping.output_files import _safe_output_name
from sciplot_core.data_mapping.table_choice import (
    proposal_for_table_columns, select_table, source_table_snapshot, verify_table_confirmation,
)
from sciplot_core.mapping_contract import DataMappingProposal, DataSourceReference


def selected(tmp_path: Path):
    source = tmp_path / "original.csv"
    source.write_text("Re,Re.1,Re.2\nkJ/m²,kJ/m²,kJ/m²\nA,A,B\n1,7,11\n,8,12\n3,,13\n")
    request = tmp_path / "request.json"
    request.write_text('{"input":"original.csv"}')
    snapshot = source_table_snapshot(source, rule_id="impact_metric")
    selection = {"sheet": None, "header_rows": [0], "unit_row": 1, "sample_row": 2,
                 "data_start_row": 3, "data_end_row": 6}
    return source, request, select_table(snapshot, selection)


def proposal(tmp_path: Path, choices, *, structured=True):
    source, request, snapshot = selected(tmp_path)
    result = proposal_for_table_columns(snapshot, request_path=request,
        proposal_id="literal", created_at="2026-10-21T00:00:00Z", replicates=choices,
        structured_identity=structured)
    return source, result


def test_original_category_and_alias_do_not_define_physical_identity(tmp_path):
    choices = [{"column_index": 0, "label": "a/b || literal"},
               {"column_index": 1, "label": "a (sheet)"},
               {"column_index": 2, "label": "third"}]
    source, first = proposal(tmp_path, choices)
    _, permuted = proposal(tmp_path, [choices[2], choices[0], choices[1]])
    assert first.sample_labels == dict(zip([s.source_id for s in first.sources], ["A", "A", "B"], strict=True))
    assert [s.identity for s in first.sources] == [
        {"version": 1, "source_namespace": str(source.resolve()), "category": sample, "condition": None} for sample in ("A", "A", "B")]
    assert {s.source_id for s in first.sources} == {s.source_id for s in permuted.sources}
    alias = replace(first, display_labels={key: "new/" + value for key, value in first.display_labels.items()})
    assert alias.sources == first.sources and alias.sample_labels == first.sample_labels
    assert [_safe_output_name(s, first, used=set()) for s in first.sources] == [
        _safe_output_name(s, alias, used=set()) for s in alias.sources]
    verify_table_confirmation(first, source)
    with pytest.raises(ValueError, match="reproduce"):
        verify_table_confirmation(alias, source)  # The receipt still binds the confirmed aliases.
    assert DataMappingProposal.from_dict(first.to_dict()) == first


def test_physical_overlap_is_not_a_new_group_under_another_alias(tmp_path):
    with pytest.raises(ValueError, match="Overlapping"):
        proposal(tmp_path, [{"column_index": 0, "label": "first"}, {"column_index": 0, "label": "second"}])


def test_absent_identity_roundtrips_original_serialization_and_legacy_rebuild(tmp_path):
    source, old = proposal(tmp_path, [{"column_index": 0}], structured=False)
    payload = old.to_dict()
    assert "display_labels" not in payload and "identity" not in payload["sources"][0]
    assert payload["sources"][0]["source_id"] == "series_000"
    assert DataMappingProposal.from_dict(deepcopy(payload)).to_dict() == payload
    verify_table_confirmation(DataMappingProposal.from_dict(payload), source)


@pytest.mark.parametrize("identity", [[], {"version": True, "category": "A", "condition": None},
    {"version": 1, "category": "A", "condition": None, "sample": "alias"},
    {"version": 1, "category": "A", "condition": ""}])
def test_identity_is_closed_and_typed(identity):
    with pytest.raises(ValueError):
        DataSourceReference("group_a", "source.csv", "1" * 64, identity=identity)


def test_equal_bytes_from_independent_files_have_distinct_physical_groups(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    source_left, one = proposal(left, [{"column_index": 0}])
    source_right, two = proposal(right, [{"column_index": 0}])
    assert source_left.read_bytes() == source_right.read_bytes()
    assert one.sources[0].sha256 == two.sources[0].sha256
    assert one.sources[0].source_id != two.sources[0].source_id
    assert one.sources[0].identity["source_namespace"] != two.sources[0].identity["source_namespace"]


def test_fresh_confirmed_version_keeps_physical_group_id_without_accepting_stale_receipt(tmp_path):
    source, first = proposal(tmp_path, [{"column_index": 0}])
    selection = first.table_confirmation["selection"]
    source.write_text(source.read_text().replace("1,7,11", "2,7,11"))
    snapshot = source_table_snapshot(source, rule_id="impact_metric")
    fresh = proposal_for_table_columns(select_table(snapshot, selection), request_path=tmp_path / "request.json",
        proposal_id="fresh-version", created_at="2026-10-21T00:00:00Z", replicates=[{"column_index": 0}])
    assert fresh.sources[0].sha256 != first.sources[0].sha256
    assert fresh.sources[0].source_id == first.sources[0].source_id
    verify_table_confirmation(fresh, source)
    with pytest.raises(ValueError, match="reproduce"):
        verify_table_confirmation(first, source)


def test_structured_correspondence_cannot_be_claimed_without_original_selection_owner(tmp_path):
    _, confirmed = proposal(tmp_path, [{"column_index": 0}])
    with pytest.raises(ValueError, match="original-column"):
        replace(confirmed, table_confirmation={})
