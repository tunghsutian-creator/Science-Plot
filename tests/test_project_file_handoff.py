"""A relocated standalone project hands off only the two supported image choices."""

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
from sciplot_core.project_lifecycle.attachment_index import Attachment, read_index
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.project_file import create_project_file
from sciplot_core.project_lifecycle.project_file_summary import project_file_figure
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.veusz_runtime import veusz_worker_environment


@pytest.mark.comprehensive
def test_relocated_project_file_selected_handoff_through_cli_and_daily_mcp(tmp_path, monkeypatch):
    import anyio
    from mcp import Client
    from PIL import Image
    from socket_fixture_helpers import socket_directory
    from test_figure_document import request_for_figure
    from test_mcp_stdio import _parameters

    root = tmp_path.resolve()
    original = root / "old workspace"
    project = original / "project"
    project.mkdir(parents=True)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    with closing(PlotService()) as service:
        saved = service.create(request_for_figure(original), project=project)
        assert saved["ready_to_use"], saved
    [entry] = read_index(store)["attachments"].values()
    assert entry["plot_id"] == saved["plot_id"] != entry["figure_id"]
    generation = store.snapshot()["generation"]
    warm = root / "warm.sciplot"
    warm_saved = create_project_file(warm, store, expected_generation=generation)
    cache = Attachment(store, entry).cache
    cache_path = cache / "state" / "export-cache.json"
    failure = json.loads(cache_path.read_text())
    failure["export"]["publication_qa"]["status"] = "failed"
    cache_path.write_text(json.dumps(failure))
    unready = root / "failed-qa.sciplot"
    unready_saved = create_project_file(unready, store, expected_generation=generation)
    # A bundle can retain derivatives. Remove only this fixture's disposable
    # tree to make sure the cold archive cannot reuse a built publication.
    shutil.rmtree(cache)
    archive = original / "原图.sciplot"
    archive_receipt = create_project_file(archive, store, expected_generation=generation)
    destination = root / "论文 (冷启动)"
    destination.mkdir()
    moved = archive.rename(destination / "频率数据.sciplot")
    shutil.rmtree(original)
    with project_file_figure(moved, saved["plot_id"]) as (_session, owner, document):
        assert document["revision"] == 0
        assert not owner.exists(owner.attachment.root / "export-cache.json")

    sentinel = destination / "keep.txt"
    sentinel.write_text("unrelated file")
    alias = destination / "别名.sciplot"
    alias.symlink_to(moved)
    scratch = root / "scratch"
    scratch.mkdir()
    env = {**veusz_worker_environment(), "TMPDIR": str(scratch), "SCIPLOT_PYTHON": sys.executable,
           "MPLCONFIGDIR": str(root / "mpl")}
    plot_id, revision = saved["plot_id"], saved["revision"]

    def cli(output, *, target=moved, plot=plot_id, rev=revision, flags=(), failure=None):
        execution = subprocess.run(
            [str(REPO_ROOT / "skill/scripts/sciplot"), "plot", "export", str(target.relative_to(root)),
             "--output-dir", str(output), "--plot-id", plot, "--revision", str(rev), "--direct", "--json", *flags],
            env={**env, **({"SCIPLOT_VEUSZ_ROOT": str(root / "no-renderer")} if failure else {})},
            cwd=root, capture_output=True, text=True, timeout=90, check=False,
        )
        assert execution.returncode == int(failure is not None), execution.stdout + execution.stderr
        assert str(scratch) not in execution.stdout and str(original) not in execution.stdout
        assert not list(scratch.iterdir())
        result = json.loads(execution.stdout)
        if failure:
            assert result["reason_code"] == failure, result
        return result

    def verify(result, output, formats):
        assert result["kind"] == "sciplot_figure_handoff" and result["ready_to_use"] is True
        assert {key: result[key] for key in ("plot", "project_file", "project_id", "plot_id", "revision",
                "scientific_hash", "presentation_hash", "output_dir")} == {
            "plot": str(moved), "project_file": str(moved), "project_id": archive_receipt.project_id,
            "plot_id": plot_id, "revision": revision, "scientific_hash": saved["scientific_hash"],
            "presentation_hash": saved["presentation_hash"], "output_dir": str(output),
        }
        files = {item["format"]: Path(item["path"]) for item in result["exports"]}
        assert files.keys() == set(formats) and set(output.iterdir()) == set(files.values())
        assert all(file_sha256(Path(row["path"])) == row["sha256"] for row in result["exports"])
        assert files["pdf"].read_bytes().startswith(b"%PDF-")
        if "tiff_300" in files:
            with Image.open(files["tiff_300"]) as raster:
                assert raster.format == "TIFF" and raster.info["dpi"] == pytest.approx((300, 300), abs=.1)

    occupied = destination / "occupied"
    occupied.mkdir()
    marker = occupied / "keep.txt"
    marker.write_bytes(b"do not replace")
    refused = destination / "not created"
    cli(occupied, failure="figure_handoff_destination_exists")
    cli(refused, plot="plot:unknown", failure="project_file_figure_not_found")
    cli(refused, plot=entry["figure_id"], failure="project_file_figure_not_found")
    cli(refused, rev=revision + 1, failure="figure_handoff_revision_conflict")
    cli(refused, target=alias, failure="project_file_invalid")
    cli(refused, flags=("--plotted-csv",), failure="project_file_handoff_unsupported")
    assert not refused.exists() and list(occupied.iterdir()) == [marker] and marker.read_bytes() == b"do not replace"

    pdf = destination / "just PDF"
    verify(cli(pdf), pdf, ["pdf"])
    both = destination / "PDF and TIFF"
    with socket_directory(prefix="sp-file-handoff-", dir="/tmp") as directory:
        socket = Path(directory) / "engine.sock"
        parameters = _parameters(cli=True, profile="daily")
        parameters.env = {**(parameters.env or {}), **env, "SCIPLOT_ENGINE_SOCKET": str(socket)}

        async def mcp_export():
            async with Client(parameters, read_timeout_seconds=90) as mcp:
                fields = {"output_dir": str(both), "plot_id": plot_id, "revision": revision, "formats": ["tiff_300", "pdf"]}
                reply = await mcp.call_tool("sciplot_plot_export", {"plot": str(moved), "handoff": fields})
                assert not reply.is_error, reply.content
                assert str(scratch) not in str(reply.structured_content) and str(original) not in str(reply.structured_content)
                return reply.structured_content

        try:
            verify(anyio.run(mcp_export), both, ["pdf", "tiff_300"])
        finally:
            if socket.exists():
                os.kill(read_owner(socket)["pid"], signal.SIGTERM)

    assert not original.exists() and not list(scratch.glob("sciplot-open-*"))
    assert file_sha256(moved) == archive_receipt.sha256 and sentinel.read_text() == "unrelated file"
    assert set(destination.iterdir()) == {moved, occupied, sentinel, alias, pdf, both}

    def never_build(*_args, **_kwargs):
        pytest.fail("An archive with an existing export cache must not rebuild it.")

    with closing(PlotService()) as service:
        monkeypatch.setattr(service, "_export", never_build)
        warm_out, blocked = root / "warm PDF", root / "no PDF after failed QA"
        handoff = {"output_dir": str(warm_out), "plot_id": plot_id, "revision": revision, "formats": ["pdf"]}
        warm_export = service.export(warm, handoff=handoff)
        [warm_pdf] = warm_export["exports"]
        assert warm_pdf["sha256"] == next(item["sha256"] for item in saved["exports"] if item["format"] == "pdf")
        with pytest.raises(EngineError, match="handoff does not rebuild") as error:
            service.export(unready, handoff={**handoff, "output_dir": str(blocked)})
        assert error.value.reason_code == "figure_handoff_publication_unready" and not blocked.exists()
    assert file_sha256(warm) == warm_saved.sha256 and file_sha256(unready) == unready_saved.sha256

    def native_error(private_root):
        raise EngineError("native_error", f"Failed to open {private_root} from the old binding {original}",
                          evidence=str(private_root))

    with closing(PlotService()) as service:
        monkeypatch.setattr(service, "_export", native_error)
        with pytest.raises(EngineError) as failed:
            service.export(moved, handoff={**handoff, "output_dir": str(refused)})
    assert failed.value.reason_code == "figure_handoff_publication_unready"
    assert "sciplot-open-" not in str(failed.value) and str(original) not in str(failed.value)
    assert failed.value.repair == {"action": "inspect_project_file_handoff", "project_file": str(moved),
                                   "project_id": archive_receipt.project_id}
    assert not refused.exists() and file_sha256(moved) == archive_receipt.sha256
