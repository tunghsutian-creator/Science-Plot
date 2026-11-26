"""Generated ManagedPlots to relocated independently editable native snapshots."""

import json
import csv
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from test_figure_document import request_for_figure
from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head
from sciplot_core.veusz_runtime import veusz_worker_environment


def _verify_selected_figure_handoff(tmp_path, selected, exports):
    import signal

    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
    from PIL import Image
    from socket_fixture_helpers import socket_directory

    from sciplot_core.plot_protocol.paths import read_owner

    launcher = str(REPO_ROOT / "skill/scripts/sciplot")
    plot = Path(selected["plot"])
    audit = {item["format"]: item["sha256"] for item in exports}
    original_cache = file_sha256(plot / "export-cache.json")

    def direct(label, directory, *, revision=selected["revision"], success=True):
        command = [launcher, "plot", "export", str(plot), "--direct", "--json",
                   "--output-dir", str(directory), "--plot-id", selected["plot_id"], "--revision", str(revision)]
        process = subprocess.run(command, env=veusz_worker_environment(), cwd=REPO_ROOT,
                                 capture_output=True, text=True, timeout=90, check=False)
        assert process.returncode == (0 if success else 1), (label, process.stdout, process.stderr)
        return json.loads(process.stdout)

    pdf_dir = tmp_path / "just PDF"
    pdf = direct("pdf", pdf_dir)
    assert pdf["ready_to_use"] and pdf["revision"] == selected["revision"]
    assert [row["format"] for row in pdf["exports"]] == ["pdf"]
    assert len(list(pdf_dir.iterdir())) == 1
    document = Path(pdf["exports"][0]["path"])
    assert document.parent == pdf_dir and document.read_bytes().startswith(b"%PDF-")
    assert file_sha256(document) == pdf["exports"][0]["sha256"] == audit["pdf"]

    parent_before = set(tmp_path.iterdir())
    occupied = direct("occupied", pdf_dir, success=False)
    assert occupied["reason_code"] == "figure_handoff_destination_exists"
    assert file_sha256(document) == audit["pdf"]
    stale_dir = tmp_path / "stale"
    stale = direct("stale", stale_dir, revision=selected["revision"] + 1, success=False)
    assert stale["reason_code"] == "figure_handoff_revision_conflict"
    assert set(tmp_path.iterdir()) == parent_before

    both = tmp_path / "manuscript files"
    fields = {"output_dir": str(both), "plot_id": selected["plot_id"],
              "revision": selected["revision"], "formats": ["pdf", "tiff_300"]}
    with socket_directory(prefix="sp-figures-", dir="/tmp") as root:
        socket = Path(root) / "engine.sock"
        environment = {**veusz_worker_environment(), "SCIPLOT_ENGINE_SOCKET": str(socket)}
        parameters = StdioServerParameters(command=launcher, args=["mcp", "--profile", "daily"], cwd=REPO_ROOT, env=environment)

        async def run_daily():
            async with Client(parameters, read_timeout_seconds=90) as mcp:
                result = await mcp.call_tool("sciplot_plot_export", {"plot": str(plot), "handoff": fields})
                assert not result.is_error, result.content
                return result.structured_content

        try:
            copied = anyio.run(run_daily)
        finally:
            if socket.exists():
                os.kill(read_owner(socket)["pid"], signal.SIGTERM)
    assert copied["ready_to_use"] and copied["plot_id"] == fields["plot_id"] and copied["revision"] == fields["revision"]
    files = {row["format"]: Path(row["path"]) for row in copied["exports"]}
    assert set(files) == {"pdf", "tiff_300"} and set(both.iterdir()) == set(files.values())
    assert all(file_sha256(path) == audit[fmt] for fmt, path in files.items())
    with Image.open(files["tiff_300"]) as image:
        assert image.format == "TIFF"
        assert image.info["dpi"] == pytest.approx((300, 300), abs=.1)
    assert file_sha256(plot / "export-cache.json") == original_cache


