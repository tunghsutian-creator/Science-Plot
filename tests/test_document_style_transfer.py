from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.render import render_to_dir
from sciplot_core.veusz_runtime import veusz_worker_environment
from sciplot_core.veusz_worker.style_transfer import _style_plan


def _spec(labels: tuple[str, ...] = ("A", "B")) -> dict:
    return {
        "template": "curve",
        "axes": {"x": {"label": "Time (s)"}, "y": {"label": "Force (N)"}},
        "series": [
            {"name": f"series_{index}", "label": label}
            for index, label in enumerate(labels, start=1)
        ],
    }


def _xy_widgets(colors: tuple[str, ...]) -> dict:
    return {
        f"/page1/graph1/series_{index}": {
            "type": "xy",
            "settings": {
                "PlotLine/color": color,
                "PlotLine/width": "2pt",
                "hide": True,
                "xData": "old_x",
                "yData": "old_y",
                "thinfactor": 5,
            },
        }
        for index, color in enumerate(colors, start=1)
    }


def test_style_plan_matches_reordered_samples_and_excludes_science() -> None:
    old, new = _spec(), _spec(("B", "A"))
    operations, _ = _style_plan(
        old, new, _xy_widgets(("red", "blue")), _xy_widgets(("black", "black"))
    )
    colors = {
        item["current_widget"]: item["after"]
        for item in operations
        if item["setting"] == "PlotLine/color"
    }
    assert colors == {"/page1/graph1/series_1": "blue", "/page1/graph1/series_2": "red"}
    assert not {"hide", "xData", "yData", "thinfactor"} & {
        item["setting"] for item in operations
    }


def test_style_plan_rejects_unit_change_and_ambiguous_labels() -> None:
    old, new = _spec(), _spec()
    new["axes"]["y"]["label"] = "Force (kN)"
    operations, skipped = _style_plan(
        old, new, _xy_widgets(("red", "blue")), _xy_widgets(("black", "black"))
    )
    assert operations == []
    assert skipped == [{"reason": "axis_meaning_or_unit_changed"}]
    ambiguous = _spec(("A", "A"))
    operations, skipped = _style_plan(
        ambiguous,
        _spec(),
        _xy_widgets(("red", "blue")),
        _xy_widgets(("black", "black")),
    )
    assert operations == []
    assert all(item["reason"] == "new_or_ambiguous_series_identity" for item in skipped)


def test_style_plan_keeps_condition_color_encoding_and_generated_legend_layout() -> (
    None
):
    old = _spec()
    old["categorical"] = {"presentation_kind": "grouped_bar_error"}
    new = deepcopy(old)
    old_widgets, new_widgets = (
        _xy_widgets(("red", "blue")),
        _xy_widgets(("black", "black")),
    )
    old["legend"] = {
        "horz_position": "manual",
        "vert_position": "manual",
        "horz_manual": 0.2,
        "vert_manual": 0.8,
    }
    old_widgets["/page1/graph1/key1"] = {
        "type": "key",
        "settings": {
            "horzPosn": "manual",
            "vertPosn": "manual",
            "horzManual": 0.2,
            "vertManual": 0.8,
        },
    }
    new_widgets["/page1/graph1/key1"] = {
        "type": "key",
        "settings": {
            "horzPosn": "manual",
            "vertPosn": "manual",
            "horzManual": 0.6,
            "vertManual": 0.1,
        },
    }
    operations, skipped = _style_plan(old, new, old_widgets, new_widgets)
    assert operations == []
    assert skipped[0]["reason"] == "semantic_color_encoding_kept_from_new_source"
    assert skipped[1]["reason"] == "new_source_legend_layout_kept"


def _worker(*arguments: str) -> dict:
    run = subprocess.run(
        [sys.executable, "-m", "sciplot_core.veusz_worker", *arguments],
        capture_output=True,
        text=True,
        env=veusz_worker_environment(),
        timeout=90,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _render(
    root: Path, *, changed: bool = False, unit: str = "nm"
) -> tuple[Path, Path]:
    root.mkdir()
    source = root / "values.csv"
    source.write_text(
        f"Wavelength,Absorbance,Wavelength,Absorbance\n{unit},a.u.,{unit},a.u.\n"
        + (
            "B,B,A,A\n400,9,400,8\n450,10,450,9\n500,11,500,10\n"
            if changed
            else "A,A,B,B\n400,1,400,2\n450,2,450,3\n500,3,500,4\n"
        )
    )
    result = render_to_dir(
        source,
        template="curve",
        output_dir=root / "render",
        export_formats=("pdf",),
        options={"size": "60x55"},
    )
    return Path(result["veusz_documents"][0]), Path(result["veusz_specs"][0])


@pytest.mark.comprehensive
def test_native_style_transfer_keeps_new_values_and_moves_styles_with_sample(
    tmp_path: Path,
) -> None:
    old, old_spec = _render(tmp_path / "old")
    new, new_spec = _render(tmp_path / "new", changed=True)
    code = f"""
from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
ensure_veusz_runtime_path();ensure_veusz_loader_compat()
from PyQt6 import QtWidgets
from veusz import document,widgets,dataimport
from veusz.document import CommandInterface
app=QtWidgets.QApplication([])
d=document.Document();d.load({str(old)!r});i=CommandInterface(d)
i.To('/page1/graph1/x');i.Set('Label/size','9pt');i.Set('min',0.0)
i.To('/page1/graph1/series_1');i.Set('PlotLine/color','#A020F0');i.Set('PlotLine/width','2.4pt')
i.Save({str(old)!r})
"""
    edited = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=veusz_worker_environment(),
        timeout=60,
    )
    assert edited.returncode == 0, edited.stderr
    old_hash = file_sha256(old)
    before = _worker("inspect-document-state", str(new))
    receipt = _worker(
        "transfer-styles", str(old), str(new), str(old_spec), str(new_spec)
    )
    assert receipt["applied_count"] > 0
    assert file_sha256(old) == old_hash
    after = _worker("inspect-document-state", str(new))
    current_widgets = after["widgets"]
    assert current_widgets["/page1/graph1/x"]["settings"]["Label/size"] == "9pt"
    assert (
        current_widgets["/page1/graph1/x"]["settings"]["min"]
        == before["widgets"]["/page1/graph1/x"]["settings"]["min"]
    )
    series = current_widgets["/page1/graph1/series_2"]["settings"]
    assert series["PlotLine/color"] == "#A020F0"
    assert series["PlotLine/width"] == "2.4pt"
    assert (
        _worker(
            "audit-spec-data", str(new), str(new_spec), "--allow-presentation-edits"
        )["status"]
        == "passed"
    )


@pytest.mark.comprehensive
def test_native_style_transfer_skips_changed_units_without_rewriting(
    tmp_path: Path,
) -> None:
    old, old_spec = _render(tmp_path / "old")
    new, new_spec = _render(tmp_path / "new", unit="um")
    before = file_sha256(new)
    receipt = _worker(
        "transfer-styles", str(old), str(new), str(old_spec), str(new_spec)
    )
    assert receipt["transfer_status"] == "skipped"
    assert receipt["skipped"] == [{"reason": "axis_meaning_or_unit_changed"}]
    assert file_sha256(new) == before
