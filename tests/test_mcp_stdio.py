from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

import anyio
import pytest

pytest.importorskip("mcp")

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256


def _parameters(*, cli=False):
    return StdioServerParameters(command=str(REPO_ROOT / "skill/scripts/sciplot") if cli else sys.executable,
        args=["mcp"] if cli else ["-m", "sciplot_core.mcp_server"], cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")})


async def _call(client, name, arguments):
    result = await client.call_tool(name, arguments)
    assert not result.is_error, result.content
    return result.structured_content


@pytest.mark.comprehensive
def test_official_stdio_client_discovery_and_error_recovery():
    async def scenario():
        async with Client(_parameters(cli=True), read_timeout_seconds=60) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 14
            caps = await _call(client, "sciplot_capabilities", {})
            assert caps["transport"] == "mcp_stdio"
            assert caps["model_configuration_required"] is False
            error = await client.call_tool("sciplot_project_inspect", {"project": "/missing/sciplot"})
            assert error.is_error and error.structured_content["ready_to_use"] is False
            assert (await _call(client, "sciplot_capabilities", {}))["transport"] == "mcp_stdio"
            assert not (await client.list_resources()).resources

    anyio.run(scenario)


@pytest.mark.comprehensive
def test_stdio_native_preview_style_apply_export_and_new_connection(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance\nnm,a.u.\nA,A\n400,1\n450,3\n500,2\n", encoding="utf-8")
    raw = source.read_bytes()
    setup = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "studio", str(source),
        "--out", str(tmp_path / "Visible"), "--rule", "uvvis_spectrum", "--export", "pdf,tiff_300", "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
    assert setup.returncode == 0, setup.stdout + setup.stderr
    created = json.loads(setup.stdout)
    project, document = created["project_dir"], Path(created["document"])
    original = file_sha256(document)

    async def scenario():
        async with Client(_parameters(), read_timeout_seconds=180) as client:
            summary = await _call(client, "sciplot_project_inspect", {"project": project})
            figure_id = summary["primary_figure_id"]
            selected = await _call(client, "sciplot_project_inspect", {"project": project, "figure_id": figure_id})
            field = next(item for item in selected["selected_figure"]["objects"]["/page1/graph1/x"]["editable_fields"]
                if item["setting_path"].endswith("/Label/size"))
            operations = [{"op": "set_style", "object_path": "/page1/graph1/x", "setting_path": field["setting_path"],
                "expected_value": field["current_value"], "value": "9pt"}]
            review = await _call(client, "sciplot_edit_preview", {"project": project, "figure_id": figure_id,
                "expected_document_sha256": original, "operations": operations, "output_dir": str(tmp_path / "preview")})
            assert file_sha256(document) == original
            assert review["scientific_audit"]["status"] == "passed"
            resource = await client.read_resource(review["preview_resource"])
            assert base64.b64decode(resource.contents[0].blob).startswith(b"\x89PNG")
            image = await client.call_tool("sciplot_read_result", {"uri": review["preview_resource"]})
            assert image.content[1].type == "image"
            applied = await _call(client, "sciplot_edit_apply", {"project": project, "review_path": review["review_path"]})
            assert applied["status"] == "applied"
            retried = await _call(client, "sciplot_edit_apply", {"project": project, "review_path": review["review_path"]})
            assert retried["status"] == "already_applied"
            exported = await _call(client, "sciplot_export", {"project": project})
            assert exported["studio_run"]["ready_to_use"] is True
        async with Client(_parameters(), read_timeout_seconds=180) as client:
            resumed = await _call(client, "sciplot_project_inspect", {"project": project, "figure_id": figure_id})
            assert resumed["selected_figure"]["document_sha256"] == file_sha256(document) != original
            assert resumed["delivery"]["current"] is True
            unknown = await client.call_tool("sciplot_read_result", {"uri": review["preview_resource"]})
            assert unknown.is_error

    anyio.run(scenario)
    assert source.read_bytes() == raw


@pytest.mark.comprehensive
@pytest.mark.parametrize("defer_export", [False, True])
def test_stdio_local_task_creates_then_reviews_applies_and_exports_annotation(tmp_path, defer_export):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance\nnm,a.u.\nA,A\n400,1\n450,3\n500,2\n", encoding="utf-8")
    raw = source.read_bytes()

    async def scenario():
        async with Client(_parameters(), read_timeout_seconds=180) as client:
            created = await _call(client, "sciplot_task_start", {
                "request": {"version": 1, "action": "create", "source": str(source), "rule_id": "uvvis_spectrum"},
                "task_dir": str(tmp_path / "create_task"),
            })
            assert created["status"] == "complete"
            assert created["model_calls_by_sciplot"] == 0
            assert created["external_model_tokens"] is None
            assert created["result"]["studio_run"]["ready_to_use"] is True
            project = created["project"]
            found = await _call(client, "sciplot_task_find", {"source": str(source), "tasks_root": str(tmp_path)})
            assert found["match_count"] == 1 and found["scan_complete"]
            assert found["matches"][0]["project"] == project and found["matches"][0]["source_current"] is True
            inspected = await _call(client, "sciplot_project_inspect", {"project": project})
            figure = inspected["figures"][0]
            edited = await _call(client, "sciplot_task_start", {
                "request": {"version": 1, "action": "edit", "project": project,
                    "figure_id": figure["figure_id"], "expected_document_sha256": figure["document_sha256"],
                    "export": not defer_export,
                    "operations": [{"op": "add_reference_line", "id": "reference425", "parent_path": "/page1/graph1", "axis": "x", "value": 425, "unit": "nm"},
                                   {"op": "set_sample_style", "samples": ["A"], "style": {"color": "#3568C0"}}]},
                "task_dir": str(tmp_path / "edit_task"),
            })
            assert edited["status"] == "needs_review"
            png = await client.call_tool("sciplot_read_result", {"uri": edited["preview_resource"]})
            assert not png.is_error and png.content[1].type == "image"
            replacement = {"expected_operation_id": edited["operation_id"], "revise_operations": [
                {"op": "add_reference_line", "id": "reference450", "parent_path": "/page1/graph1", "axis": "x", "value": 450, "unit": "nm"},
                {"op": "set_sample_style", "samples": ["A"], "style": {"color": "#2A9D8F"}},
            ]}
            revised = await _call(client, "sciplot_task_resume", {"task": edited["task_dir"], "response": replacement})
            assert revised["status"] == "needs_review" and revised["preview_revision"] == 2
            assert file_sha256(Path(figure["document"])) == figure["document_sha256"]
            assert revised["preview_resource"] != edited["preview_resource"]
            second_png = await client.call_tool("sciplot_read_result", {"uri": revised["preview_resource"]})
            assert second_png.content[1].type == "image"
            task_record = Path(edited["task_dir"]) / "task.json"
            task_bytes = task_record.read_bytes()
            stale = await client.call_tool("sciplot_task_resume", {"task": edited["task_dir"], "response": {
                "accept_preview": True, "expected_operation_id": edited["operation_id"],
            }})
            assert stale.is_error and task_record.read_bytes() == task_bytes
            repeated = await _call(client, "sciplot_task_resume", {"task": edited["task_dir"], "response": replacement})
            assert repeated["operation_id"] == revised["operation_id"] and task_record.read_bytes() == task_bytes
            completed = await _call(client, "sciplot_task_resume", {"task": edited["task_dir"], "response": {
                "accept_preview": True, "expected_operation_id": revised["operation_id"],
            }})
            assert completed["status"] == "complete"
            if defer_export:
                assert completed["result"]["status"] == "saved"
                assert completed["result"]["export_performed"] is False
                pending = await _call(client, "sciplot_project_inspect", {"project": project})
                assert pending["delivery"]["current"] is False
                exported = await _call(client, "sciplot_export", {"project": project})
                assert exported["studio_run"]["ready_to_use"] is True
            else:
                assert completed["result"]["studio_run"]["ready_to_use"] is True
            current = await _call(client, "sciplot_task_inspect", {"task": edited["task_dir"]})
            assert current["current_project"]["delivery"]["current"] is True
            annotation = await _call(client, "sciplot_annotation_inspect", {"project": project, "figure_id": figure["figure_id"]})
            assert [item["id"] for item in annotation["annotations"]] == ["reference450"]
            stable = Path(figure["document"]).read_bytes()
            unchanged = await _call(client, "sciplot_task_start", {
                "request": {"version": 1, "action": "edit", "project": project, "figure_id": figure["figure_id"],
                    "expected_document_sha256": file_sha256(Path(figure["document"])), "export": False,
                    "operations": [{"op": "set_sample_style", "samples": ["A"], "style": {"color": "#2A9D8F"}}]},
                "task_dir": str(tmp_path / "unchanged_task"),
            })
            assert unchanged["status"] == "complete" and unchanged["result"]["status"] == "unchanged"
            assert "preview_resource" not in unchanged
            assert Path(figure["document"]).read_bytes() == stable
        async with Client(_parameters(), read_timeout_seconds=180) as client:
            found = await _call(client, "sciplot_task_find", {"source": str(source), "tasks_root": str(tmp_path)})
            recovered = await _call(client, "sciplot_project_inspect", {"project": found["matches"][0]["project"]})
            assert recovered["delivery"]["current"] is True

    anyio.run(scenario)
    assert source.read_bytes() == raw
