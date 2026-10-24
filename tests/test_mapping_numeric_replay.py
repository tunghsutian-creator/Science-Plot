"""Generated mapping v2 histories and fixed v3 numeric execution contracts."""

from dataclasses import replace
from pathlib import Path

import pytest

from mapping_numeric_history import (
    hashes, historical_case, mixed_profile_attack, read_json, write_json,
)
from sciplot_core.data_mapping import (
    create_data_mapping_confirmation, execute_data_mapping_proposal,
    load_data_mapping_execution, load_data_mapping_proposal, preview_data_mapping_proposal,
)
from sciplot_core.data_mapping import execution as writer
from sciplot_core.data_mapping import execution_loading as reader
from sciplot_core.data_mapping.table_choice import (
    replicate_proposal_contents, select_table, table_choice_snapshot,
)
from sciplot_core.data_mapping.original_tables import source_table_snapshot
from sciplot_core.source_tables import parsing
from sciplot_core.source_tables.read_session import table_read_session
from sciplot_core.foundation.file_hashing import file_sha256


@pytest.mark.parametrize("name", ["nul", "sorted306", "sorted310", "converted_nul306", "threshold306", "selected306", "two306", "sort_nul310", "baseline310"])
def test_path_rebound_actual_v2_history_replays_without_mutating_files(tmp_path, name):
    case, manifest = historical_case(tmp_path, name)
    before = hashes(case)
    loaded = load_data_mapping_execution(manifest)
    assert loaded["version"] == 2 and loaded["status"] == "passed"
    assert "source_numeric_encoding" not in loaded["transform_steps"][0]["parameters"]
    assert hashes(case) == before


def current_execution(tmp_path, name):
    case, manifest = historical_case(tmp_path, name)
    record = read_json(manifest)
    proposal = replace(load_data_mapping_proposal(record["proposal"]), proposal_id="new_v3")
    output = case / "new_execution"
    confirmation = create_data_mapping_confirmation(proposal, source_root=record["source_root"],
        request_path=record["base_request"], output_root=output, confirmed_by="generated current execution")
    return case, record, proposal, confirmation, output


def test_new_execution_v3_pins_parser_and_ledger_independently_of_current_alias(tmp_path, monkeypatch):
    case, record, proposal, confirmation, output = current_execution(tmp_path, "sorted306")
    old_files = hashes(case)
    result = execute_data_mapping_proposal(proposal, confirmation, source_root=record["source_root"],
        request_path=record["base_request"], output_root=output)
    assert result["version"] == 3
    assert result["outputs"][0]["sha256"] == "7afe2ea6038aa076ce6d10203581671d502ab02f2fcf8163b886c52fd4456d7d"
    assert result["transform_steps"][0]["parameters"]["source_numeric_encoding"] == "decimal_float64_round_trip_v2"
    monkeypatch.setattr(parsing, "DECIMAL_ROUND_TRIP_ENCODING", "future_default_not_v2")
    assert load_data_mapping_execution(Path(result["output_root"]) / "execution.json")["status"] == "passed"
    after = hashes(case)
    assert all(after[path] == digest for path, digest in old_files.items())


@pytest.mark.parametrize("name", ["nul", "converted_nul306", "selected306"])
def test_old_unexecuted_proposal_does_not_admit_legacy_numeric_cells(tmp_path, name):
    case, record, proposal, confirmation, output = current_execution(tmp_path, name)
    before = hashes(case)
    with pytest.raises(ValueError):
        execute_data_mapping_proposal(proposal, confirmation, source_root=record["source_root"],
            request_path=record["base_request"], output_root=output)
    assert not output.exists() and hashes(case) == before


def test_existing_execution_idempotent_reuse_precedes_fresh_preview(tmp_path, monkeypatch):
    case, manifest = historical_case(tmp_path, "converted_nul306")
    record = read_json(manifest)
    before = hashes(case)
    def no_new_preview(*args, **kwargs):
        raise AssertionError("An existing sealed execution must not enter fresh numeric preparation.")
    monkeypatch.setattr(writer, "preview_data_mapping_proposal", no_new_preview)
    result = execute_data_mapping_proposal(record["proposal"], record["confirmation"], source_root=record["source_root"],
        request_path=record["base_request"], output_root=Path(record["output_root"]).parent)
    assert result["idempotent_reuse"] is True and result["version"] == 2
    assert hashes(case) == before


@pytest.mark.parametrize("field", ["source", "output", "ledger", "version"])
def test_drifted_history_is_rejected_before_historical_numeric_preparation(tmp_path, monkeypatch, field):
    case, manifest = historical_case(tmp_path, "nul")
    record = read_json(manifest)
    if field == "version":
        record["version"] = 999
        write_json(manifest, record)
    else:
        path = (Path(record["source_root"]) / "measurements.csv" if field == "source" else
                Path(record["outputs"][0]["path"]) if field == "output" else Path(record["transform_ledger"]))
        path.write_bytes(path.read_bytes() + b"\n")
    before = hashes(case)
    def no_numeric_candidate(*args, **kwargs):
        raise AssertionError("Drifted source/output/ledger or unknown version cannot admit a numeric candidate.")
    monkeypatch.setattr(reader, "_prepare_mapping_frames", no_numeric_candidate)
    with pytest.raises(ValueError):
        load_data_mapping_execution(manifest)
    assert hashes(case) == before


