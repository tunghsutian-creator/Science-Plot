from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.studio_core.document_edit import preview_project_document
from sciplot_core.studio_core.project_query import inspect_project


@pytest.mark.comprehensive
def test_public_cli_column_choice_exports_real_pda_and_resumes_current_project(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    fixture = repo / ".local/reference_data/real_world/uvvis_spectrum/pda_uvvis_spectra.csv"
    if not fixture.is_file():
        pytest.skip("local source-backed PDA fixture is unavailable")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = inputs / "PDA.csv"
    source.write_bytes(fixture.read_bytes())
    task = tmp_path / "task"
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"version": 1, "action": "create", "source": str(source),
                                   "rule_id": "uvvis_spectrum", "choose_columns": True}))

    def cli(*args):
        result = subprocess.run([str(repo / "skill/scripts/sciplot"), *map(str, args), "--json"],
                                cwd=repo, check=False, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr + result.stdout
        return json.loads(result.stdout)

    question = cli("task", "start", "--request", request, "--task-dir", task)
    assert question["status"] == "needs_input"
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps({"expected_question_id": question["question"]["question_id"],
                                  "column_mapping": {"x_column": 0, "y_column": 1}}))
    completed = cli("task", "resume", task, "--response", answer)
    assert completed["status"] == "complete" and completed["result"]["studio_run"]["ready_to_use"] is True
    current = cli("task", "inspect", task)["current_project"]
    assert current["source"]["current"] is True
    project = Path(completed["project"])
    inspected = inspect_project(project)
    assert inspected["qa"]["current"] is True and inspected["delivery"]["current"] is True
    mapped = load_data_mapping_execution(completed["data_mapping"]["data_mapping_execution"])
    rows = Path(mapped["effective_input"]).read_text().splitlines()
    assert len(rows) == 502 and rows[1] == "800,0.677513659"
    preview_project_document(project, output_dir=tmp_path / "final_preview")
    assert source.read_bytes() == fixture.read_bytes()
    assert cli("task", "resume", task, "--response", answer)["status"] == "complete"
