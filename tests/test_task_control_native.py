from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256


def _cli(*args: object) -> dict:
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, args), "--json"],
                            cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.comprehensive
def test_public_task_creation_annotation_review_export_and_continuation(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance\nnm,a.u.\nE3,E3\n400,1\n425,2\n450,4\n475,2\n500,1\n")
    original = file_sha256(source)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"version": 1, "action": "create", "source": str(source)}))
    created = _cli("task", "start", "--request", request, "--task-dir", tmp_path / "create")
    assert created["status"] == "complete"
    assert created["result"]["kind"] == "sciplot_project_creation_result"
    project = Path(created["project"])
    figure_id = created["result"]["primary_figure_id"]
    inspected = _cli("project", "inspect", project, "--figure", figure_id)
    figure = inspected["selected_figure"]
    request.write_text(json.dumps({
        "version": 1, "action": "edit", "project": str(project), "figure_id": figure_id,
        "expected_document_sha256": figure["document_sha256"], "operations": [{
            "op": "add_reference_line", "id": "reference450", "parent_path": "/page1/graph1",
            "axis": "x", "value": 450, "unit": "nm",
        }],
    }))
    review = _cli("task", "start", "--request", request, "--task-dir", tmp_path / "edit")
    assert review["status"] == "needs_review"
    assert Path(review["preview"]["image"]["path"]).is_file()
    assert file_sha256(Path(figure["document"])) == figure["document_sha256"]
    response = tmp_path / "accept.json"
    response.write_text('{"accept_preview":true}')
    applied = _cli("task", "resume", review["task_dir"], "--response", response)
    assert applied["status"] == "complete"
    assert applied["result"]["studio_run"]["ready_to_use"] is True
    current = _cli("task", "inspect", applied["task_dir"])
    assert current["current_project"]["delivery"]["current"] is True
    inventory = sorted((project / "runs").glob("studio_*"))
    again = _cli("task", "resume", review["task_dir"], "--response", response)
    assert again["status"] == "complete"
    assert sorted((project / "runs").glob("studio_*")) == inventory
    assert file_sha256(source) == original
