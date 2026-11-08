"""Public transports on a real Store/PDF fixture, without claiming native QA."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core._paths import REPO_ROOT
from test_pdf_review_binding import annotate, current as current


@pytest.mark.parametrize("transport", ["cli", "mcp"])
def test_pdf_review_public_transports_preserve_reference_facts_and_originals(current, tmp_path, transport):
    project, original = current
    original_bytes = original.read_bytes()
    source = project / "source/data.csv"
    source_bytes = source.read_bytes()
    output = tmp_path / "review"

    def check_reference(created, result):
        assert result["review_id"] == created["review_id"]
        assert result["document"] == created["document"]
        assert result["annotation_count"] == 2
        assert result["page_count"] == 1
        assert result["pages"] == [{"page_index": 0, "rect_pt": [0.0, 0.0, 240.0, 180.0],
                                    "media_box_pt": [0.0, 0.0, 240.0, 180.0],
                                    "crop_box_pt": [0.0, 0.0, 240.0, 180.0], "rotation": 0}]
        assert result["page_rect_coordinate_space"] == "pymupdf_rotated_visible_page_points"
        assert result["command_authority"] is result["scientific_authority"] is False
        assert result["outbound_request_sent"] is False
        assert result["annotations"][0]["text"] == "Reference only; keep measurements unchanged"

    if transport == "cli":
        def cli(*args):
            process = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "project", *map(str, args), "--json"],
                                     cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
            assert process.returncode == 0, process.stdout + process.stderr
            return json.loads(process.stdout)

        created = cli("pdf-review-create", project, "--out", output)
        annotate(Path(created["review_pdf"]), "Reference only; keep measurements unchanged")
        result = cli("pdf-review-read", project, created["review_id"])
        check_reference(created, result)
    else:
        pytest.importorskip("mcp")
        import anyio
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters, stdio_client

        parameters = StdioServerParameters(command=sys.executable, args=["-m", "sciplot_core.mcp_server"],
                                          cwd=REPO_ROOT, env=dict(os.environ))

        async def scenario():
            # Own a real diagnostic FD; the SDK's default stderr can have been
            # captured at import time by an earlier capsys-based test.
            with (tmp_path / "mcp-stderr.log").open("w") as error_log:
                async with Client(stdio_client(parameters, errlog=error_log), read_timeout_seconds=60) as client:
                    created_result = await client.call_tool("sciplot_pdf_review_create",
                        {"project": str(project), "output_dir": str(output)})
                    assert not created_result.is_error, created_result.content
                    created = created_result.structured_content
                    annotate(Path(created["review_pdf"]), "Reference only; keep measurements unchanged")
                async with Client(stdio_client(parameters, errlog=error_log), read_timeout_seconds=60) as client:
                    read_result = await client.call_tool("sciplot_pdf_review_read",
                        {"project": str(project), "review_id": created["review_id"]})
                    assert not read_result.is_error, read_result.content
                    check_reference(created, read_result.structured_content)

        anyio.run(scenario)
    assert original.read_bytes() == original_bytes
    assert source.read_bytes() == source_bytes
