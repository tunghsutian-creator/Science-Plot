"""Generated original-wide CLI, native bar and visible valid-n delivery."""

import csv
import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256


def _cli(*args):
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, args), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=180, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.comprehensive
def test_public_wide_mean_sample_sd_n_delivers_audited_csv_after_explicit_missing_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from sciplot_core.studio_core.registry_state import _veusz_spec_path
    from sciplot_core.studio_core.document_edit_state import run_document_worker

    source = tmp_path / "replicates.csv"
    source.write_text("Impact strength,Impact strength\nkJ/m2,kJ/m2\nAmber,Blue\n1,2\n2,\n10,8\n")
    original = file_sha256(source)
    task = tmp_path / "task"
    first = _cli("task", "create", source, "--rule", "impact_metric", "--template", "bar",
                 "--summary-statistic", "mean_sample_sd_n", "--task-dir", task)
    assert first["status"] == "needs_input", first
    assert first["question"]["field"] == "missing_values"
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(first["question"]["response_template"]))
    created = _cli("task", "resume", task, "--response", answer)
    assert created["status"] == "complete", created
    document = Path(created["current_project"]["figures"][0]["document"])
    spec_path = _veusz_spec_path(document)
    spec = json.loads(spec_path.read_text())
    groups = spec["categorical"]["groups"]
    assert [group["raw_values"] for group in groups] == [[1., 2., 10.], [2., 8.]]
    assert [group["replicate_count"] for group in groups] == [3, 2]
    assert groups[0]["bar_mean"] != 2.  # Skewed source distinguishes a median.
    assert run_document_worker("audit-spec-data", document, spec_path)["status"] == "passed"
    delivery = Path(created["current_project"]["delivery"]["path"])
    summaries = list((delivery / "data").glob("*_replicate_summary.csv"))
    assert len(summaries) == 1
    with summaries[0].open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["sample"] for row in rows] == ["Amber", "Blue"]
    assert [row["valid_n"] for row in rows] == ["3", "2"]
    assert [row["excluded_missing_count"] for row in rows] == ["0", "1"]
    assert [float(row["mean"]) for row in rows] == [group["bar_mean"] for group in groups]
    assert [float(row["sample_sd"]) for row in rows] == [group["bar_error"] for group in groups]
    assert all(row["missing_policy"] == "exclude" and row["spec_sha256"] == file_sha256(spec_path)
               and row["source_sha256"] == source_tree_sha256(source) for row in rows)
    state = json.loads((task / "task.json").read_text())
    manifest = json.loads(Path(state["result"]["studio_run"]["manifest"]).read_text())
    package = manifest["delivery_package"]
    record = next(item for item in package["data_csvs"] if item.get("data_role") == "mean_sample_sd_n")
    assert Path(record["path"]) == summaries[0] and record["sha256"] == file_sha256(summaries[0])
    assert record["source_kind"] == "audited_categorical_contract"
    assert record["source_sha256"] == file_sha256(Path(record["source"])) == file_sha256(spec_path)
    assert record["original_source_sha256"] == source_tree_sha256(source)
    receipt = next(item for item in package["artifacts"] if item["id"] == "plot_data_csv")
    assert record in receipt["details"] and receipt["exists"] and package["complete"]
    assert all(created["current_project"][key]["current"] for key in ("source", "qa", "delivery"))
    assert all(Path(path).is_file() for path in created["next_step"]["images"])
    assert file_sha256(source) == original


@pytest.mark.comprehensive
def test_public_wide_workbook_n_keeps_physical_cells_and_each_original_condition(tmp_path):
    import pandas as pd
    source = tmp_path / "shifted.xlsx"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame([[None] * 4, [None] * 4, [None, "Re", None, "Re"], [None, "kJ/m2", None, "kJ/m2"],
                      [None, "Amber", None, "Blue"], [None, 1, None, 2], [None, 2, None, None], [None, 10, None, 8]]).to_excel(writer, sheet_name="Shifted", header=False, index=False)
        pd.DataFrame([[None] * 3, [None, None, "Re"], [None, None, "kJ/m2"], [None, None, "Cobalt"],
                      [None, None, 3], [None, None, 4], [None, None, 9]]).to_excel(writer, sheet_name="Other", header=False, index=False)
    original = file_sha256(source)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"version": 1, "action": "create", "source": str(source), "rule_id": "impact_metric", "template": "bar",
                                   "summary_statistic": "mean_sample_sd_n", "missing_values": "exclude"}))
    created = _cli("task", "start", "--request", request, "--task-dir", tmp_path / "task")
    assert created["status"] == "complete", created
    delivery = Path(created["current_project"]["delivery"]["path"])
    summaries = list((delivery / "data").glob("*_replicate_summary.csv"))
    assert len(summaries) == 2
    rows = []
    for summary in summaries:
        with summary.open(newline="") as handle:
            rows.extend(csv.DictReader(handle))
    assert {(row["sample"], row["condition"], row["valid_n"]) for row in rows} == {
        ("Amber", "Shifted", "3"), ("Blue", "Shifted", "2"), ("Cobalt", "Other", "3")}
    state = json.loads((tmp_path / "task/task.json").read_text())
    options = json.loads((tmp_path / "task/plan.json").read_text())["source_options"]
    groups = options["replicate_summary_disclosure"]["groups"]
    assert [group["source_columns"] for group in groups] == [[1], [3], [2]]
    assert groups[1]["missing_cells"] == [[6, 3]]
    assert "missing_value_confirmation" not in state  # First-call scientific choice needs no second answer.
    assert all(created["current_project"][key]["current"] for key in ("source", "qa", "delivery"))
    assert file_sha256(source) == original
