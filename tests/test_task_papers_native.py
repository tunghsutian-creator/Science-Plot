from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.document_edit_state import run_document_worker
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.task_control import start_task
from sciplot_core.task_papers import paper_capabilities, start_paper, resume_paper
from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.veusz_runtime import veusz_worker_environment


def _public(*args):
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "task", "paper", *map(str, args), "--json"],
                            capture_output=True, text=True, timeout=240,
                            env={**os.environ, "SCIPLOT_PYTHON": sys.executable, "PYTHONPATH": str(REPO_ROOT / "src")})
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _projects(tmp_path):
    sources = []
    projects = []
    for name, text in (
        ("UVvis", "Wavelength,Absorbance\nnm,a.u.\nE3,E3\n400,1\n425,2\n450,4\n475,2\n500,1\n"),
        ("FTIR", "Wavenumber,Absorbance\ncm-1,a.u.\nF3,F3\n1000,2\n1250,3\n1500,2\n"),
    ):
        source = tmp_path / f"{name}.csv"
        source.write_text(text)
        sources.append(source)
        created = start_task({"version": 1, "action": "create", "source": str(source)},
                             task_dir=tmp_path / f"create-{name}", defer_creation_export=True)
        assert created["status"] == "complete", created
        projects.append(Path(created["project"]))
    return sources, projects


def _request(tmp_path, projects):
    return {"version": 1, "title": "Two exact final figures", "out": str(tmp_path / "selected-paper"),
            "items": [{**paper_capabilities(project=project, figure_id=inspect_project(project)["primary_figure_id"])["selection"], "label": label}
                      for project, label in zip(projects, ("Fig2", "Fig1"), strict=True)]}


@pytest.mark.comprehensive
def test_public_paper_cli_packages_two_native_figures_and_relocated_editable_export(tmp_path):
    sources, projects = _projects(tmp_path)
    # Native manual presentation state is current authority, even without project re-export.
    selected = projects[0] / "studio/document.vsz"
    native_script = tmp_path / "manual-save.py"
    native = run_document_worker("inspect-document-state", selected)
    curve = next(path for path, widget in native["widgets"].items() if widget["type"] == "xy")
    linked = tmp_path / "native-linked.txt"
    spec = json.loads((projects[0] / "studio/spec.json").read_text())
    series = spec["series"][0]
    linked.write_text("".join(f"{x:.17g} {y:.17g}\n" for x, y in zip(series["x_values"], series["y_values"], strict=True)))
    native_script.write_text("from pathlib import Path\nfrom sciplot_core.veusz_worker.document_edit import loaded_native_document\n"
        "from sciplot_core.studio_core.persistence import atomic_save_veusz_document\n"
        f"path=Path({str(selected)!r})\nwith loaded_native_document(path) as doc:\n"
        " from veusz.document import CommandInterface\n"
        f" doc.resolveSettingPath(None,{(curve + '/PlotLine/color')!r}).set('#A34455')\n"
        f" CommandInterface(doc).ImportFile({str(linked)!r},{(series['x_name'] + '(numeric), ' + series['y_name'] + '(numeric)')!r},linked=True)\n"
        " atomic_save_veusz_document(doc,path)\n")
    saved = subprocess.run([sys.executable, str(native_script)], env=veusz_worker_environment(), capture_output=True, text=True, timeout=120)
    assert saved.returncode == 0, saved.stdout + saved.stderr
    before = {p: file_inventory(p) for p in [*sources, *projects, linked]}
    request = _request(tmp_path, projects)
    for item in request["items"]:
        item.pop("source_files")
        item.pop("document_authority")
    path = tmp_path / "paper.json"
    path.write_text(json.dumps(request))
    result = _public("start", "--request", path, "--paper-dir", tmp_path / "paper-task")
    assert result["status"] == "complete", result
    out = Path(request["out"])
    assert sorted(p.name for p in (out / "figures").glob("*.pdf")) == ["001_Fig2.pdf", "002_Fig1.pdf"]
    assert sorted(p.name for p in (out / "project").glob("*.vsz")) == ["001_Fig2.vsz", "002_Fig1.vsz"]
    manifest = json.loads((out / "data/figure_sources.json").read_text())
    assert [i["label"] for i in manifest["items"]] == ["Fig2", "Fig1"]
    assert all(i["portable_native"]["native_state_sha256"] == i["portable_native"]["reopened_native_state_sha256"] for i in manifest["items"])
    assert result["result"]["verification"]["passed"] is True
    assert manifest["items"][0]["portable_native"]["imports"]
    assert str(linked) in manifest["items"][0]["source_files"]
    copy = tmp_path / "relocated"
    shutil.copytree(out, copy)
    held = linked.with_suffix(".hidden")
    linked.rename(held)
    try:
        for item in manifest["items"]:
            editable = copy / item["editable"]
            audit = run_document_worker("audit-spec-data", editable, editable.with_suffix(".spec.json"), "--allow-presentation-edits")
            from sciplot_core.foundation.json_hashing import canonical_json_sha256

            assert canonical_json_sha256(audit["units"], allow_nan=False) == item["scientific_sha256"]
            exported = run_document_worker("export-document", editable, "--out", copy / "reexports" / item["stem"])
            assert len(exported["exports"]) == 2
            assert all(Path(export["path"]).is_file() for export in exported["exports"])
    finally:
        held.rename(linked)
    copied_state = run_document_worker("inspect-document-state", copy / "project/001_Fig2.vsz")
    assert copied_state["widgets"][curve]["settings"]["PlotLine/color"] == "#A34455"
    assert all(file_inventory(p) == before[p] for p in before)
    assert _public("resume", tmp_path / "paper-task")["status"] == "complete"
    assert _public("inspect", tmp_path / "paper-task")["delivery_current"] is True


