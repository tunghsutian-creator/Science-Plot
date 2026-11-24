"""Managed authority survives artifact deletion through the public thin clients."""

from socket_fixture_helpers import socket_directory

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
from time import perf_counter

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters
import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_protocol.client import _ping, call
from sciplot_core.plot_protocol.paths import read_owner
from managed_plot_helpers import request_for_source


@pytest.mark.comprehensive
@pytest.mark.parametrize("figure", [False, True], ids=["cartesian-v1", "figure-v2"])
def test_public_cli_create_and_mcp_rebuild_from_canonical_document(tmp_path, figure):
    from test_figure_document import request_for_figure
    from sciplot_core.project_lifecycle.context import repository_scope
    from sciplot_core.project_lifecycle.repository import digest
    from sciplot_core.project_lifecycle.repository_router import ComposedProjectRepository
    from sciplot_core.project_store.repository import FileProjectStore

    request = request_for_figure(tmp_path) if figure else request_for_source(tmp_path)
    source = Path(request["data_binding"]["data_sources"][0]["path"]).resolve()
    source_hash = file_sha256(source)
    historical_id = digest([str(source.parent), request["idempotency_key"]])[:24]
    visible_output = source.parent / (source.stem + "_SciPlot") / ("plot_" + historical_id)
    request_file = tmp_path / "managed-create.json"
    request_file.write_text(json.dumps(request))
    timings = []
    with socket_directory(prefix="spmanaged-", dir="/tmp") as temporary:
        socket = Path(temporary) / "engine.sock"
        environment = {**os.environ, "SCIPLOT_ENGINE_SOCKET": str(socket)}
        engine_pid = None
        try:
            started = perf_counter()
            process = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "plot", "create",
                "--request", str(request_file), "--json"], cwd=REPO_ROOT, env=environment,
                capture_output=True, text=True, timeout=180)
            timings.append({"case": "cli_managed_create_cold", "seconds": round(perf_counter() - started, 6)})
            assert process.returncode == 0, process.stdout + process.stderr
            created = json.loads(process.stdout)
            assert created["ready_to_use"] and created["plot_type"] == "ManagedPlot", created
            engine_pid = read_owner(socket)["pid"]
            root = Path(created["plot"])
            opened = call("project.open", {"target": str(root)}, socket_path=socket)
            described = call("plot.describe", {"plot": str(root)}, socket_path=socket)
            assert opened["plot_id"] == described["plot_id"] == created["plot_id"]
            assert described["authority"]["source_of_truth"] == "sciplot_document"
            assert described["authority"]["rebuild_from_document"] is True
            if figure:
                assert described["plot_ir_version"] == 2 and created["publication_qa"]["native_text_checked"]
            assert root.parent.name == ".sciplot_semantic"
            store = FileProjectStore(root.parent.parent)
            repository = ComposedProjectRepository()
            with repository_scope(repository), repository.query_scope(root):
                binding = repository.load_head(root)["binding"]
                creation = repository.read(root / "managed-creation.json")
            assert creation["request"] == request and creation["request_hash"] == digest(request)
            assert "out" not in creation["request"]
            private = Path(binding["document"])
            assert private.is_relative_to(store.root / ".sciplot_store")
            native = visible_output / "artifacts" / binding["ir_hash"] / "document.vsz"
            assert next(Path(item["path"]) for item in created["exports"] if item["format"] == "vsz") == native
            assert file_sha256(native) == file_sha256(private)
            ir_path = Path(binding["ir_path"])
            ir = json.loads(ir_path.read_text())
            pixels = (native.parent / "preview.png").read_bytes()
            native_state = json.loads((native.parent / "build.json").read_text())["native_state_hash"]
            authority_names = {(path.relative_to(store.root)).as_posix() for path in (
                root / "head.json", root / "managed-creation.json", Path(binding["canonical_document"]))}
            revision_prefix = (root / "revisions").relative_to(store.root).as_posix() + "/"

            def authority():
                files = store.snapshot()["files"]
                revisions = {name for name in files if name.startswith(revision_prefix)}
                assert len(revisions) == 1
                return {name: files[name]["sha256"] for name in authority_names | revisions}

            authority_before = authority()
            shutil.rmtree(visible_output)
            shutil.rmtree(Path(binding["output"]))
            shutil.rmtree(ir_path.parent)
            dirty = call("plot.describe", {"plot": str(root)}, socket_path=socket)
            assert dirty["artifact_status"] == "missing" and dirty["next_step"]["action"] == "plot.export"

            async def rebuild_and_replay():
                parameters = StdioServerParameters(command=str(REPO_ROOT / "skill/scripts/sciplot"),
                    args=["mcp"], cwd=REPO_ROOT, env=environment)
                async with Client(parameters, read_timeout_seconds=180) as mcp:
                    started = perf_counter()
                    result = await mcp.call_tool("sciplot_plot_export", {"plot": str(root)})
                    timings.append({"case": "mcp_managed_rebuild_warm", "seconds": round(perf_counter() - started, 6)})
                    assert not result.is_error, result.content
                    rebuilt = result.structured_content
                    started = perf_counter()
                    replay = await mcp.call_tool("sciplot_plot_create", {"request": request})
                    timings.append({"case": "mcp_managed_create_same_key", "seconds": round(perf_counter() - started, 6)})
                    assert not replay.is_error, replay.content
                    return rebuilt, replay.structured_content

            rebuilt, replay = anyio.run(rebuild_and_replay)
            for receipt in (rebuilt, replay):
                assert receipt["ready_to_use"] and receipt["revision"] == 0, receipt
                assert receipt["plot_id"] == created["plot_id"]
                assert receipt["scientific_hash"] == created["scientific_hash"]
                assert receipt["presentation_hash"] == created["presentation_hash"]
                assert next(Path(item["path"]) for item in receipt["exports"] if item["format"] == "vsz") == native
            assert json.loads(ir_path.read_text()) == ir
            assert (native.parent / "preview.png").read_bytes() == pixels
            assert json.loads((native.parent / "build.json").read_text())["native_state_hash"] == native_state
            assert authority() == authority_before
            current = call("plot.describe", {"plot": str(root)}, socket_path=socket)
            assert current["status"] == "current" and current["dependencies"]["invalidated"] == []
            assert _ping(socket, 3)["pid"] == engine_pid and file_sha256(source) == source_hash
            evidence = REPO_ROOT / (".tmp_verify/figure_grammar_20261008/protocol_acceptance.json" if figure else
                                    ".tmp_verify/managed_architecture_20261008/protocol_acceptance.json")
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(json.dumps({"status": "passed", "transport": "CLI + official MCP -> persistent UNIX engine",
                "plot": str(root), "plot_type": "ManagedPlot", "server_pid": engine_pid, "server_pid_stable": True,
                "source_unchanged": True, "canonical_authority_unchanged": True, "scientific_hash_unchanged": True,
                "generated_native_ir_preview_exports_deleted": True, "rebuilt_from_canonical": True,
                "ir_equal": True, "pixels_equal": True, "native_state_equal": True, "revision": 0,
                "same_key_creation_reuses_document": True, "measurements": timings,
                "measurement_scope": "Local calls only; CLI includes startup, MCP excludes initialization. No AI latency measured."}, indent=2))
        finally:
            if engine_pid is None and socket.exists():
                engine_pid = read_owner(socket)["pid"]
            if engine_pid is not None:
                os.kill(engine_pid, signal.SIGTERM)


