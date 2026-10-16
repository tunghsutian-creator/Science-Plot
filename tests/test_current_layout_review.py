"""Only exact byte-bound, supported current geometry can supersede a stale issue."""

from copy import deepcopy
import math

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.current_layout_review import current_legend_issues
from sciplot_core.veusz_audit.legend_geometry import _clip, _segment_box


@pytest.mark.parametrize("distance,severity", [(0, "critical"), (1, "warning"), (2, "info"), (7, "info")])
def test_current_legend_measurement_preserves_generated_issue_and_target(tmp_path, distance, severity):
    document = tmp_path / "document.vsz"
    document.write_bytes(b"exact current native")
    issues = [{"id": "legend_curve_clearance_below_target", "severity": "critical",
               "required_clearance_mm": 2, "measured_clearance_mm": 0},
              {"id": "unrelated_scientific_issue", "severity": "critical"}]
    original = deepcopy(issues)
    audit = {"path": str(document), "sha256": file_sha256(document), "legend_geometry": {
        "coverage_complete": True, "legends": [{"path": "/page1/graph1/key1", "graph_path": "/page1/graph1", "minimum_curve_clearance_mm": distance}]}}
    result = current_legend_issues(issues, document, audit)
    measured = next(item for item in result if item["id"] == issues[0]["id"])
    assert measured["severity"] == severity
    assert measured["required_clearance_mm"] == 2
    assert measured["generated_issue"] == original[0]
    assert original[1] in result and issues == original


@pytest.mark.parametrize("invalid", ["path", "sha", "unsupported", "missing", "nan", "empty", "wrong_key", "wrong_graph"])
def test_unverified_current_geometry_cannot_clear_critical(tmp_path, invalid):
    document = tmp_path / "document.vsz"
    document.write_bytes(b"native")
    issues = [{"id": "legend_curve_clearance_below_target", "severity": "critical",
               "required_clearance_mm": 2, "measured_clearance_mm": 0}]
    geometry = {"coverage_complete": True, "legends": [{"path": "/page1/graph1/key1", "graph_path": "/page1/graph1", "minimum_curve_clearance_mm": 8}]}
    audit = {"path": str(document), "sha256": file_sha256(document), "legend_geometry": geometry}
    if invalid == "path":
        audit["path"] = str(tmp_path / "other.vsz")
    elif invalid == "sha":
        document.write_bytes(b"changed native")
    elif invalid == "unsupported":
        geometry["coverage_complete"] = False
    elif invalid == "missing":
        geometry["legends"][0].clear()
    elif invalid == "wrong_key":
        geometry["legends"][0]["path"] = "/page1/graph1/key2"
    elif invalid == "wrong_graph":
        geometry["legends"][0]["graph_path"] = "/page1/graph2"
    elif invalid == "nan":
        geometry["legends"][0]["minimum_curve_clearance_mm"] = math.nan
    else:
        geometry["legends"] = []
    result = current_legend_issues(issues, document, audit)
    assert result[0] == issues[0]
    assert result[-1]["id"] == "current_legend_geometry_unavailable"
    assert result[-1]["severity"] == "critical"
    assert current_legend_issues([], document, audit)[0]["severity"] == "critical"


def test_new_overlap_is_found_without_a_generated_issue(tmp_path):
    document = tmp_path / "document.vsz"
    document.write_bytes(b"native")
    audit = {"path": str(document), "sha256": file_sha256(document), "legend_geometry": {
        "coverage_complete": True, "legends": [{"path": "/page1/graph1/key1", "graph_path": "/page1/graph1", "minimum_curve_clearance_mm": 0}]}}
    issue = current_legend_issues([], document, audit)[0]
    assert issue["severity"] == "critical" and issue["required_clearance_mm"] == 2
    assert "generated_issue" not in issue


