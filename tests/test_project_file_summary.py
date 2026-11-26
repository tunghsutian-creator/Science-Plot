"""Existing public transports observe the same saved archive without a renderer."""

from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_protocol.paths import read_owner
from sciplot_core.project_lifecycle.project_file import create_project_file
from sciplot_core.project_store.repository import FileProjectStore


@pytest.mark.comprehensive
def test_relocated_project_file_opens_read_only_in_cli_and_daily_mcp(tmp_path):
    import anyio
    from mcp import Client
    from socket_fixture_helpers import socket_directory
    from test_figure_document import request_for_figure
    from test_mcp_stdio import _parameters

    root = tmp_path.resolve()
    original = root / "original"
    original.mkdir()
    project = original / "project"
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    with closing(PlotService()) as service:
        figures = []
        for label in ("甲", "乙"):
            source = original / label
            source.mkdir()
            request = request_for_figure(source)
            request["idempotency_key"] = "first" if not figures else "second"
            saved = service.create(request, project=store.root)
            assert saved["ready_to_use"] and saved["revision"] == 0
            figures.append(saved)
    selected = figures[1]
    assert selected["plot_id"] != figures[0]["plot_id"]
    snapshot = store.snapshot()
    archive = original / "模量数据.sciplot"
    receipt = create_project_file(archive, store, expected_generation=snapshot["generation"])
    folder = root / "移入 (测试)"
    folder.mkdir()
    moved = archive.rename(folder / "新料 1.14.sciplot")
    shutil.rmtree(original)

    scratch = root / "scratch"
    scratch.mkdir()
    read_env = {**os.environ, "TMPDIR": str(scratch), "SCIPLOT_PYTHON": sys.executable,
                "MPLCONFIGDIR": str(root / "mpl"),
                "SCIPLOT_VEUSZ_ROOT": str(root / "absent-renderer")}
    expected = {"kind": "sciplot_project_file_summary", "version": 1, "read_only": True,
                "project_file": str(moved), "project_id": snapshot["project_id"],
                **{key: selected[key] for key in ("plot_id", "revision", "scientific_hash", "presentation_hash")}}

    def cli(target, *flags, returncode=0):
        run = subprocess.run(
            [str(REPO_ROOT / "skill/scripts/sciplot"), "plot", "open", str(target), "--direct", "--json", *flags],
            env=read_env, cwd=root, capture_output=True, text=True, timeout=60, check=False,
        )
        assert run.returncode == returncode, run.stdout + run.stderr
        assert not list(scratch.iterdir())
        return json.loads(run.stdout)

    assert cli(moved.relative_to(root),
               "--scope", "summary", "--figure", selected["plot_id"]) == expected
    assert cli(moved, returncode=1)["reason_code"] == "project_file_figure_ambiguous"

    aliases = root / "aliases"
    aliases.mkdir()
    alias = aliases / "alias.sciplot"
    alias.symlink_to(moved)
    assert cli(alias, "--figure", selected["plot_id"], returncode=1)["reason_code"] == "project_file_invalid"

    with socket_directory(prefix="sp-file-", dir="/tmp") as directory:
        socket = Path(directory) / "engine.sock"
        parameters = _parameters(cli=True, profile="daily")
        parameters.env = {**(parameters.env or {}), **read_env, "SCIPLOT_ENGINE_SOCKET": str(socket)}

        async def check_mcp():
            async with Client(parameters, read_timeout_seconds=60) as client:
                args = {"target": str(moved), "figure_id": selected["plot_id"]}
                result = await client.call_tool("sciplot_project_open", args)
                assert not result.is_error, result.content
                assert result.structured_content == expected
                assert not (await client.list_resources()).resources
                for arguments, code in (
                    ({**args, "figure_id": "plot:unknown"}, "project_file_figure_not_found"),
                    ({**args, "description": {"scope": "edit", "target": "axis:xb", "property": "axis.label"}},
                     "project_file_summary_only"),
                    ({**args, "target": str(alias)}, "project_file_invalid"),
                ):
                    rejected = await client.call_tool("sciplot_project_open", arguments)
                    assert rejected.is_error and rejected.structured_content["error"]["code"] == code
                    assert str(scratch) not in str(rejected.structured_content)
                assert not list(scratch.iterdir())

        try:
            anyio.run(check_mcp)
        finally:
            if socket.exists():
                os.kill(read_owner(socket)["pid"], signal.SIGTERM)

    assert not original.exists()
    assert list(folder.iterdir()) == [moved]
    assert file_sha256(moved) == receipt.sha256