@pytest.mark.comprehensive
def test_public_expert_output_is_projection_for_create_patch_and_export(tmp_path):
    from managed_plot_helpers import patch
    from sciplot_core.plot_protocol.rpc import RemoteError
    from sciplot_core.project_lifecycle.context import repository_scope
    from sciplot_core.project_lifecycle.repository_router import ComposedProjectRepository
    from sciplot_core.studio_core.source_update_files import file_inventory

    originals = tmp_path / "originals"
    originals.mkdir()
    out = tmp_path / "deliveries" / "experiment"
    request = {**request_for_source(originals), "out": str(out)}
    created = call("plot.create", {"request": request}, direct=True)
    assert created["ready_to_use"] and created["revision"] == 0, created
    root = Path(created["plot"])
    assert root.parent.name == ".sciplot_semantic"
    assert (root.parent.parent / ".sciplot_store/head.json").is_file()
    assert root.is_relative_to(originals) and not root.is_relative_to(out)
    repository = ComposedProjectRepository()
    with repository_scope(repository), repository.query_scope(root):
        binding = repository.load_head(root)["binding"]
    assert Path(binding["document"]).is_relative_to(root.parent.parent / ".sciplot_store")
    first = out / "artifacts" / created["ir_hash"]
    original_members = file_inventory(first)
    assert {"document.vsz", "exports/document.pdf", "exports/document_300dpi.tiff"} <= set(original_members)
    assert not (out / "index.json").exists()  # This is not a task or paper package.

    changed = call("plot.patch", {"plot": str(root), "request": patch(
        created, "wider-line", "style.line.width", "1.2pt", "series:A")}, direct=True)
    assert changed["ready_to_use"] and changed["revision"] == 1, changed
    second = out / "artifacts" / changed["ir_hash"]
    assert first != second and file_inventory(first) == original_members
    assert all(Path(item["path"]).is_relative_to(second) for item in changed["exports"])

    lost = next(Path(item["path"]) for item in changed["exports"] if item["format"] == "pdf")
    lost.unlink()
    exported = call("plot.export", {"plot": str(root)}, direct=True)
    assert exported["ready_to_use"] and exported["revision"] == 1 and lost.is_file()
    assert file_inventory(first) == original_members

    visible = second / "document.vsz"
    edited = visible.read_bytes() + b"\n# user edit\n"
    visible.write_bytes(edited)
    with pytest.raises(RemoteError):
        call("plot.export", {"plot": str(root)}, direct=True)
    assert visible.read_bytes() == edited
