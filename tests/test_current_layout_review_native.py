"""Public native legend edits recover clear layouts and retain overlap blockers."""

import csv
import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.annotation_operations import preview_document_operations
from sciplot_core.studio_core.document_edit import apply_document_edit
from sciplot_core.studio_core.project_query import inspect_project, resolve_project_figure
from sciplot_core.studio_core.review_artifacts import _current_layout_issues
from sciplot_core.qa.audit_support import _run_veusz_audit


@pytest.mark.comprehensive
@pytest.mark.parametrize("position,old_issue,markers,hidden,expected", [
    (.03, True, False, False, "passed"), (.70, True, False, False, "failed"),
    (.70, False, False, False, "failed"), (.70, False, True, False, "failed"),
    (.03, True, False, True, "passed")])
def test_current_native_legend_layout_uses_current_geometry_without_changing_science(
        tmp_path, position, old_issue, markers, hidden, expected):
    source = tmp_path / "stress_relaxation.csv"
    with source.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([name for i in range(5) for name in (f"S{i}|t_s", f"S{i}|sigma_over_sigma0")])
        for time in (.1, 1., 10., 100., 1000.):
            writer.writerow([v for i in range(5) for v in (time, .6 + i * .08)])
    source_bytes = source.read_bytes()
    created = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "studio", str(source),
        "--rule", "rheology_stress_relaxation", "--json"], capture_output=True, text=True, timeout=90, check=True)
    project = Path(json.loads(created.stdout)["project_dir"])
    selected = resolve_project_figure(project, None)
    document, spec_path = Path(selected["document"]), Path(selected["spec"])
    spec = json.loads(spec_path.read_text())
    # Generated control models a prior placement's immutable diagnostic.
    spec["layout_issues"] = ([{"id": "legend_curve_clearance_below_target", "severity": "critical",
                              "required_clearance_mm": 2., "measured_clearance_mm": 0.}] if old_issue else [])
    spec_path.write_text(json.dumps(spec))
    objects = inspect_project(project, figure_id=selected["figure_id"])["selected_figure"]["objects"]
    def style(path, suffix, value):
        setting = path + "/" + suffix
        field = next(f for f in objects[path]["editable_fields"] if f["setting_path"] == setting)
        return {"op": "set_style", "object_path": path, "setting_path": setting,
                "expected_value": field["current_value"], "value": value}
    key = "/page1/graph1/key1"
    operations = [style(key, suffix, value) for suffix, value in
                  (("columns", 1), ("horzPosn", "manual"), ("vertPosn", "manual"),
                   ("horzManual", .03), ("vertManual", position))]
    if hidden:
        operations.append({"op": "set_legend_visibility", "expected_visible": True, "visible": False})
    if markers:
        # No connecting lines: only actual marker footprints can trigger this negative.
        for i in range(1, 6):
            path = f"/page1/graph1/series_{i}"
            operations.extend(style(path, suffix, value) for suffix, value in
                              (("marker", "square"), ("markerSize", "6pt"), ("PlotLine/transparency", 100)))
    preview = preview_document_operations(project, operations, figure_id=selected["figure_id"],
        expected_document_sha256=file_sha256(document), output_dir=tmp_path / "preview")
    apply_document_edit(project, preview)
    spec = json.loads(spec_path.read_text())
    assert spec["legend"]["show"] is (not hidden)
    before = {str(p): p.read_bytes() for p in (source, document, spec_path)}
    audit, error = _run_veusz_audit([document])
    assert error is None and audit is not None
    native = audit["documents"][0]
    assert native["legend_geometry"]["coverage_complete"], native["legend_geometry"]
    if hidden:
        assert native["legend_geometry"]["legends"] == []
        assert native["legend_geometry"]["hidden_legends"][0]["hidden"] is True
    issues = _current_layout_issues(spec, document_path=document, native_audit=native)
    assert ("failed" if issues[0]["severity"] == "critical" else "passed") == expected, issues
    if old_issue:
        assert issues[0]["generated_issue"] == spec["layout_issues"][0]
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "studio", str(project),
        "--export", "pdf,tiff_300", "--json"], capture_output=True, text=True, timeout=90)
    receipt = json.loads(result.stdout)
    run = receipt["studio_run"]
    assert run["qa"]["studio_layout"]["status"] == expected, run
    assert run["ready_to_use"] is (expected == "passed"), run
    assert before == {str(p): p.read_bytes() for p in (source, document, spec_path)}
    assert source.read_bytes() == source_bytes