def test_sparse_segment_crosses_legend_even_when_endpoints_are_outside():
    box = [4., 4., 6., 6.]
    assert _segment_box((0., 0.), (10., 10.), box) == 0
    assert _segment_box((0., 0.), (10., 0.), box) == 4
    assert _clip((-10., 5.), (10., 5.), [0., 0., 8., 8.]) == ((0., 5.), (8., 5.))


def _fake_curve(monkeypatch, xs, ys, *, handling="break-on", width=.1):
    from types import SimpleNamespace as NS
    import numpy as np
    from sciplot_core.veusz_audit import legend_geometry as geometry

    class Settings(NS):
        def get(self, name):
            return getattr(self, name)
    class Data:
        def __init__(self, values):
            self.values = values
        def getData(self, _doc, **_kwargs):
            return NS(data=np.array(self.values)) if self.values is not None else None
    def hidden(hide):
        return Settings(hide=hide, setdict={"hide": NS(val=hide)})
    line = hidden(False)
    line.steps, line.interpType, line.style, line.width = "off", "linear", "solid", width
    settings = Settings(PlotLine=line, FillAbove=hidden(True), FillBelow=hidden(True),
                        xData=Data(xs), yData=Data(ys), scalePoints=Data(None),
                        Color=Settings(points=Data(None)), labels=Data(None),
                        errorStyle="none", marker="none", nanHandling=handling)
    axis = NS(dataToPlotterCoords=lambda _bounds, values: values * 72 / 25.4)
    class Widget:
        pass
    native = Widget()
    native.typename, native.settings, native.document = "xy", settings, None
    native.fetchAxes = lambda: (axis, axis)
    native.clipAxesBounds = lambda *_args: NS(getCoords=lambda: [v * 72 / 25.4 for v in [0, 0, 10, 10]])
    helper = NS(states={(native, 0): NS(bounds=[0, 0, 10, 10])})
    monkeypatch.setattr(geometry, "_distance_pt", lambda value, _helper: value)
    return native, {"helper": helper}, Data


@pytest.mark.parametrize("handling,expected", [("break-on", math.inf), ("ignore", 0)])
def test_current_geometry_respects_nan_breaks_and_checks_whole_visible_segment(monkeypatch, handling, expected):
    from sciplot_core.veusz_audit.legend_geometry import _curve_distance
    native, state, Data = _fake_curve(monkeypatch, [-1., math.nan, 11.], [5., math.nan, 5.], handling=handling)
    assert _curve_distance(native, state, [4, 4, 6, 6]) == expected
    settings = native.settings
    for group, name in ((settings, "scalePoints"), (settings.Color, "points"), (settings, "labels")):
        previous = getattr(group, name)
        setattr(group, name, Data([math.nan]))
        with pytest.raises(ValueError, match="segmentation"):
            _curve_distance(native, state, [4, 4, 6, 6])
        setattr(group, name, previous)


@pytest.mark.parametrize("xs,ys,box", [
    ([0, 3], [0, 0], [3.3, .3, 4, 1]),  # Square cap corner exceeds a half-width disk.
    ([-.2, -.2], [-1, 11], [0, 4, .1, 6]),  # Off-frame centerline still paints inside.
])
def test_native_thick_stroke_caps_and_expanded_clipping_remain_blocking(monkeypatch, xs, ys, box):
    from sciplot_core.veusz_audit.legend_geometry import _curve_distance
    native, state, _ = _fake_curve(monkeypatch, xs, ys, width=2.)
    assert _curve_distance(native, state, box) == 0


@pytest.mark.parametrize("change", ["step", "bezier", "fill", "error", "missing"])
def test_unsupported_curve_geometry_is_explicit(monkeypatch, change):
    from sciplot_core.veusz_audit.legend_geometry import _curve_distance
    native, state, Data = _fake_curve(monkeypatch, [0, 10], [0, 10])
    s = native.settings
    if change == "step":
        s.PlotLine.steps = "centre"
    elif change == "bezier":
        s.PlotLine.interpType = "tight-Bezier"
    elif change == "fill":
        s.FillAbove.setdict["hide"].val = False
    elif change == "error":
        s.errorStyle = "bar"
        data = s.xData.getData(None)
        data.serr = [1., 1.]
        s.xData.getData = lambda *_args: data
    else:
        s.xData = Data(None)
    with pytest.raises(ValueError):
        _curve_distance(native, state, [4, 4, 6, 6])