@pytest.mark.comprehensive
def test_public_managed_delivery_relocated_native_open_edit_save_and_export(tmp_path):
    service = PlotService()
    originals = {}
    selected = []
    try:
        source_directory = tmp_path / "shared-input"
        source_directory.mkdir()
        original_request = request_for_figure(source_directory)
        for name in ("A", "B"):
            request = {**original_request, "idempotency_key": f"shared-delivery-{name}"}
            result = service.create(request)
            assert result["ready_to_use"], json.dumps(result, indent=2)
            plot = Path(result["plot"])
            head = load_head(plot)
            for path in (Path(request["data_binding"]["data_sources"][0]["path"]),
                         plot / "head.json", Path(head["binding"]["document"])):
                originals[path] = file_sha256(path)
            selected.append({"plot": str(plot), "plot_id": result["plot_id"],
                             "revision": result["revision"], "label": f"P{name}/native"})
            if name == "A":
                _verify_selected_figure_handoff(tmp_path, selected[-1], result["exports"])
        delivery = {"idempotency_key": "generated-native-delivery", "title": "Independent snapshots",
                    "mode": "native_snapshot", "out": str(tmp_path / "published snapshots"), "items": selected}
        request_file = tmp_path / "delivery-request.json"
        request_file.write_text(json.dumps(delivery))
        env = {**os.environ, "SCIPLOT_PYTHON": sys.executable,
               "PYTHONPATH": os.pathsep.join(filter(None, (str(REPO_ROOT / "src"), os.environ.get("PYTHONPATH", ""))))}
        cli = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "plot", "deliver", "--request", str(request_file), "--direct", "--json"],
                             env=env, capture_output=True, text=True, timeout=240, check=False)
        assert cli.returncode == 0, cli.stdout + cli.stderr
        result = json.loads(cli.stdout)
        assert result["ready_to_use"] and result["mode"] == "native_snapshot", result
        assert result["capabilities"]["portable_managed_project"] is False
        out = Path(result["out"])
        index = json.loads((out / "index.json").read_text())
        assert len({item["plot_id"] for item in selected}) == 2
        assert len({item["sources"][0]["path"] for item in index["items"]}) == 1
        assert len(list((Path(result["checkpoint"]) / "data" / "originals").iterdir())) == 1
        for item, selection in zip(index["items"], selected, strict=True):
            original_ir = Path(load_head(Path(selection["plot"]))["binding"]["ir_path"])
            data = item["plotted_data"]
            exact_ir = out / data["ir"]["path"]
            assert exact_ir.read_bytes() == original_ir.read_bytes()
            payload = json.loads(exact_ir.read_text())
            assert len(data["datasets"]) == len(payload["datasets"])
            for table in data["datasets"]:
                with (out / table["path"]).open(newline="") as handle:
                    rows = list(csv.reader(handle))[1:]
                original_columns = payload["datasets"][table["dataset_id"]]["columns"]
                assert len(rows) == table["row_count"]
                for column_index, column_id in enumerate(table["column_ids"]):
                    assert [float(row[column_index]) if row[column_index] else None for row in rows] == original_columns[column_id]["values"]
        connected = service.open(out, figure_id=index["items"][0]["id"], description={"scope": "summary"})
        assert connected["plot"] == selected[0]["plot"] and connected["plot_type"] == "ManagedPlot"
        assert connected["delivery_continuation"]["mode"] == "original_local_managed"
        from sciplot_core.plot_engine.errors import EngineError
        from sciplot_core.studio_core.project_query import inspect_project

        secondary = index["items"][1]
        secondary_path = out / secondary["files"]["editable"]
        public = PlotService(read_only_legacy=True)
        try:
            for display, selector in ((out, secondary["id"]), (out / "index.json", secondary["id"]),
                                      (secondary_path, None)):
                opened = public.open(display, figure_id=selector, description={"scope": "summary"})
                inspected = inspect_project(display, figure_id=selector)
                assert opened["plot"] == selected[1]["plot"] == inspected["project"]
                assert opened["plot_type"] == "ManagedPlot"
                assert inspected["selected_figure"]["figure_id"] == secondary["id"]
                assert inspected["selected_snapshot"] == {"path": str(secondary_path), "item_id": secondary["id"], "current": True}
            with pytest.raises(EngineError, match="same exact delivery member"):
                public.open(secondary_path, figure_id=index["items"][0]["id"])
            with pytest.raises(EngineError, match="same exact delivery member"):
                inspect_project(secondary_path, figure_id=index["items"][0]["id"])
        finally:
            public.close()
        with zipfile.ZipFile(out / "Figures.zip") as archive:
            assert len([name for name in archive.namelist() if name.endswith(".vsz")]) == 2
            assert all(archive.read(name) == (out / name).read_bytes() for name in archive.namelist())
        # Move an isolated complete copy, rather than editing the installed
        # frozen delivery or treating its absolute local plot paths as portable.
        moved = tmp_path / "different location" / "moved native package"
        shutil.copytree(out, moved)
        target = moved / index["items"][0]["files"]["editable"]
        program = tmp_path / "edit-moved-native.py"
        program.write_text(
            "from pathlib import Path\nimport json\n"
            "from sciplot_core.veusz_worker.document_edit import loaded_native_document\n"
            "from sciplot_core.plot_backends.managed_audit import native_state,content_hash\n"
            "from sciplot_core.studio_core.persistence import atomic_save_veusz_document\n"
            "from sciplot_core.studio_core.export_execution import export_studio_document\n"
            f"target=Path({str(target)!r})\n"
            "with loaded_native_document(target) as doc:\n"
            " before=content_hash(native_state(doc)['datasets'])\n"
            " nodes=[]\n"
            " doc.walkNodes(lambda p,w:nodes.append((p,w)),nodetypes=('widget',))\n"
            " path=next(str(p) for p,w in nodes if w.typename=='xy')\n"
            " doc.resolveSettingPath(None,path+'/PlotLine/color').set('#A34455')\n"
            " saved=atomic_save_veusz_document(doc,target)\n"
            " assert saved['ready_for_export']\n"
            "with loaded_native_document(target) as doc:\n"
            " assert content_hash(native_state(doc)['datasets'])==before\n"
            " assert doc.resolveSettingPath(None,path+'/PlotLine/color').get()=='#A34455'\n"
            f"exported=export_studio_document(target,formats=['pdf','tiff_300'],output_dir=Path({str(tmp_path / 'relocated-exports')!r}))\n"
            "assert len(exported['exports'])==2\n"
            "assert all(e['exists'] and e['size_bytes']>0 and e['sha256'] for e in exported['exports'])\n"
            "print(json.dumps({'reopened':True,'edited_and_saved':True,'source_data_equal':True,'exported':exported}))\n"
        )
        edited = subprocess.run([sys.executable, str(program)], env=veusz_worker_environment(),
                                capture_output=True, text=True, timeout=120, check=False)
        assert edited.returncode == 0, edited.stdout + edited.stderr
        evidence = json.loads(edited.stdout)
        assert evidence["reopened"] and evidence["edited_and_saved"] and evidence["source_data_equal"]
        assert {item["format"] for item in evidence["exported"]["exports"]} == {"pdf", "tiff_300"}
        assert file_sha256(target) != file_sha256(out / index["items"][0]["files"]["editable"])
        changed = {str(path): {"before": expected, "after": file_sha256(path)}
                   for path, expected in originals.items() if file_sha256(path) != expected}
        assert changed == {}, changed
        assert service.deliver(delivery)["ready_to_use"], "Editing the independent moved snapshot must not dirty the original ManagedPlots/delivery."
    finally:
        service.close()


