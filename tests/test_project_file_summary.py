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
            axes = request["template_definition"]["figure_spec"]["views"][0]["axes"]
            axes[0]["label"] = f"Frequency {label} (Hz)"
            if figures:
                axes[0]["id"] = "axis:x"
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
                "edit_targets": {
                    "axis:x": {"kind": "axis", "label": "Frequency 乙 (Hz)", "properties": ["axis.label", "axis.ticks"]},
                    "axis:yl": {"kind": "axis", "label": "Modulus (Pa)", "properties": ["axis.label", "axis.ticks"]},
                },
                **{key: selected[key] for key in ("plot_id", "revision", "scientific_hash", "presentation_hash")}}

    def cli(target, *flags, action="open", returncode=0):
        run = subprocess.run(
            [str(REPO_ROOT / "skill/scripts/sciplot"), "plot", action, str(target), "--direct", "--json", *flags],
            env=read_env, cwd=root, capture_output=True, text=True, timeout=60, check=False,
        )
        assert run.returncode == returncode, run.stdout + run.stderr
        assert not list(scratch.iterdir())
        return json.loads(run.stdout)

    summary = cli(moved.relative_to(root), "--scope", "summary", "--figure", selected["plot_id"])
    assert summary == expected
    assert cli(moved, "--figure", figures[0]["plot_id"])["edit_targets"]["axis:xb"]["label"] == "Frequency 甲 (Hz)"
    no_selection = cli(moved, returncode=1)
    assert no_selection["reason_code"] == "project_file_figure_ambiguous"
    bad_selection = cli(moved, "--figure", "plot:unknown", returncode=1)
    assert bad_selection["reason_code"] == "project_file_figure_not_found"
    repair = no_selection["repair"]
    assert bad_selection["repair"] == repair
    assert repair["action"] == "select_figure"
    assert repair["project_file"] == str(moved) and repair["project_id"] == snapshot["project_id"]
    choices = {item["plot_id"]: item for item in repair["figures"]}
    assert set(choices) == {item["plot_id"] for item in figures}
    selected_arguments = choices[selected["plot_id"]]["open_arguments"]
    assert selected_arguments == {"target": str(moved), "figure_id": selected["plot_id"],
                                  "description": {"scope": "summary"}}
    target, axis = next((target, axis) for target, axis in summary["edit_targets"].items()
                        if axis["label"] == "Frequency 乙 (Hz)")
    plan_request = {"mode": "plan", "plot_id": summary["plot_id"], "base_revision": summary["revision"],
                    "idempotency_key": "selected-axis", "target_id": target, "property": axis["properties"][0],
                    "value": "Revised frequency (Hz)"}
    plan_path = root / "plan.json"
    plan_path.write_text(json.dumps(plan_request))
    plan = cli(summary["project_file"], "--request", str(plan_path), action="intent")
    assert plan["status"] == "ready" and plan["before"] == axis["label"] and plan["saved"] is False
    assert plan["target_context"]["unit"] == "Hz"
    assert str(scratch) not in str(plan) and str(original) not in str(plan)

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
                rejected = await client.call_tool("sciplot_project_open", {"target": str(moved),
                                                                          "figure_id": "plot:unknown"})
                assert rejected.is_error and rejected.structured_content["repair"] == repair
                mcp_choice = next(choice for choice in rejected.structured_content["repair"]["figures"]
                                  if choice["plot_id"] == selected["plot_id"])
                result = await client.call_tool("sciplot_project_open", mcp_choice["open_arguments"])
                assert not result.is_error, result.content
                assert result.structured_content == expected
                planned = await client.call_tool("sciplot_plot_intent",
                                                 {"plot": result.structured_content["project_file"],
                                                  "request": plan_request})
                assert not planned.is_error, planned.content
                assert planned.structured_content == plan
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