@pytest.mark.parametrize("invalid", [None, "wrong_key", "wrong_graph", "missing", "unsupported", "stale"])
def test_only_byte_bound_explicit_native_hide_can_clear_a_prior_issue(tmp_path, invalid):
    document = tmp_path / "document.vsz"
    document.write_bytes(b"native hidden key")
    issues = [{"id": "legend_curve_clearance_below_target", "severity": "critical",
               "required_clearance_mm": 2, "measured_clearance_mm": 0}]
    audit = {"path": str(document), "sha256": file_sha256(document), "legend_geometry": {
        "coverage_complete": True, "legends": [], "hidden_legends": [
            {"path": "/page1/graph1/key1", "graph_path": "/page1/graph1", "hidden": True}]}}
    geometry = audit["legend_geometry"]
    if invalid == "wrong_key":
        geometry["hidden_legends"][0]["path"] = "/page1/graph1/key2"
    elif invalid == "wrong_graph":
        geometry["hidden_legends"][0]["graph_path"] = "/page1/graph2"
    elif invalid == "missing":
        geometry["hidden_legends"] = []
    elif invalid == "unsupported":
        geometry["coverage_complete"] = False
    elif invalid == "stale":
        document.write_bytes(b"unverified edit")
    result = current_legend_issues(issues, document, audit)
    if invalid:
        assert result[0] == issues[0] and result[-1]["severity"] == "critical"
    else:
        assert result[0]["severity"] == "info" and result[0]["native_legend_hidden"] is True
        assert result[0]["generated_issue"] == issues[0]


@pytest.mark.parametrize("missing", ["key", "curve"])
def test_visible_native_widgets_missing_paint_state_cannot_establish_clearance(monkeypatch, missing):
    import sys
    from types import SimpleNamespace as NS, ModuleType
    from sciplot_core.veusz_audit.legend_geometry import collect_legend_geometry

    class ControlKey:
        pass
    module = ModuleType("veusz.widgets.key")
    module.ControlKey = ControlKey
    monkeypatch.setitem(sys.modules, "veusz.widgets.key", module)
    parent = NS(path="/page1/graph1")
    key = NS(typename="key", parent=parent, settings=NS(hide=False, setdict={}))
    curve = NS(typename="xy", parent=parent, settings=NS(setdict={"PlotLine": object()}))
    control = ControlKey()
    control.widget, control.posn, control.dims = key, (0, 0), (10, 10)
    states = {} if missing == "key" else {
        "/page1/graph1/key1": {"helper": NS(getControlGraph=lambda _widget: [control]), "page": 1}}
    result = collect_legend_geometry([("/page1/graph1/key1", key), ("/page1/graph1/series_1", curve)], states)
    assert result["coverage_complete"] is False
    assert "painted geometry" in result["unsupported"][0]["reason"]
    assert result["legends"] == []


@pytest.mark.parametrize("target", [None, 0, math.nan, True])
def test_unknown_historical_target_cannot_inherit_a_noncritical_severity(tmp_path, target):
    document = tmp_path / "document.vsz"
    document.write_bytes(b"native")
    issues = [{"id": "legend_curve_clearance_below_target", "severity": "info", "required_clearance_mm": target}]
    audit = {"path": str(document), "sha256": file_sha256(document), "legend_geometry": {
        "coverage_complete": True, "legends": [{"path": "/page1/graph1/key1", "graph_path": "/page1/graph1", "minimum_curve_clearance_mm": 0}]}}
    result = current_legend_issues(issues, document, audit)
    assert result[0] == issues[0] and result[-1]["severity"] == "critical"