@pytest.mark.comprehensive
@pytest.mark.parametrize("marker", ["circle", "square"])
def test_native_marker_path_uses_radius_scale_and_equal_area(marker):
    import sys
    from sciplot_core.veusz_runtime import veusz_worker_environment

    script = r"""
import math
import sys
from types import SimpleNamespace as NS
from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
from sciplot_core.veusz_audit import legend_geometry
ensure_veusz_runtime_path()
ensure_veusz_loader_compat()
class Settings(NS):
    def get(self, name):
        return getattr(self, name)
settings = Settings(marker=sys.argv[1], markerSize=10.,
    MarkerLine=Settings(width=1., setdict={"hide": NS(val=True)}),
    MarkerFill=Settings(newMarkerSizes=False))
legend_geometry._distance_pt = lambda value, _helper: value
radius = legend_geometry._marker_radius(settings, None)
# Native markerSize is a radius scale; the envelope includes every path corner.
assert math.isclose(radius, math.sqrt(2) * 10 * 25.4 / 72, rel_tol=1e-6), radius
settings.MarkerFill.newMarkerSizes = True
assert legend_geometry._marker_radius(settings, None) <= radius
settings.MarkerLine.setdict["hide"].val = False
assert legend_geometry._marker_radius(settings, None) > radius * .8
# A single point at (0,0) overlaps the key at x=3 mm by its actual marker.
# The former diameter-based envelope left a false positive clearance here.
class Data:
    def getData(self, _doc, **_kwargs):
        return NS(data=[0.])
class Empty:
    def getData(self, _doc, **_kwargs):
        return None
hidden = Settings(setdict={"hide": NS(val=True)})
settings.PlotLine = Settings(steps="off", interpType="linear", style="solid", width=1., setdict={"hide": NS(val=True)})
settings.FillAbove = settings.FillBelow = hidden
settings.xData = settings.yData = Data()
settings.scalePoints = settings.labels = Empty()
settings.Color = Settings(points=Empty())
settings.errorStyle, settings.nanHandling = "none", "break-on"
class Widget:
    typename, document = "xy", None
widget = Widget()
widget.settings = settings
axis = NS(dataToPlotterCoords=lambda _bounds, _data: [0.])
widget.fetchAxes = lambda: (axis, axis)
widget.clipAxesBounds = lambda *_args: NS(getCoords=lambda: [-30., -30., 30., 30.])
helper = NS(states={(widget, 0): NS(bounds=[-30., -30., 30., 30.])})
assert legend_geometry._curve_distance(widget, {"helper": helper}, [3., -1., 4., 1.]) == 0
"""
    result = subprocess.run([sys.executable, "-c", script, marker], capture_output=True,
                            text=True, timeout=30, env=veusz_worker_environment())
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.comprehensive
def test_native_audit_rejects_a_document_changed_after_loading(tmp_path):
    import sys
    from sciplot_core.veusz_runtime import veusz_worker_environment

    script = r"""
import sys
from pathlib import Path
from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
ensure_veusz_runtime_path()
ensure_veusz_loader_compat()
from veusz import document, widgets, dataimport
from PyQt6.QtWidgets import QApplication
from sciplot_core.veusz_audit import document as audit_owner
app = QApplication([])
path = Path(sys.argv[1])
doc = document.Document()
ci = document.CommandInterface(doc)
ci.Add("page", name="page1", autoadd=False)
ci.Save(str(path))
original = audit_owner.collect_legend_geometry
def change_after_paint(*args):
    result = original(*args)
    path.write_bytes(path.read_bytes() + b"\n# concurrent native save\n")
    return result
audit_owner.collect_legend_geometry = change_after_paint
try:
    audit_owner._audit_document(path)
except ValueError as exc:
    assert "changed while" in str(exc), str(exc)
else:
    raise AssertionError("Audit accepted geometry loaded from different native bytes")
app.quit()
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path / "document.vsz")],
                            capture_output=True, text=True, timeout=30, env=veusz_worker_environment())
    assert result.returncode == 0, result.stdout + result.stderr
