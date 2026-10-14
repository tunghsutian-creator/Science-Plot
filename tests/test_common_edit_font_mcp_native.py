"""Official MCP thread path: installed fonts succeed and invalid fonts are inert."""

import os
from pathlib import Path
import sys

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters
import pytest
from test_figure_document import request_for_figure

from sciplot_core._paths import REPO_ROOT
from sciplot_core.native_font_catalog import installed_font_families
from sciplot_core.plot_engine.storage import load_head, read


@pytest.mark.comprehensive
def test_official_mcp_font_edit_keeps_default_mac_server_alive_and_rejects_unavailable_font(tmp_path):
    families = installed_font_families()
    if sys.platform == "darwin":
        assert "Helvetica" in families, "This Mac native acceptance requires its actual installed Helvetica family."
        family = "Helvetica"
    else:
        family = next((name for name in ("Liberation Sans", "DejaVu Sans") if name in families), families[0])
    request = request_for_figure(tmp_path)
    request["out"] = str(tmp_path / "visible")
    request["template_definition"]["figure_spec"]["annotations"] = [{
        "id": "annotation:note", "space": "view", "view_id": "view:A", "x": .5, "y": .5,
        "text": "N", "visible": True, "style": {"font_size_pt": 6., "color": "#123456"}}]
    source = tmp_path / "figure.csv"
    original_source = source.read_bytes()
    environment = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src"),
                   "SCIPLOT_REPO": str(REPO_ROOT), "SCIPLOT_SOURCE_ROOT": str(REPO_ROOT / "src")}
    if sys.platform == "darwin":
        # The MCP server uses default Cocoa; its native children retain their
        # existing worker environment and do not initialize Qt in this server.
        environment.pop("QT_QPA_PLATFORM", None)
    parameters = StdioServerParameters(command=str(REPO_ROOT / "skill/scripts/sciplot"), args=["mcp"],
                                       cwd=REPO_ROOT, env=environment)
    async def scenario():
        async with Client(parameters, read_timeout_seconds=120) as client:
            created = await client.call_tool("sciplot_plot_create", {"request": request})
            assert not created.is_error, created.content
            root = Path(created.structured_content["plot"])
            initial = load_head(root)
            original_ir = read(Path(initial["binding"]["ir_path"]))
            missing = tmp_path / "invalid-font-entry"
            invalid = await client.call_tool("sciplot_task_edit", {"target": str(root), "font_family": "SciPlot missing font 92831", "task_dir": str(missing)})
            assert invalid.is_error and not missing.exists()
            assert load_head(root) == initial and source.read_bytes() == original_source
            assert not (await client.call_tool("sciplot_capabilities", {})).is_error
            arguments = {"target": str(root), "font_family": family, "task_dir": str(tmp_path / "valid-font-entry")}
            edited = await client.call_tool("sciplot_task_edit", arguments)
            assert not edited.is_error, edited.content
            result = edited.structured_content
            assert result["status"] == "complete" and result["ready_to_use"]
            assert result["doctor"]["status"] == "ready"
            assert result["revision"] == 1 and result["scientific_hash"] == initial["document"]["scientific_hash"]
            after = load_head(root)
            ir = read(Path(after["binding"]["ir_path"]))
            assert ir["datasets"] == original_ir["datasets"] and ir["scales"] == original_ir["scales"]
            typography = [axis["style"] for view in ir["views"] for axis in view["axes"]]
            typography += [view["panel_label_style"] for view in ir["views"]]
            typography += [item["style"] for item in ir["guides"] + ir["annotations"]]
            assert {style["font_family"] for style in typography} == {family}
            assert ir["annotations"][0]["style"]["font_size_pt"] == 6.
            assert ir["annotations"][0]["style"]["color"] == "#123456"
            assert result["publication_qa"]["status"] == "passed"
            assert all(Path(item["path"]).is_file() for item in result["exports"])
            replay = await client.call_tool("sciplot_task_edit", arguments)
            assert not replay.is_error and replay.structured_content["replayed"]
            assert load_head(root) == after and source.read_bytes() == original_source
            assert not (await client.call_tool("sciplot_capabilities", {})).is_error
            assert (await client.list_tools()).tools
    anyio.run(scenario)