def test_one_execution_cannot_mix_individually_matching_legacy_pipelines(tmp_path, monkeypatch):
    case, manifest = historical_case(tmp_path, "two306")
    _other, modern = historical_case(tmp_path, "sorted310")
    replacement = Path(read_json(modern)["outputs"][0]["path"]).read_bytes()
    mixed_profile_attack(manifest, replacement)
    before = hashes(case)
    calls = []
    actual = reader._prepare_mapping_frames
    def recording(*args, **kwargs):
        calls.append(kwargs["numeric_contract"])
        return actual(*args, **kwargs)
    monkeypatch.setattr(reader, "_prepare_mapping_frames", recording)
    with pytest.raises(reader.MappingReplayMismatch, match="does not reproduce"):
        load_data_mapping_execution(manifest)
    assert calls == ["legacy_fused", "legacy_round_trip"]
    assert hashes(case) == before


def test_source_change_after_frame_read_is_still_rejected(tmp_path, monkeypatch):
    _case, manifest = historical_case(tmp_path, "converted_nul306")
    record = read_json(manifest)
    source = Path(record["source_root"]) / "observations.csv"
    actual = reader._prepare_mapping_frames
    calls = []
    def change_after_read(*args, **kwargs):
        result = actual(*args, **kwargs)
        calls.append(kwargs["numeric_contract"])
        source.write_bytes(source.read_bytes() + b"\n")
        return result
    monkeypatch.setattr(reader, "_prepare_mapping_frames", change_after_read)
    with pytest.raises(ValueError, match="hash|changed"):
        load_data_mapping_execution(manifest)
    assert calls == ["legacy_fused"]


@pytest.mark.parametrize("field", ["request_seed", "transform_ledger", "superseded_base_transform_ledger"])
def test_original_post_frame_seals_remain_current(tmp_path, monkeypatch, field):
    case, old, proposal, _receipt, output = current_execution(tmp_path, "sorted306")
    request = case / "request_with_prior_ledger.json"
    base = read_json(Path(old["base_request"]))
    base["transform_ledger"] = read_json(Path(old["transform_ledger"]))
    write_json(request, base)
    proposal = replace(proposal, base_request_sha256=file_sha256(request))
    receipt = create_data_mapping_confirmation(proposal, source_root=old["source_root"], request_path=request,
        output_root=output, confirmed_by="generated current execution with prior ledger")
    created = execute_data_mapping_proposal(proposal, receipt, source_root=old["source_root"],
        request_path=request, output_root=output)
    target = Path(created[field])
    manifest = Path(created["output_root"]) / "execution.json"
    actual = reader._prepare_mapping_frames
    calls = []
    def drift_after_frames(*args, **kwargs):
        result = actual(*args, **kwargs)
        calls.append(kwargs["numeric_contract"])
        target.write_bytes(target.read_bytes() + b" ")
        return result
    monkeypatch.setattr(reader, "_prepare_mapping_frames", drift_after_frames)
    with pytest.raises(ValueError, match="hash"):
        load_data_mapping_execution(manifest)
    assert calls == ["v3"]


def test_old_execution_cannot_be_relabelled_as_v3_without_its_numeric_ledger(tmp_path, monkeypatch):
    _case, manifest = historical_case(tmp_path, "nul")
    record = read_json(manifest)
    record["version"] = 3  # Deliberately invalid test attack, never a producer fixture.
    write_json(manifest, record)
    def no_historical_candidate(*args, **kwargs):
        raise AssertionError("A wrong v3 ledger cannot fall back to a historical pipeline.")
    monkeypatch.setattr(reader, "_prepare_mapping_frames", no_historical_candidate)
    with pytest.raises(ValueError, match="confirmed proposal"):
        load_data_mapping_execution(manifest)


def test_old_eligibility_cache_cannot_change_new_preview_in_the_same_read_session(tmp_path):
    _case, manifest = historical_case(tmp_path, "selected306")
    record = read_json(manifest)
    proposal = load_data_mapping_proposal(record["proposal"])
    source = Path(record["source_root"]) / proposal.sources[0].relative_path
    with table_read_session():
        assert load_data_mapping_execution(manifest)["status"] == "passed"
        binding = proposal.table_confirmation
        selected = select_table(table_choice_snapshot(source, binding["rule_id"]), binding["selection"], binding["metadata_confirmations"])
        assert selected["columns"][1]["numeric"]["invalid_count"] == 1
        assert selected["columns"][1]["y_eligible"] is False
        with pytest.raises(ValueError):
            preview_data_mapping_proposal(proposal, source_root=record["source_root"], request_path=record["base_request"])


def test_historical_numeric_summary_does_not_expand_replicate_float_grammar(tmp_path):
    source = tmp_path / "replicates.csv"
    source.write_text("Impact strength,Notes\nkJ/m2,\nAmber,\n0.12345678901234567\x00suffix,\n1,\n")
    selection = {"sheet": None, "header_rows": [0], "unit_row": 1, "sample_row": 2,
                 "data_start_row": 3, "data_end_row": 5}
    selected = select_table(source_table_snapshot(source, rule_id="impact_metric"), selection, numeric_contract="legacy_fused")
    with pytest.raises(ValueError, match="Nonnumeric original replicate"):
        replicate_proposal_contents(selected, [{"column_index": 0}], numeric_contract="legacy_fused")