@pytest.mark.comprehensive
def test_managed_delivery_uses_store_sealed_source_after_original_disappears(tmp_path):
    from contextlib import closing

    from sciplot_core.project_store.repository import FileProjectStore

    project, inputs = tmp_path / "original-project", tmp_path / "original-inputs"
    project.mkdir()
    inputs.mkdir()
    request = request_for_figure(inputs)
    source = Path(request["data_binding"]["data_sources"][0]["path"])
    raw = source.read_bytes()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    with closing(PlotService()) as service:
        original = service.create(request, project=project)
        assert original["ready_to_use"], json.dumps(original, indent=2)
    bundle = store.export_bundle(tmp_path / "bundle")
    project.rename(tmp_path / "disconnected-project")
    inputs.rename(tmp_path / "disconnected-inputs")
    assert not source.exists()
    moved = FileProjectStore.import_bundle(bundle, tmp_path / "relocated-project")
    with closing(PlotService()) as service:
        opened = service.open(moved.root, figure_id=original["plot_id"])
        plot = Path(opened["plot"])
        exported = service.export(plot)
        assert exported["ready_to_use"], exported
        out = tmp_path / "delivered"
        result = service.deliver({"idempotency_key": "moved-project-delivery", "title": "Moved project",
            "mode": "native_snapshot", "out": str(out), "items": [{
                "plot": str(plot), "plot_id": original["plot_id"], "revision": original["revision"], "label": "Moved plot",
            }]})
        assert result["ready_to_use"], json.dumps(result, indent=2)
    manifest = json.loads((out / "index.json").read_text())
    row = manifest["items"][0]
    assert row["scientific_hash"] == original["scientific_hash"]
    assert (out / row["sources"][0]["path"]).read_bytes() == raw
    assert row["sources"][0]["original_name"] == source.name
    assert not source.exists()
