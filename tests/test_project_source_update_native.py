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
        if path.is_file()
    }


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
