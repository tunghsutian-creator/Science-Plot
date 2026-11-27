"""A relocated standalone project hands off only its exact selected files."""

from contextlib import closing
import csv
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
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    root = tmp_path.resolve()
    original = root / "old workspace"
    project = original / "project"
    project.mkdir(parents=True)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    with closing(PlotService()) as service:
        create = request_for_figure(original)
        original_source, = create["data_binding"]["data_sources"]
        created = service.create(create, project=project)
        assert created["ready_to_use"], created
        saved = service.patch(Path(created["plot"]), {"plot_id": created["plot_id"], "base_revision": 0,
            "idempotency_key": "current-frequency-label", "intent_class": "presentation",
            "changes": [{"op": "set", "target": ["axis:xb"], "property": "axis.label",
                         "value": "Current frequency display"}]})
        assert saved["ready_to_use"] and saved["revision"] == 1, saved
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
        assert document["revision"] == saved["revision"]
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
        if "pdf" in files:
            assert files["pdf"].read_bytes().startswith(b"%PDF-")
        if "tiff_300" in files:
            with Image.open(files["tiff_300"]) as raster:
                assert raster.format == "TIFF" and raster.info["dpi"] == pytest.approx((300, 300), abs=.1)
        return files

    occupied = destination / "occupied"
    occupied.mkdir()
    marker = occupied / "keep.txt"
    marker.write_bytes(b"do not replace")
    refused = destination / "not created"
    cli(occupied, failure="figure_handoff_destination_exists")
    cli(refused, plot="plot:unknown", failure="project_file_figure_not_found")
    cli(refused, plot=entry["figure_id"], failure="project_file_figure_not_found")
    cli(refused, rev=revision - 1, failure="figure_handoff_revision_conflict")
    for flag in ("--plotted-csv", "--editable-vsz"):
        cli(refused, rev=revision - 1, flags=(flag,), failure="figure_handoff_revision_conflict")
    cli(refused, target=alias, failure="project_file_invalid")
    assert not refused.exists() and list(occupied.iterdir()) == [marker] and marker.read_bytes() == b"do not replace"

    pdf = destination / "just PDF"
    verify(cli(pdf), pdf, ["pdf"])
    tiff = destination / "just TIFF"
    verify(cli(tiff, flags=("--tiff-only",)), tiff, ["tiff_300"])
    vsz = destination / "just editable VSZ"
    result = cli(vsz, flags=("--editable-vsz",))
    editable = verify(result, vsz, ["editable_vsz"])["editable_vsz"]
    assert editable.name == "figure.vsz" and result["managed_project_included"] is False
    assert result["mode"] == "independent_native_snapshot"
    assert "Current frequency display" in editable.read_text(encoding="utf-8")
    with loaded_native_document(editable) as reopened:
        assert sorted(dataset.data.tolist() for dataset in reopened.data.values()) == [[0., 5., 10.], [1., 5., 15.]]

    both = destination / "PDF and TIFF"
    data = destination / "just plotted CSV"
    with socket_directory(prefix="sp-file-handoff-", dir="/tmp") as directory:
        socket = Path(directory) / "engine.sock"
        parameters = _parameters(cli=True, profile="daily")
        parameters.env = {**(parameters.env or {}), **env, "SCIPLOT_ENGINE_SOCKET": str(socket)}

        async def mcp_export():
            async with Client(parameters, read_timeout_seconds=90) as mcp:
                async def selected(output, formats):
                    fields = {"output_dir": str(output), "plot_id": plot_id, "revision": revision, "formats": formats}
                    reply = await mcp.call_tool("sciplot_plot_export", {"plot": str(moved), "handoff": fields})
                    assert not reply.is_error, reply.structured_content
                    assert str(scratch) not in str(reply.structured_content) and str(original) not in str(reply.structured_content)
                    return reply.structured_content

                verify(await selected(both, ["tiff_300", "pdf"]), both, ["pdf", "tiff_300"])
                result = await selected(data, ["plotted_csv"])
                table = verify(result, data, ["plotted_csv"])["plotted_csv"]
                with table.open(newline="", encoding="utf-8") as stream:
                    headers, *values = csv.reader(stream)
                assert headers == ["Frequency", "Modulus"]
                assert [list(map(float, row)) for row in values] == [[0., 1.], [5., 5.], [10., 15.]]
                record, = result["exports"]
                assert result["coordinate_space"] == "scientific_layer_inputs"
                assert [column["unit"] for column in record["columns"]] == ["Hz", "Pa"]
                assert record["layers"][0]["sample"] == "Modulus"
                [provenance] = record["provenance"]["sources"]
                assert {key: provenance[key] for key in ("source_id", "sha256", "table_selection")} == {
                    key: original_source[key] for key in ("source_id", "sha256", "table_selection")}

        try:
            anyio.run(mcp_export)
        finally:
            if socket.exists():
                os.kill(read_owner(socket)["pid"], signal.SIGTERM)

    assert not original.exists() and not list(scratch.glob("sciplot-open-*"))
    assert file_sha256(moved) == archive_receipt.sha256 and sentinel.read_text() == "unrelated file"
    assert set(destination.iterdir()) == {moved, occupied, sentinel, alias, pdf, tiff, both, vsz, data}

    def never_build(*_args, **_kwargs):
        pytest.fail("An archive with an existing export cache must not rebuild it.")

    with closing(PlotService()) as service:
        monkeypatch.setattr(service, "_export", never_build)
        monkeypatch.setattr(service.backend, "export_selected", never_build)
        warm_out, blocked = root / "warm PDF", root / "no PDF after failed QA"
        handoff = {"output_dir": str(warm_out), "plot_id": plot_id, "revision": revision, "formats": ["pdf"]}
        warm_export = service.export(warm, handoff=handoff)
        [warm_pdf] = warm_export["exports"]
        assert warm_pdf["sha256"] == next(item["sha256"] for item in saved["exports"] if item["format"] == "pdf")
        warm_tiff = root / "warm TIFF"
        [cached_tiff] = service.export(warm, handoff={**handoff, "output_dir": str(warm_tiff), "formats": ["tiff_300"]})["exports"]
        assert cached_tiff["sha256"] == next(item["sha256"] for item in saved["exports"] if item["format"] == "tiff_300")
        for formats in (["pdf"], ["tiff_300"], ["plotted_csv"], ["editable_vsz"]):
            with pytest.raises(EngineError, match="handoff does not rebuild") as error:
                service.export(unready, handoff={**handoff, "output_dir": str(blocked), "formats": formats})
            assert error.value.reason_code == "figure_handoff_publication_unready" and not blocked.exists()
    assert file_sha256(warm) == warm_saved.sha256 and file_sha256(unready) == unready_saved.sha256

    def native_error(binding, output, formats):
        private_root = binding["root"]
        raise EngineError("native_error", f"Failed to open {private_root} from the old binding {original}",
                          evidence=str(private_root))

    with closing(PlotService()) as service:
        monkeypatch.setattr(service.backend, "export_selected", native_error)
        with pytest.raises(EngineError) as failed:
            service.export(moved, handoff={**handoff, "output_dir": str(refused)})
    assert failed.value.reason_code == "figure_handoff_publication_unready"
    assert "sciplot-open-" not in str(failed.value) and str(original) not in str(failed.value)
    assert failed.value.repair == {"action": "inspect_project_file_handoff", "project_file": str(moved),
                                   "project_id": archive_receipt.project_id}
    assert not refused.exists() and file_sha256(moved) == archive_receipt.sha256