@pytest.mark.comprehensive
def test_native_second_export_failure_and_exact_retry_only_reruns_unsealed_figure(tmp_path, monkeypatch):
    sources, projects = _projects(tmp_path)
    before = {p: file_inventory(p) for p in [*sources, *projects]}
    request = _request(tmp_path, projects)
    for item in request["items"]:
        item.pop("source_files")
        item.pop("document_authority")
    from sciplot_core import task_papers as owner

    export = owner.export_studio_document
    calls = []

    def failure(document, **options):
        calls.append(document.name)
        if document.name == "002_Fig1.vsz":
            raise RuntimeError("injected native export failure after first sealed item")
        return export(document, **options)

    monkeypatch.setattr(owner, "export_studio_document", failure)
    first = start_paper(request, paper_dir=tmp_path / "paper-task")
    assert first["status"] == "blocked", first
    assert [i["status"] for i in first["items"]] == ["sealed", "exporting"]
    assert not Path(request["out"]).exists()

    def restored(document, **options):
        calls.append(document.name)
        return export(document, **options)

    monkeypatch.setattr(owner, "export_studio_document", restored)
    from sciplot_core.delivery import install

    atomic_install = install.install_new_delivery

    def lost_reply(candidate, destination):
        atomic_install(candidate, destination)
        raise RuntimeError("injected lost reply after exclusive atomic publication")

    monkeypatch.setattr(install, "install_new_delivery", lost_reply)
    published_without_reply = resume_paper(tmp_path / "paper-task")
    assert published_without_reply["status"] == "blocked"
    assert Path(request["out"]).is_dir()
    monkeypatch.setattr(install, "install_new_delivery", atomic_install)
    final = resume_paper(tmp_path / "paper-task")
    assert final["status"] == "complete", final
    assert calls == ["001_Fig2.vsz", "002_Fig1.vsz", "002_Fig1.vsz"]
    assert all(file_inventory(p) == before[p] for p in before)
    assert all(file_sha256(Path(i["path"])) == i["delivery_sha256"] for i in final["result"]["figures"])
