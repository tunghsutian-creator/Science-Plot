from __future__ import annotations

import json
import csv
import subprocess
import sys
from pathlib import Path

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.studio_core.source_update import (
    apply_project_source_update,
    preview_project_source_update,
)
from sciplot_core.veusz_runtime import veusz_worker_environment


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not {".sciplot_store", ".sciplot_resources"}.intersection(path.relative_to(root).parts)
    }


@pytest.mark.comprehensive
@pytest.mark.parametrize("ys,status", [([1, 2, 3, 4, 5], "missing"), ([1, 4, 1, 3, 1], "ambiguous")])
def test_native_peak_revision_missing_and_multiple_candidates(tmp_path, ys, status):
    from sciplot_core.task_control import start_task, resume_task, inspect_task
    from sciplot_core.studio_core.project_query import resolve_project_figure
    from sciplot_core.studio_core.peak_analysis import inspect_peak_candidates
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.studio_core.annotation_operations import inspect_annotation_state

    old, new = tmp_path / "old.csv", tmp_path / "new.csv"
    for path, values in ((old, [1, 3, 2, 1, 1]), (new, ys)):
        path.write_text("Wavelength,Absorbance\nnm,a.u.\nA,A\n" + "".join(f"{x},{y}\n" for x, y in zip([400, 425, 450, 475, 500], values, strict=True)))
    first = start_task({"version": 1, "action": "create", "source": str(old), "rule_id": "uvvis_spectrum"}, task_dir=tmp_path / "create")
    assert first["status"] == "complete", first
    project = Path(first["project"])
    figure = resolve_project_figure(project, None)
    document = Path(figure["document"])
    peaks = inspect_peak_candidates(project, figure_id=figure["figure_id"], object_path="/page1/graph1/series_1",
        window={"min": 400, "max": 500, "unit": "nm"}, polarity="maximum", expected_document_sha256=file_sha256(document))
    edit_task = tmp_path / "edit"
    edit = start_task({"version": 1, "action": "edit", "project": str(project), "expected_document_sha256": file_sha256(document),
        "operations": [{"op": "add_peak_label", "id": "peak", "candidate": peaks["candidates"][0]}]}, task_dir=edit_task)
    assert edit["status"] == "needs_review", edit
    assert resume_task(edit_task, {"accept_preview": True})["status"] == "complete"
    old_bytes, new_bytes, baseline = old.read_bytes(), new.read_bytes(), document.read_bytes()
    task = tmp_path / "update"
    update = start_task({"version": 1, "action": "update_source", "project": str(project), "source": str(new)}, task_dir=task)
    assert update["status"] == "needs_input", update
    issue = update["question"]["evidence"][0]
    assert issue["status"] == status
    assert len(update["previews"]) == 2
    assert document.read_bytes() == baseline
    decision = {"figure_id": issue["figure_id"], "id": "peak", "action": "remove"}
    if status == "ambiguous":
        peak = issue["candidates"][1]
        decision.update(action="rebind", candidate_id=peak["candidate_id"], text="475 nm")
        record = (task / "task.json").read_bytes()
        with pytest.raises(ValueError, match="annotation_choices"):
            resume_task(task, {"expected_revision_id": update["revision_id"],
                              "annotation_choices": [{**decision, "action": "keep"}]})
        assert (task / "task.json").read_bytes() == record
    invalid = resume_task(task, {"expected_revision_id": update["revision_id"], "annotation_choices": [
        {"figure_id": issue["figure_id"], "id": "peak", "action": "keep"}]})
    assert invalid["status"] == "needs_input" and invalid["annotation_error"]
    update = resume_task(task, {"expected_revision_id": update["revision_id"], "annotation_choices": [decision]})
    assert update["status"] == "needs_review", update
    update = resume_task(task, {"expected_revision_id": update["revision_id"], "accept_source_update": True})
    assert update["status"] == "complete", update
    annotations = inspect_annotation_state(project)["annotations"]
    if status == "missing":
        assert annotations == []
    else:
        assert annotations[0]["peak_anchor"]["x"] == 475
    assert old.read_bytes() == old_bytes and new.read_bytes() == new_bytes
    current = inspect_task(task)["current_project"]
    assert current["source"]["current"] and current["qa"]["current"] and current["delivery"]["current"]


def _source(path: Path, *, changed: bool = False) -> None:
    path.write_text(
        "Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
        + (
            "B,B,A,A\n400,9,400,8\n450,10,450,9\n500,11,500,10\n"
            if changed
            else "A,A,B,B\n400,1,400,2\n450,2,450,3\n500,3,500,4\n"
        ),
        encoding="utf-8",
    )


