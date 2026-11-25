"""Export only plotted data through the normal current-figure interface."""

import csv
import json
import os
from pathlib import Path
import signal
import subprocess

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_protocol.paths import read_owner


@pytest.mark.comprehensive
def test_saved_figure_exports_only_exact_plotted_csvs_via_cli_and_daily_mcp(tmp_path):
    import anyio
    from mcp import Client
    from socket_fixture_helpers import socket_directory
    from test_mcp_stdio import _parameters
    from test_task_control_native import _cli
    from test_task_semantic_creation import _single_table_spectral_control

    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.project_lifecycle.context import project_query, read, repository_scope
    from sciplot_core.project_store import FileProjectStore

    source, intent = _single_table_spectral_control(tmp_path)
    intent["labels"] = ["Same label", "Same label"]
    raw_hash = file_sha256(source)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({
        "version": 1, "action": "create", "sources": [str(source)], "intent": intent,
        "formats": ["pdf"], "out": str(tmp_path / "first PDF"),
    }))
    first = _cli("task", "start", "--request", request, "--task-dir", tmp_path / "task")
    assert first["ready_to_use"] is True and first["result"]["revision"] == 0, first
    saved = first["result"]
    plot = Path(saved["plot"])
    cache_path = plot / "export-cache.json"
    def publication():
        service = PlotService(read_only_legacy=True)
        try:
            with repository_scope(service.repository, capabilities=service.capabilities), project_query(plot):
                return read(cache_path)
        finally:
            service.close()

    cache = publication()
    store = FileProjectStore(plot.parent.parent)
    generation = store.snapshot()["generation"]
    original = {source: raw_hash, **{Path(path): sha for path, sha in cache["artifact_files"].items()}}
    assert all(file_sha256(path) == sha for path, sha in original.items())
    assert list((tmp_path / "first PDF").iterdir())[0].suffix == ".pdf"

    def cli(directory, revision=0, returncode=0):
        completed = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "plot", "export", str(plot),
            "--direct", "--plotted-csv", "--output-dir", str(directory), "--plot-id", saved["plot_id"],
            "--revision", str(revision), "--json"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=90, check=False)
        assert completed.returncode == returncode, (completed.stdout, completed.stderr)
        return json.loads(completed.stdout)

    def check(result, output_dir):
        assert result["status"] == "exported" and result["coordinate_space"] == "scientific_layer_inputs"
        assert {key: result[key] for key in ("plot_id", "revision", "scientific_hash", "presentation_hash")} == {
            key: saved[key] for key in ("plot_id", "revision", "scientific_hash", "presentation_hash")}
        assert result["ir_sha256"] == cache["export"]["native_export_audit"]["ir_sha256"]
        by_sample = {item["layers"][0]["sample"]: item for item in result["exports"]}
        assert set(by_sample) == {"Resin blue", "Resin red"}
        assert len({row["dataset_id"] for row in by_sample.values()}) == len(by_sample)
        assert len({row["layers"][0]["layer_id"] for row in by_sample.values()}) == len(by_sample)
        assert set(output_dir.resolve().iterdir()) == {Path(row["path"]) for row in by_sample.values()}
        for sample, values in {"Resin blue": {"x": [700, 2600, 3900], "y": [84, 62, 79]},
                               "Resin red": {"x": [650, 2500, 3800], "y": [89, 73, 91]}}.items():
            row = by_sample[sample]
            path = Path(row["path"])
            assert row["format"] == "plotted_csv" and path.suffix == ".csv"
            assert row["layers"][0]["label"] == "Same label"
            assert row["layers"][0]["mappings"] == {"x": "x", "y": "y"}
            assert file_sha256(path) == row["sha256"] and row["row_count"] == 3
            assert {item["id"]: item["unit"] for item in row["columns"]} == {"x": "cm^-1", "y": "%"}
            raw, = row["provenance"]["sources"]
            assert raw["sha256"] == raw_hash and raw["table_selection"]["sample_row"] == 2
            assert set(raw["column_indices"].values()) == ({"Resin blue": {0, 1}, "Resin red": {2, 3}}[sample])
            with path.open(newline="") as stream:
                header, *rows = csv.reader(stream)
            assert header == [item["label"] for item in row["columns"]]
            assert [list(map(float, col)) for col in zip(*rows, strict=True)] == [values[id_] for id_ in row["column_ids"]]
        return {sample: row["sha256"] for sample, row in by_sample.items()}

    cli_out = tmp_path / "just data CLI"
    expected = check(cli(cli_out), cli_out)
    assert cli(cli_out, returncode=1)["reason_code"] == "figure_handoff_destination_exists"
    stale_out = tmp_path / "stale revision"
    assert cli(stale_out, revision=1, returncode=1)["reason_code"] == "figure_handoff_revision_conflict"
    assert not stale_out.exists()

    mcp_out = tmp_path / "just data MCP"
    with socket_directory(prefix="sp-data-", dir="/tmp") as runtime:
        socket = Path(runtime) / "engine.sock"
        parameters = _parameters(cli=True, profile="daily")
        parameters.env = {**(parameters.env or {}), "SCIPLOT_ENGINE_SOCKET": str(socket)}

        async def scenario():
            async with Client(parameters, read_timeout_seconds=90) as client:
                call = {"plot": str(plot), "handoff": {"output_dir": str(mcp_out), "plot_id": saved["plot_id"],
                                                       "revision": saved["revision"], "formats": ["plotted_csv"]}}
                result = await client.call_tool("sciplot_plot_export", call)
                assert not result.is_error, result.content
                assert check(result.structured_content, mcp_out) == expected
                mixed = tmp_path / "mixed formats"
                illegal = await client.call_tool("sciplot_plot_export", {**call, "handoff": {
                    **call["handoff"], "formats": ["plotted_csv", "pdf"], "output_dir": str(mixed)}})
                assert illegal.is_error and not mixed.exists()

        try:
            anyio.run(scenario)
        finally:
            if socket.exists():
                os.kill(read_owner(socket)["pid"], signal.SIGTERM)
    assert all(file_sha256(path) == sha for path, sha in original.items())
    assert publication() == cache and store.snapshot()["generation"] == generation
