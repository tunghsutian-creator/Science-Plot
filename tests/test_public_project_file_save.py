"""Public ordinary XY can be relocated as one complete .sciplot project."""

from hashlib import sha256
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
from sciplot_core.plot_protocol.paths import read_owner
from sciplot_core.project_lifecycle.attachment_index import read_index
from sciplot_core.project_lifecycle.project_file_summary import project_file_figure
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.veusz_runtime import veusz_worker_environment


@pytest.mark.comprehensive
def test_public_ordinary_xy_project_file_save_keeps_all_members_and_history(tmp_path):
    import anyio
    from mcp import Client
    from socket_fixture_helpers import socket_directory
    from test_figure_document import request_for_figure
    from test_mcp_stdio import _parameters

    root = tmp_path.resolve()
    original = root / "old working directory"
    original.mkdir()
    source = original / "cooling.csv"
    raw = b"Temperature,Heat Flow\nC,W/g\nSample Z,Sample Z\n66,-0.023\n61,0.008\n61,\n53,-0.016\n"
    source.write_bytes(raw)
    ordinary_request = original / "ordinary.json"
    ordinary_request.write_text(json.dumps({"version": 1, "action": "create", "sources": [str(source)],
        "intent": {"x": {"quantity": "temperature"}, "y": {"quantity": "heat_flow"}},
        "out": str(original / "paper"), "formats": ["pdf"]}))

    env = {**veusz_worker_environment(), "SCIPLOT_PYTHON": sys.executable, "MPLCONFIGDIR": str(root / "mpl")}

    def cli(*args, failure=None):
        run = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, args), "--json"],
                             env=env, cwd=root, capture_output=True, text=True, timeout=90, check=False)
        assert run.returncode == int(failure is not None), run.stdout + run.stderr
        result = json.loads(run.stdout)
        if failure:
            assert result["reason_code"] == failure, result
        return result

    created = cli("task", "start", "--request", ordinary_request, "--task-dir", original / "task")
    assert created["ready_to_use"] and created["scientific_presentation"]["rule_id"] == "ordinary_xy", created
    plot = Path(created["project"])
    first = cli("plot", "open", plot, "--scope", "summary", "--direct")
    assert first["scientific_hash"] == created["result"]["scientific_hash"] and first["revision"] == 0
    # The test needs the owning Store to create a second independent figure there.
    store_root = plot.parent.parent
    store = FileProjectStore(store_root)
    directory = root / "default directory bundle"
    previous = cli("project", "bundle-export", store_root, "--out", directory)
    assert directory.is_dir() and (directory / "bundle.json").is_file()
    assert set(previous) == {"kind", "version", "status", "project", "bundle", "project_id", "generation",
                             "mode", "independent_project", "host_grants_included", "next_step"}

    second_request = original / "second.json"
    second_request.write_text(json.dumps(request_for_figure(original)))
    second = cli("plot", "create", "--request", second_request, "--project", store_root, "--direct")
    assert second["ready_to_use"] and second["plot_id"] != first["plot_id"]
    intent = original / "edit.json"
    axis = next(target for target, contract in first["edit_targets"].items() if "axis.label" in contract["properties"])
    intent.write_text(json.dumps({"mode": "apply", "plot_id": first["plot_id"], "base_revision": 0,
        "idempotency_key": "axis-label-before-relocation", "property": "axis.label", "target_id": axis,
        "value": "Cooling temperature (C)"}))
    updated = cli("plot", "intent", plot, "--request", intent, "--direct")
    assert updated["ready_to_use"] and updated["revision"] == 1 and updated["scientific_hash"] == first["scientific_hash"]
    snapshot = store.snapshot()
    assert snapshot["generation"] != previous["generation"] and snapshot["project_id"] == previous["project_id"]

    archive = root / "论文完整项目.sciplot"
    refused = root / "not written.sciplot"
    cli("project", "bundle-export", plot, "--single-file", "--expected-generation", previous["generation"],
        "--out", refused, failure="project_bundle_generation_conflict")
    assert not refused.exists() and source.read_bytes() == raw and store.snapshot() == snapshot
    cli("project", "bundle-export", plot, "--out", refused, failure="project_bundle_store_required")
    alias = original / "linked project handle"
    alias.symlink_to(plot, target_is_directory=True)
    cli("project", "bundle-export", alias, "--single-file", "--out", refused,
        failure="project_bundle_store_required")
    cli("project", "bundle-export", plot.with_name("unknown"), "--single-file", "--out", refused,
        failure="project_bundle_store_required")
    cli("project", "bundle-export", plot, "--single-file", "--out", root / "not an archive",
        failure="project_file_destination_required")
    saved = cli("project", "bundle-export", plot, "--single-file", "--expected-generation", snapshot["generation"],
                "--out", archive)
    assert saved == {"kind": "sciplot_project_bundle_result", "version": 1, "status": "exported",
        "project": str(plot), "bundle": str(archive), "project_id": snapshot["project_id"],
        "generation": snapshot["generation"], "mode": "same_project_relocation", "independent_project": False,
        "host_grants_included": False, "bundle_format": "single_file", "whole_project": True,
        "project_file": str(archive), "sha256": file_sha256(archive),
        "next_step": {"action": "project.open", "arguments": {"target": str(archive), "description": {"scope": "summary"}}}}
    cli("project", "bundle-export", plot, "--single-file", "--out", archive,
        failure="project_bundle_destination_exists")
    assert file_sha256(archive) == saved["sha256"] and source.read_bytes() == raw and store.snapshot() == snapshot

    other_archive = root / "MCP relocation.sciplot"
    with socket_directory(prefix="sp-public-file-", dir="/tmp") as directory:
        socket = Path(directory) / "engine.sock"
        parameters = _parameters(cli=True, profile="daily")
        parameters.env = {**(parameters.env or {}), **env, "SCIPLOT_ENGINE_SOCKET": str(socket)}

        async def public_round_trip():
            async with Client(parameters, read_timeout_seconds=90) as client:
                packed = await client.call_tool("sciplot_project_bundle_export", {"project": str(plot),
                    "output_dir": str(other_archive), "single_file": True, "expected_generation": snapshot["generation"]})
                assert not packed.is_error, packed.content
                assert packed.structured_content == {**saved, "bundle": str(other_archive),
                    "project_file": str(other_archive), "sha256": file_sha256(other_archive),
                    "next_step": {"action": "project.open",
                                  "arguments": {"target": str(other_archive), "description": {"scope": "summary"}}}}
                shutil.rmtree(original)
                route = packed.structured_content["next_step"]
                never_created = root / "wrong import"
                mistaken_import = await client.call_tool("sciplot_project_bundle_import", {
                    "bundle": str(other_archive), "output_dir": str(never_created)})
                assert mistaken_import.is_error and mistaken_import.structured_content["error"]["code"] == "project_bundle_required"
                assert mistaken_import.structured_content["repair"] == route
                assert not never_created.exists()
                no_selection = await client.call_tool("sciplot_project_open", route["arguments"])
                assert no_selection.is_error
                assert no_selection.structured_content["error"]["code"] == "project_file_figure_ambiguous"
                for figure in (updated, second):
                    opened = await client.call_tool("sciplot_project_open", {**route["arguments"], "figure_id": figure["plot_id"]})
                    assert not opened.is_error, opened.content
                    payload = opened.structured_content
                    assert payload["project_id"] == snapshot["project_id"] and payload["project_file"] == str(other_archive)
                    assert all(payload[key] == figure[key] for key in ("plot_id", "revision", "scientific_hash", "presentation_hash"))

        try:
            anyio.run(public_round_trip)
        finally:
            if socket.exists():
                os.kill(read_owner(socket)["pid"], signal.SIGTERM)

    opened = cli("plot", "open", archive, "--direct", "--figure", first["plot_id"])
    assert opened["revision"] == 1 and opened["scientific_hash"] == first["scientific_hash"]
    with project_file_figure(archive, first["plot_id"]) as (session, owner, _current):
        previous_figure = owner.load_revision(owner.attachment.root, 0)["document"]
        assert previous_figure["plot_id"] == first["plot_id"] and previous_figure["presentation_hash"] == first["presentation_hash"]
        assert session.project_id == snapshot["project_id"] and session.store.snapshot()["generation"] == snapshot["generation"]
        assert {entry["plot_id"] for entry in read_index(session.store)["attachments"].values()} == {first["plot_id"], second["plot_id"]}
        ((source_id, version),) = [(identifier, version) for identifier, versions in snapshot["sources"].items()
                                   for version, item in versions.items() if item["sha256"] == sha256(raw).hexdigest()]
        assert session.store.resolve_source(source_id, version).read_bytes() == raw
        assert session.store.observe_members((), generation=previous["generation"], projection=False).selected["project_id"] == saved["project_id"]
    assert not original.exists() and file_sha256(archive) == saved["sha256"]