def _cli(*args: object) -> dict:
    completed = subprocess.run(
        [str(REPO_ROOT / "skill/scripts/sciplot"), "studio", *map(str, args), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def _native(document: Path, *, edit: bool = False, size: str = "9pt") -> dict:
    code = f"""
import json
from pathlib import Path
from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
ensure_veusz_runtime_path()
ensure_veusz_loader_compat()
from PyQt6 import QtWidgets
from veusz import document, widgets, dataimport
from veusz.document import CommandInterface
app = QtWidgets.QApplication([])
path = Path({str(document)!r})
spec = json.loads(path.with_name('spec.json').read_text())
doc = document.Document()
doc.load(str(path))
i = CommandInterface(doc)
colors = {{'A': '#A020F0', 'B': '#008080'}}
result = {{'series': {{}}}}
i.To('/page1/graph1/x')
if {edit!r}:
    i.Set('Label/size', {size!r})
result['label_size'] = i.Get('Label/size')
for item in spec['series']:
    i.To('/page1/graph1/' + item['name'])
    if {edit!r}:
        i.Set('PlotLine/color', colors[item['label']])
    result['series'][item['label']] = {{
        'color': i.Get('PlotLine/color'),
        'x': list(map(float, i.GetData(item['x_name'])[0])),
        'y': list(map(float, i.GetData(item['y_name'])[0])),
    }}
if {edit!r}:
    i.Save(str(path))
print(json.dumps(result))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        env=veusz_worker_environment(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.comprehensive
def test_native_source_update_preserves_sample_styles_and_publishes_same_project(
    tmp_path: Path,
) -> None:
    old_source, new_source = tmp_path / "old_uvvis.csv", tmp_path / "new_uvvis.csv"
    _source(old_source)
    _source(new_source, changed=True)
    visible = tmp_path / "UVvis_SciPlot"
    first = _cli(
        old_source,
        "--out",
        visible,
        "--rule",
        "uvvis_spectrum",
        "--export",
        "pdf,tiff_300",
    )
    assert first["studio_run"]["ready_to_use"] is True
    project, document = Path(first["project_dir"]), Path(first["document"])
    _native(document, edit=True)
    previous, old_visible = _files(project), _files(visible)
    old_runs = _files(project / "runs")
    review_path = tmp_path / "review.json"
    preview = _cli(project, "--update-source", new_source, "--preview-out", review_path)
    assert preview["status"] == "ready", preview
    assert json.loads(review_path.read_text()) == preview
    assert _files(project) == previous
    assert _files(visible) == old_visible
    figure_change = preview["changes"]["figures"][0]
    assert figure_change["change"] == "updated"
    assert figure_change["sample_order_changed"] is True

    applied = _cli(project, "--apply-revision", review_path)
    assert applied["status"] == "updated", applied
    assert applied["document"] == str(document)
    archive = Path(applied["archive"])
    assert (archive / "studio/document.vsz").read_bytes() == previous[
        "studio/document.vsz"
    ]
    for name, data in _files(archive).items():
        assert previous[name] == data
    assert _files(project / "runs") == old_runs
    assert _files(visible) == old_visible
    current = _native(document)
    assert current["label_size"] == "9pt"
    assert list(current["series"]) == ["B", "A"]
    for label, values, color in (
        ("B", [9, 10, 11], "#008080"),
        ("A", [8, 9, 10], "#A020F0"),
    ):
        assert current["series"][label] == {
            "color": color,
            "x": [400, 450, 500],
            "y": values,
        }
    adopted = document.read_bytes()
    reopened = _cli(project, "--prepare-only")
    assert reopened["project_dir"] == str(project)
    assert reopened["document"] == str(document)
    assert document.read_bytes() == adopted
    published = _cli(project, "--export", "pdf,tiff_300")
    assert published["studio_run"]["ready_to_use"] is True, published
    delivery = published["studio_run"]["delivery_package"]
    assert delivery["path"] == str(visible)
    assert Path(delivery["project_documents"][0]["path"]).read_bytes() == adopted
    assert _files(visible / "data") != {
        name.removeprefix("data/"): data
        for name, data in old_visible.items()
        if name.startswith("data/")
    }
    delivered_csv = list((visible / "data").glob("*.csv"))
    assert len(delivered_csv) == 1
    with delivered_csv[0].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[2] == ["B", "B", "A", "A"]
    assert [list(map(float, row)) for row in rows[3:]] == [
        [400, 9, 400, 8],
        [450, 10, 450, 9],
        [500, 11, 500, 10],
    ]
    assert set(old_runs).issubset(_files(project / "runs"))

    # Reuse the real published project to challenge both stale receipt inputs.
    # All checks operate on native saves or legitimate replacement source bytes.
    for stale in ("source", "document"):
        ready = preview_project_source_update(project, old_source)
        assert ready["status"] == "ready", ready
        if stale == "source":
            source_bytes = old_source.read_bytes()
            _source(old_source, changed=True)
        else:
            _native(document, edit=True, size="10pt")
        history = archive.parent
        before_rejection = _files(project), _files(visible), _files(history)
        with pytest.raises(ValueError, match="stale|changed"):
            apply_project_source_update(project, ready)
        assert (_files(project), _files(visible), _files(history)) == before_rejection
        if stale == "source":
            old_source.write_bytes(source_bytes)


@pytest.mark.comprehensive
def test_native_source_update_same_origin_versions_and_cold_public_export(tmp_path, monkeypatch):
    import os
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.studio import export_native_document_artifacts
    from sciplot_core.studio_core import source_update
    from sciplot_core.studio_core.project_command_scope import project_store
    from sciplot_core.studio_core.project_query import inspect_project
    from sciplot_core.native_process.session import _close_workers

    original, incoming = tmp_path / "initial.csv", tmp_path / "incoming.csv"
    _source(original)
    _source(incoming)
    visible = tmp_path / "visible"
    first = _cli(original, "--out", visible, "--rule", "uvvis_spectrum", "--export", "pdf,tiff_300")
    project = Path(first["project_dir"])
    document = Path(first["document"])
    raw = _files(project / "raw"), _files(project / "source")
    original_bytes = original.read_bytes()
    processes = []
    popen = subprocess.Popen
    def owned_popen(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(subprocess, "Popen", owned_popen)
    try:
        first_review = preview_project_source_update(project, incoming)
        assert first_review["status"] == "ready", first_review
        apply_project_source_update(project, first_review)
        repository = project_store(project, with_snapshot=True)
        v0 = file_sha256(incoming)
        before = repository.snapshot()
        owners = [identity for identity, versions in before["sources"].items()
                  if versions.get(v0, {}).get("locator") == str(incoming)]
        assert len(owners) == 1
        identity = owners[0]
        _source(incoming, changed=True)
        v1 = file_sha256(incoming)
        assert v1 != v0
        review = preview_project_source_update(project, incoming)
        assert review["status"] == "ready" and review["source"] == str(incoming), review
        starts = len(processes)
        with monkeypatch.context() as frozen:
            frozen.setattr(source_update, "prepare_candidate", lambda *_a, **_kw: pytest.fail("frozen preview must not reprepare"))
            assert preview_project_source_update(project, incoming) == review
            assert len(processes) == starts
            applied = apply_project_source_update(project, review)
            assert applied["status"] == "updated" and len(processes) == starts
        after = repository.snapshot()
        assert {v0, v1}.issubset(after["sources"][identity])
        assert repository.resolve_source(identity, v0).read_bytes() != repository.resolve_source(identity, v1).read_bytes()
        assert (after["sequence"] - before["sequence"]) == 1
        state = _native(document)
        assert state["series"]["B"]["y"] == [9, 10, 11]
        assert state["series"]["A"]["y"] == [8, 9, 10]
        assert (_files(project / "raw"), _files(project / "source")) == raw
        assert original.read_bytes() == original_bytes
        spec_bytes = (project / "studio/spec.json").read_bytes()
        native_bytes = document.read_bytes()
        bundle = repository.export_bundle(tmp_path / "portable")
        cold = FileProjectStore.import_bundle(bundle, tmp_path / "cold")
        project.rename(tmp_path / "project-offline")
        incoming.rename(tmp_path / "incoming-offline.csv")
        visible.rename(tmp_path / "visible-offline")
        inspected = inspect_project(cold.root, native=True)
        assert inspected["status"] == "ok" and inspected["source"]["current"] is True
        exported = export_native_document_artifacts(cold.root / "studio/document.vsz", formats=["pdf", "tiff_300"])
        assert exported["standalone_export"]["export_ready"] is True, exported
        assert (cold.root / "studio/spec.json").read_bytes() == spec_bytes
        assert (cold.root / "studio/document.vsz").read_bytes() == native_bytes
        assert (_files(cold.root / "raw"), _files(cold.root / "source")) == raw
        current = project_store(cold.root).snapshot()
        assert {v0, v1}.issubset(current["sources"][identity])
        assert not project.exists() and not incoming.exists() and not visible.exists()
        (tmp_path / "source-versions-evidence.json").write_text(json.dumps({
            "pid": os.getpid(), "parent_pid": os.getppid(), "project_id": after["project_id"],
            "source_id": identity, "original_literal": str(incoming), "v0": v0, "v1": v1,
            "generation": after["generation"], "cold_generation": current["generation"],
            "native_sha256": file_sha256(cold.root / "studio/document.vsz"),
            "checks": ["same_original_locator_new_version", "stable_source_id", "sealed_v0_preserved",
                "frozen_preview_and_apply_no_worker", "original_raw_source_preserved", "cold_public_inspect_export"]}, indent=2))
    finally:
        _close_workers()
        assert all(process.poll() is not None for process in processes)
        (tmp_path / "source-version-workers.json").write_text(json.dumps([
            {"pid": process.pid, "returncode": process.returncode} for process in processes], indent=2))
