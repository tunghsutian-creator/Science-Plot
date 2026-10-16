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


@pytest.mark.comprehensive
def test_public_managed_delivery_relocated_native_open_edit_save_and_export(tmp_path):
    service = PlotService()
    originals = {}
    selected = []
    try:
        for name in ("A", "B"):
            source_directory = tmp_path / name
            source_directory.mkdir()
            request = request_for_figure(source_directory)
            result = service.create(request)
            assert result["ready_to_use"], result
            plot = Path(result["plot"])
            head = load_head(plot)
            for path in (Path(request["data_binding"]["data_sources"][0]["path"]),
                         plot / "head.json", Path(head["binding"]["document"])):
                originals[path] = file_sha256(path)
            selected.append({"plot": str(plot), "plot_id": result["plot_id"],
                             "revision": result["revision"], "label": f"P{name}/native"})
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