def test_historical_fallback_only_allows_the_owned_completed_current_series_edit(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from copy import deepcopy
    from types import SimpleNamespace

    from sciplot_core.project_lifecycle import project_file_handoff as owner_module
    from sciplot_core.project_lifecycle.context import digest, transaction_path
    from sciplot_core.project_lifecycle.contracts import NormalizedCommand, RevisionToken

    def document(revision, science):
        return {"plot_id": "plot:selected", "plot_type": "ManagedPlot", "revision": revision,
                "scientific_hash": science * 64, "presentation_hash": "c" * 64}

    root = tmp_path / "selected namespace"
    runtime = tmp_path / "runtime-cache"
    prior = {"document": document(0, "a"), "binding": {"ir_hash": "prior"}}
    cache = root / "export-cache.json"
    current = document(1, "b")

    def install_transaction(kind, key, operation, *, phase="complete"):
        request = {"idempotency_key": key, "intent_class": "scientific",
                   "plot_id": "plot:selected", "base_revision": 0,
                   "changes": [{"op": "set", "target": ["view:main"], "property": operation, "value": {}}]}
        command = NormalizedCommand.create(kind, request, expected_revision=RevisionToken.of(prior["document"]))
        journal = transaction_path(root, key)
        tx = {"normalized_command": command.to_payload(), "request": request, "phase": phase,
              "id": digest(key), "export_deferred": True, "document": deepcopy(current), "before": prior["document"]}
        head.update(transaction=tx["id"])
        records.clear()
        records.update({journal: tx, cache: {"export": {"ir_hash": "prior"}}})
        return tx

    head = {"document": current}
    records = {}
    owner = SimpleNamespace(runtime_path=lambda _: runtime, query_scope=lambda _: nullcontext(),
                            load_head=lambda _: head, exists=lambda path: path in records,
                            read=records.__getitem__, load_revision=lambda _, revision: prior)
    good = {"ready_to_use": True}
    monkeypatch.setattr(owner_module, "sealed_publication", lambda path, revision: good if path == root and revision == prior else None)
    series_key = "archive-series:" + "d" * 64
    install_transaction("patch", series_key, "source.append")
    assert owner_module._has_deferred_export(owner, root)
    # An invalid local cache remains evidence: it must not mask failure.
    runtime.write_text("damaged current cache")
    assert not owner_module._has_deferred_export(owner, root)
    runtime.unlink()

    install_transaction("patch", "manual-patch", "source.append")
    assert not owner_module._has_deferred_export(owner, root)
    install_transaction("patch", series_key, "series.display_label")
    assert not owner_module._has_deferred_export(owner, root)
    install_transaction("patch", series_key, "source.append", phase="prepared")
    assert not owner_module._has_deferred_export(owner, root)
    install_transaction("patch", series_key, "source.append")["document"]["scientific_hash"] = "f" * 64
    assert not owner_module._has_deferred_export(owner, root)
    install_transaction("patch", series_key, "source.append")
    good["ready_to_use"] = False
    assert not owner_module._has_deferred_export(owner, root)
