"""Original-cell n evidence survives sparse coordinates and independent replays."""

from copy import deepcopy
import json

import pandas as pd
import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_data.exports import build_plot_data_exports
from sciplot_core.source_coverage.file_snapshots import _stable_file_snapshot
from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
from sciplot_core.source_coverage.replicate_disclosure import verify_published_replicate_disclosures
from sciplot_core.studio_render import derive_terminal_render_data_contract
from sciplot_core.task_replicate_summary import wide_replicate_evidence


def _spec(source):
    request = {"input": str(source), "rule_id": "impact_metric", "template": "bar", "summary_statistic": "mean_sample_sd_n",
               "replicate_summary_disclosure": {**wide_replicate_evidence(source), "missing_values": "exclude"}}
    units = derive_terminal_render_data_contract(request=request, terminal_sources=[source])["units"]
    return {"source_request": request, "series": units, "axes": units[0]["axes"],
            "categorical": units[0]["categorical_contract"], "reference_guides": units[0]["reference_guides"],
            "direct_labels": units[0]["direct_labels"]}


def _source(tmp_path):
    source = tmp_path / "original.csv"
    source.write_text("Impact strength,Impact strength\nkJ/m2,kJ/m2\nAmber,Blue\n1,2\n2,\n10,8\n")
    return source


def test_replicate_evidence_records_physical_sparse_workbook_cells(tmp_path):
    source = tmp_path / "original.xlsx"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame([[None] * 4, [None] * 4, [None, "Re", None, "Re"], [None, "kJ/m2", None, "kJ/m2"],
                      [None, "Amber", None, "Blue"], [None, 1, None, 2], [None, 2, None, None], [None, 10, None, 8]]).to_excel(writer, sheet_name="Shifted", header=False, index=False)
        pd.DataFrame([[None] * 3, [None, None, "Re"], [None, None, "kJ/m2"], [None, None, "Cobalt"],
                      [None, None, 3], [None, None, 4], [None, None, 9]]).to_excel(writer, sheet_name="Other", header=False, index=False)
    original = file_sha256(source)
    groups = wide_replicate_evidence(source)["groups"]
    assert [group["source_columns"] for group in groups] == [[1], [3], [2]]
    assert [group["missing_cells"] for group in groups] == [[], [[6, 3]], []]
    assert [group["data_start_row"] for group in groups] == [5, 5, 4]
    assert [group["data_end_row"] for group in groups] == [8, 8, 7]
    assert [group["valid_n"] for group in groups] == [3, 2, 3]
    assert [group["condition"] for group in groups] == ["Shifted", "Shifted", "Other"]
    assert file_sha256(source) == original


@pytest.mark.parametrize("mutation", ["missing_count", "source_sha256", "metric", "unit", "column", "missing_cell", "version_bool", "valid_n_float", "column_bool", "unknown_field"])
def test_prepared_replay_and_processed_fallback_export_reject_forged_n_declarations(tmp_path, mutation):
    source = _source(tmp_path)
    original = file_sha256(source)
    spec = _spec(source)
    snapshots = [_stable_file_snapshot(source, label="generated original")]
    valid = _verify_prepared_data(spec, snapshots)
    assert valid["status"] == "passed" and valid["replicate_disclosure_verification"]["status"] == "passed"
    bad = deepcopy(spec)
    declaration = bad["source_request"]["replicate_summary_disclosure"]
    group = declaration["groups"][1]
    if mutation == "missing_count":
        group["missing_count"] = 0
    elif mutation == "source_sha256":
        declaration["source_sha256"] = "0" * 64
    elif mutation == "metric":
        group["metric"] = "Wrong metric"
    elif mutation == "unit":
        group["unit"] = "kg"
    elif mutation == "column":
        group["source_columns"] = [8]
    elif mutation == "missing_cell":
        group["missing_cells"] = [[4, 8]]
    elif mutation == "version_bool":
        declaration["version"] = True
    elif mutation == "valid_n_float":
        group["valid_n"] = 2.0
    elif mutation == "column_bool":
        group["source_columns"] = [True]
    else:
        group["extra"] = "unbound"
    with pytest.raises(ValueError, match="disclosure"):
        _verify_prepared_data(bad, snapshots)
    spec_path = tmp_path / "bad.spec.json"
    spec_path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="disclosure"):
        build_plot_data_exports({"processed_source": str(source), "veusz_spec": str(spec_path)}, destination=tmp_path / "data")
    assert not list((tmp_path / "data").glob("*_replicate_summary.csv"))
    document = tmp_path / "bad.vsz"
    with pytest.raises(ValueError, match="canonical publication request"):
        verify_published_replicate_disclosures(spec["source_request"], [document])
    assert file_sha256(source) == original


def test_original_source_missing_or_drift_blocks_summary_even_if_prepared_table_is_unchanged(tmp_path):
    source = _source(tmp_path)
    spec = _spec(source)
    snapshot = _stable_file_snapshot(source, label="generated original")
    processed = tmp_path / "processed.csv"
    processed.write_bytes(source.read_bytes())
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))
    source.write_text(source.read_text().replace("10,8", "11,8"))
    with pytest.raises(ValueError, match="disclosure"):
        _verify_prepared_data(spec, [snapshot])
    with pytest.raises(ValueError, match="disclosure"):
        build_plot_data_exports({"processed_source": str(processed), "veusz_spec": str(spec_path)}, destination=tmp_path / "drifted")
    source.unlink()
    with pytest.raises(FileNotFoundError):
        _verify_prepared_data(spec, [snapshot])
    with pytest.raises(FileNotFoundError):
        build_plot_data_exports({"processed_source": str(processed), "veusz_spec": str(spec_path)}, destination=tmp_path / "missing")
