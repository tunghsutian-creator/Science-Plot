from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import anyio
import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256


def cli(*arguments):
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, arguments), "--json"],
                            cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def task(tmp_path, name, request):
    path = tmp_path / (name + ".json")
    path.write_text(json.dumps(request))
    return cli("task", "start", "--request", path, "--task-dir", tmp_path / name)


def accept(tmp_path, review):
    path = tmp_path / "accept.json"
    path.write_text(json.dumps({"accept_preview": True, "expected_operation_id": review["operation_id"]}))
    return cli("task", "resume", review["task_dir"], "--response", path)


@pytest.mark.comprehensive
@pytest.mark.parametrize("transport", ["cli", "mcp"])
def test_saved_sample_styles_transfer_across_experiments_by_name(tmp_path, transport):
    uvvis, ftir = tmp_path / "UVvis.csv", tmp_path / "FTIR.csv"
    uvvis.write_text("Wavelength,Absorbance,Wavelength,Absorbance,Wavelength,Absorbance\n"
                     "nm,a.u.,nm,a.u.,nm,a.u.\nE0,E0,E2,E2,E3,E3\n"
                     "400,1,400,2,400,3\n450,3,450,4,450,5\n500,2,500,3,500,4\n")
    ftir.write_text("Wavenumber,Absorbance,Wavenumber,Absorbance,Wavenumber,Absorbance\n"
                    "cm-1,a.u.,cm-1,a.u.,cm-1,a.u.\nE3,E3,E0,E0,E2,E2\n"
                    "1000,4,1000,1,1000,2\n1250,5,1250,2,1250,3\n1500,3,1500,1,1500,2\n")
    raw = {p: p.read_bytes() for p in (uvvis, ftir)}
    origin = task(tmp_path, "origin", {"version": 1, "action": "create", "source": str(uvvis)})
    source_project = Path(origin["project"])
    source_figure = cli("task", "inspect", origin["task_dir"])["current_project"]["figures"][0]
    expected = {"E0": {"color": "#222222", "width": "2pt"},
                "E2": {"color": "#3568C0", "width": "1.5pt"},
                "E3": {"color": "#2A9D8F", "width": "2.5pt"}}
    styled = task(tmp_path, "style_origin", {"version": 1, "action": "edit", "project": str(source_project),
        "expected_document_sha256": source_figure["document_sha256"], "export": False,
        "operations": [{"op": "set_sample_style", "samples": [label], "style": style} for label, style in expected.items()]})
    assert accept(tmp_path, styled)["result"]["status"] == "saved"
    origin_before = {str(p): file_sha256(p) for p in source_project.rglob("*") if p.is_file()}
    target = task(tmp_path, "target", {"version": 1, "action": "create", "source": str(ftir)})
    target_project = Path(target["project"])
    target_figure = cli("task", "inspect", target["task_dir"])["current_project"]["figures"][0]
    specification = Path(target_figure["spec"])
    science_before = json.loads(specification.read_text())
    revision = target_figure["document_sha256"]
    runs_before = sorted((target_project / "runs").iterdir())

    def request(preset):
        return {"version": 1, "action": "edit", "project": str(target_project),
                "expected_document_sha256": revision, "export": False, "operations": [
                    {"op": "apply_sample_style_preset", "preset": preset["preset"],
                     "expected_preset_sha256": preset["preset_sha256"]}]}

    def freeze_check(review, preset):
        signed = json.loads(Path(review["preview"]["review_path"]).read_text())
        assert len(signed["operations"]) == 9 and all(item["op"] == "set_style" for item in signed["operations"])
        assert file_sha256(Path(target_figure["document"])) == revision
        Path(preset["preset"]).write_text('{"changed_after_preview":true}')
        assert review["preview"]["scientific_audit"]["status"] == "passed"

    if transport == "cli":
        preset = cli("project", "style-capture", source_project, "--out", tmp_path / "preset")
        review = task(tmp_path, "reuse", request(preset))
        assert review["status"] == "needs_review"
        freeze_check(review, preset)
        saved = accept(tmp_path, review)
    else:
        pytest.importorskip("mcp")
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters

        async def scenario():
            params = StdioServerParameters(command=sys.executable, args=["-m", "sciplot_core.mcp_server"],
                cwd=REPO_ROOT, env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")})
            async with Client(params, read_timeout_seconds=180) as client:
                result = await client.call_tool("sciplot_sample_style_capture", {
                    "project": str(source_project), "output_dir": str(tmp_path / "preset")})
                assert not result.is_error, result.content
                preset = result.structured_content
                result = await client.call_tool("sciplot_task_start", {
                    "request": request(preset), "task_dir": str(tmp_path / "reuse")})
                assert not result.is_error, result.content
                review = result.structured_content
                image = await client.call_tool("sciplot_read_result", {"uri": review["preview_resource"]})
                assert image.content[1].type == "image"
                freeze_check(review, preset)
                result = await client.call_tool("sciplot_task_resume", {"task": review["task_dir"],
                    "response": {"accept_preview": True, "expected_operation_id": review["operation_id"]}})
                assert not result.is_error, result.content
                return result.structured_content
        saved = anyio.run(scenario)

    assert saved["result"]["status"] == "saved" and saved["result"]["export_performed"] is False
    assert json.loads(specification.read_text()) == science_before
    assert sorted((target_project / "runs").iterdir()) == runs_before
    current = cli("project", "inspect", target_project, "--figure", target_figure["figure_id"])["selected_figure"]
    assert [item["sample"] for item in current["sample_styles"]] == ["E3", "E0", "E2"]
    for sample in current["sample_styles"]:
        path = sample["object_paths"][0]
        fields = {item["setting_path"]: item["current_value"] for item in current["objects"][path]["editable_fields"]}
        assert fields[path + "/PlotLine/color"] == expected[sample["sample"]]["color"]
        assert fields[path + "/PlotLine/width"] == expected[sample["sample"]]["width"]
    for label in science_before["direct_labels"]:
        path = "/page1/graph1/" + label["name"]
        fields = {item["setting_path"]: item["current_value"] for item in current["objects"][path]["editable_fields"]}
        assert fields[path + "/Text/color"] == expected[label["label"]]["color"]
    assert {str(p): file_sha256(p) for p in source_project.rglob("*") if p.is_file()} == origin_before
    assert all(p.read_bytes() == contents for p, contents in raw.items())
    # Reusing already matching preferences completes without another approval.
    matching = cli("project", "style-capture", target_project, "--out", tmp_path / "matching")
    repeated = request(matching)
    repeated["expected_document_sha256"] = saved["result"]["document_sha256"]
    unchanged = task(tmp_path, "unchanged", repeated)
    assert unchanged["status"] == "complete" and unchanged["result"]["status"] == "unchanged"
    assert "preview" not in unchanged
    exported = task(tmp_path, "export", {"version": 1, "action": "export", "project": str(target_project)})
    assert exported["result"]["studio_run"]["ready_to_use"] is True
    assert file_sha256(Path(target_figure["document"])) == saved["result"]["document_sha256"]
