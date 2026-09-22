from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.native_settings import editable_fields, validate_native_setting
from sciplot_core.render import render_to_dir
from sciplot_core.veusz_runtime import veusz_worker_environment
from sciplot_core.veusz_worker.widget_bindings import _visible_data_bindings
from sciplot_gui.studio_assistant.selection import SelectionMixin


class Setting:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def normalize(self, value):
        return value


class Document:
    def __init__(self, values):
        self.settings = {key: Setting(value) for key, value in values.items()}

    def resolveSettingPath(self, _root, path):
        if path not in self.settings:
            raise ValueError(path)
        return self.settings[path]


def test_safe_fields_are_a_subset_of_the_shared_catalog() -> None:
    widget = SimpleNamespace(path="/g/x", typename="axis")
    doc = Document({"/g/x/Label/size": "8pt", "/g/x/label": "Force (N)",
                    "/g/x/min": 0, "/g/x/log": False, "/g/x/hide": False})
    all_fields = editable_fields(doc, widget)
    safe = editable_fields(doc, widget, safe_only=True)
    assert {item["field_id"] for item in all_fields} == {
        "axis_label_size", "axis_label", "axis_min", "axis_log", "hidden",
    }
    assert safe == [item for item in all_fields if item["field_id"] == "axis_label_size"]


def test_y_axis_visibility_is_bounded_and_preserves_axis_semantics() -> None:
    parent = SimpleNamespace(children=[])
    y = SimpleNamespace(path="/page1/graph1/y", typename="axis", parent=parent)
    curve = SimpleNamespace(path="/page1/graph1/xy", typename="xy", parent=parent)
    parent.children = [y, curve]
    doc = Document({"/page1/graph1/y/hide":False, "/page1/graph1/y/label":"Intensity (%)",
        "/page1/graph1/y/min":0, "/page1/graph1/xy/xData":"x",
        "/page1/graph1/xy/yData":"y", "/page1/graph1/xy/Color/points":""})
    field, = editable_fields(doc, y, safe_only=True)
    assert field['setting_path'] == '/page1/graph1/y/hide'
    assert validate_native_setting(doc, field, expected_value=False, value=True, safe_only=True) == (False,True)
    with pytest.raises(ValueError, match='boolean'):
        validate_native_setting(doc, field, expected_value=False, value='true', safe_only=True)
    assert doc.settings['/page1/graph1/y/label'].get() == 'Intensity (%)'
    parent.children.append(SimpleNamespace(typename='colorbar'))
    assert editable_fields(doc, y, safe_only=True) == []


@pytest.mark.parametrize("path,kind,parent_hidden,include,expected", [
    ("/page1/graph1/y", "axis", False, True, True),
    ("/page1/graph1/y", "axis", False, False, False),
    ("/page1/graph1/y", "axis", True, True, False),
    ("/page1/graph1/x", "axis", False, True, False),
    ("/page1/graph2/y", "axis", False, True, False),
    ("/page1/graph1/y", "xy", False, True, False),
])
def test_axis_audit_exception_never_exposes_hidden_data_or_ancestors(
    path, kind, parent_hidden, include, expected,
) -> None:
    def settings(**values):
        return SimpleNamespace(setdict={k: SimpleNamespace(val=v) for k, v in values.items()})
    parent = SimpleNamespace(parent=None, settings=settings(hide=parent_hidden))
    node = SimpleNamespace(
        typename=kind, name=path.rsplit("/", 1)[-1], parent=parent,
        settings=settings(hide=True, label="Original units"),
    )
    doc = SimpleNamespace(walkNodes=lambda collect, **kwargs: collect(path, node))
    records = _visible_data_bindings(
        doc, widget_type=kind, setting_names=("label",), include_hidden_y_axis=include,
    )
    assert bool(records) is expected
    if expected:
        assert records[0]["bindings"]["label"] == "Original units"


@pytest.mark.parametrize("scalar,has_colorbar", [(True, False), (False, True)])
def test_scalar_encodings_do_not_advertise_curve_style_edits(scalar, has_colorbar) -> None:
    children = [SimpleNamespace(typename="colorbar")] if has_colorbar else []
    widget = SimpleNamespace(path="/g/xy", typename="xy", parent=SimpleNamespace(children=children))
    doc = Document({f"/g/xy/{key}": value for key, value in {
        "xData": "x", "yData": "y", "Color/points": "z" if scalar else "",
        "PlotLine/color": "red", "PlotLine/width": "1pt", "key": "sample",
    }.items()})
    assert editable_fields(doc, widget, safe_only=True) == []
    assert editable_fields(doc, widget)


@pytest.mark.parametrize("value", ["0pt", "-1pt", "nanpt", "2%", "1pt junk"])
def test_safe_sizes_cannot_make_scientific_marks_invisible(value) -> None:
    doc = Document({"/g/x/Label/size": "8pt"})
    cap = editable_fields(doc, SimpleNamespace(path="/g/x", typename="axis"))[0]
    with pytest.raises(ValueError, match="positive physical size"):
        validate_native_setting(doc, cap, expected_value="8pt", value=value, safe_only=True)
    assert doc.settings["/g/x/Label/size"].get() == "8pt"


def test_expected_value_checks_both_live_and_advertised_state() -> None:
    doc = Document({"/g/x/Label/size": "8pt"})
    cap = editable_fields(doc, SimpleNamespace(path="/g/x", typename="axis"))[0]
    assert validate_native_setting(doc, cap, expected_value="8pt", value="9pt") == ("8pt", "9pt")
    doc.settings["/g/x/Label/size"].value = "10pt"
    for expected in ("8pt", "10pt"):
        with pytest.raises(ValueError, match="expected value"):
            validate_native_setting(doc, cap, expected_value=expected, value="9pt")


@pytest.mark.parametrize("line_hidden,line_style,transparency,allow_none", [
    (False, "solid", 0, True), (True, "solid", 0, False),
    (False, "none", 0, False), (False, "solid", 100, False),
])
def test_curve_shape_choices_are_native_and_keep_point_only_marks(line_hidden, line_style, transparency, allow_none) -> None:
    widget = SimpleNamespace(path="/g/xy", typename="xy", parent=SimpleNamespace(children=[]))
    doc = Document({f"/g/xy/{key}": value for key, value in {
        "xData": "x", "yData": "y", "Color/points": "",
        "PlotLine/style": line_style, "marker": "circle", "markerSize": "3pt",
        "PlotLine/interpType": "linear", "errorStyle": "bar", "PlotLine/hide": line_hidden,
        "PlotLine/transparency": transparency,
    }.items()})
    doc.settings["/g/xy/PlotLine/style"].vallist = ["solid", "dashed"]
    doc.settings["/g/xy/marker"].vallist = ["none", "circle", "diamond"]
    fields = {field["field_id"]: field for field in editable_fields(doc, widget, safe_only=True)}
    assert set(fields) == {"series_line_style", "series_line_transparency", "series_marker", "series_marker_size"}
    marker = fields["series_marker"]
    assert marker["choices"] == (["none", "circle", "diamond"] if allow_none else ["circle", "diamond"])
    assert validate_native_setting(doc, marker, expected_value="circle", value="diamond", safe_only=True)[1] == "diamond"
    for value in (["not-a-native-marker"] if allow_none else ["none", "not-a-native-marker"]):
        with pytest.raises(ValueError, match="advertised choices"):
            validate_native_setting(doc, marker, expected_value="circle", value=value, safe_only=True)
    with pytest.raises(ValueError, match="positive physical size"):
        validate_native_setting(doc, fields["series_marker_size"], expected_value="3pt", value="0pt", safe_only=True)
    assert doc.settings["/g/xy/marker"].get() == "circle"


@pytest.mark.parametrize("value", [-1, 101, 2.5, True, "0"])
def test_curve_transparency_rejects_invalid_values(value):
    widget = SimpleNamespace(path="/g/xy", typename="xy", parent=SimpleNamespace(children=[]))
    doc = Document({f"/g/xy/{key}": val for key, val in {
        "xData": "x", "yData": "y", "Color/points": "", "PlotLine/transparency": 8,
    }.items()})
    cap, = editable_fields(doc, widget, safe_only=True)
    assert validate_native_setting(doc, cap, expected_value=8, value=0, safe_only=True) == (8, 0)
    with pytest.raises(ValueError):
        validate_native_setting(doc, cap, expected_value=8, value=value, safe_only=True)
    assert doc.settings['/g/xy/PlotLine/transparency'].get() == 8


@pytest.mark.parametrize("object_type,suffix,field_id", [
    ("axis", "Label/font", "axis_label_font"),
    ("axis", "TickLabels/font", "tick_label_font"),
    ("label", "Text/font", "annotation_text_font"),
    ("key", "Text/font", "legend_text_font"),
])
def test_native_font_choices_are_installed_and_rechecked(monkeypatch, object_type, suffix, field_id) -> None:
    families = ["Arial", "Times New Roman"]
    monkeypatch.setattr("sciplot_core.native_settings._font_families", lambda: list(families))
    path = f"/g/object/{suffix}"
    doc = Document({path: "Arial"})
    widget = SimpleNamespace(path="/g/object", typename=object_type)
    cap, = editable_fields(doc, widget, safe_only=True)
    assert cap["field_id"] == field_id and cap["editor"] == "choice"
    assert cap["choices"] == families
    assert validate_native_setting(doc, cap, expected_value="Arial", value="Times New Roman", safe_only=True)[1] == "Times New Roman"
    with pytest.raises(ValueError, match="advertised choices"):
        validate_native_setting(doc, cap, expected_value="Arial", value="Missing Font", safe_only=True)
    families.remove("Times New Roman")
    with pytest.raises(ValueError, match="installed native font"):
        validate_native_setting(doc, cap, expected_value="Arial", value="Times New Roman", safe_only=True)
    families.clear()
    assert editable_fields(doc, widget, safe_only=True) == []
    assert doc.settings[path].get() == "Arial"


@pytest.mark.parametrize("object_type,suffix", [
    ("axis", "Label/italic"), ("axis", "TickLabels/bold"),
    ("axis", "TickLabels/italic"), ("label", "Text/bold"),
    ("label", "Text/italic"), ("key", "Text/bold"), ("key", "Text/italic"),
])
def test_typography_toggles_are_native_booleans(object_type, suffix) -> None:
    path = f"/g/object/{suffix}"
    doc = Document({path: False})
    cap, = editable_fields(doc, SimpleNamespace(path="/g/object", typename=object_type), safe_only=True)
    assert validate_native_setting(doc, cap, expected_value=False, value=True, safe_only=True)[1] is True
    with pytest.raises(ValueError, match="boolean setting"):
        validate_native_setting(doc, cap, expected_value=False, value="true", safe_only=True)


@pytest.mark.parametrize("value", [[1, 1], [2, 1], [True], [float('nan')], [float('inf')], ['1530'], list(range(33))])
def test_manual_tick_positions_reject_invalid_coordinates_without_mutation(value):
    doc = Document({'/g/x/mode': 'numeric', '/g/x/log': False, '/g/x/MajorTicks/manualTicks': []})
    cap, = editable_fields(doc, SimpleNamespace(path='/g/x', typename='axis'), safe_only=True)
    with pytest.raises(ValueError):
        validate_native_setting(doc, cap, expected_value=[], value=value, safe_only=True)
    assert doc.settings['/g/x/MajorTicks/manualTicks'].get() == []


def test_manual_ticks_are_numeric_only_and_log_positions_remain_positive():
    widget = SimpleNamespace(path='/g/x', typename='axis')
    doc = Document({'/g/x/mode': 'numeric', '/g/x/log': False, '/g/x/MajorTicks/manualTicks': []})
    cap, = editable_fields(doc, widget, safe_only=True)
    assert validate_native_setting(doc, cap, expected_value=[], value=[1167, 1530], safe_only=True)[1] == [1167, 1530]
    assert validate_native_setting(doc, cap, expected_value=[], value=[], safe_only=True)[1] == []
    doc.settings['/g/x/log'].value = True
    with pytest.raises(ValueError, match='positive'):
        validate_native_setting(doc, cap, expected_value=[], value=[0, 10], safe_only=True)
    doc.settings['/g/x/mode'].value = 'labels'
    assert editable_fields(doc, widget, safe_only=True) == []


def test_gui_capabilities_keep_the_existing_selected_object_scope() -> None:
    widget = SimpleNamespace(path="/g/x", typename="axis")
    doc = Document({"/g/x/Label/size": "8pt", "/g/x/label": "Force (N)"})
    context = SimpleNamespace(document=doc, _object_id=lambda _widget: "object-id")
    capability = SelectionMixin._editing_capabilities(context, widget)
    assert capability["scope"] == "selected_object"
    assert capability["target_object_id"] == "object-id"
    assert capability["allowed_operations"] == [
        {"operation_type": "set_setting", "target_id": "object-id", **field}
        for field in editable_fields(doc, widget)
    ]


def _worker(*args: str, failed: bool = False) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "sciplot_core.veusz_worker", *args],
        text=True, capture_output=True, env=veusz_worker_environment(), timeout=90,
    )
    if failed:
        assert result.returncode != 0
        return {"error": result.stderr}
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.comprehensive
def test_dense_opaque_curve_pdf_keeps_all_points_as_an_editable_stroke(tmp_path):
    import fitz
    import numpy as np

    source = tmp_path / "dense.csv"
    x = np.linspace(0, 10, 12000)
    y = 2 + np.sin(x * 50)
    source.write_text("Time,Force\ns,N\nA,A\n" + "".join(
        f"{a:.15g},{b:.15g}\n" for a, b in zip(x, y, strict=True)))
    raw = source.read_bytes()
    rendered = render_to_dir(source, template="curve", output_dir=tmp_path / "render",
        export_formats=("pdf",), options={"size": "120x110"})
    document, spec = Path(rendered["veusz_documents"][0]), Path(rendered["veusz_specs"][0])
    original_hash = file_sha256(document)
    state = _worker("inspect-document-state", str(document))
    path = "/page1/graph1/series_1"
    fields = {f["setting_path"]: f for f in state["widgets"][path]["editable_fields"]}
    changes = [{"object_path": path, "setting_path": path + "/" + suffix,
        "expected_value": fields[path + "/" + suffix]["current_value"], "value": value}
        for suffix, value in (("PlotLine/color", "#338933893389"), ("PlotLine/transparency", 0))]
    request = tmp_path / "changes.json"
    request.write_text(json.dumps(changes))
    candidate = tmp_path / "candidate.vsz"
    review = _worker("edit-document", str(document), "--changes", str(request),
        "--output-document", str(candidate), "--preview-png", str(tmp_path / "preview.png"),
        "--audit-spec", str(spec))
    assert review["document_audit"]["status"] == "passed"
    exported = _worker("export-document", str(candidate), "--formats", "pdf",
        "--out", str(tmp_path / "export"))
    with fitz.open(exported["exports"][0]["path"]) as pdf:
        drawing = max(pdf[0].get_drawings(), key=lambda item: len(item["items"]))
        assert drawing["type"] == "s" and drawing["width"] == pytest.approx(1.2)
        assert len(drawing["items"]) == len(x) - 1
        assert not pdf[0].get_images()
    assert source.read_bytes() == raw and file_sha256(document) == original_hash
    # Transparency 100 cannot erase the only remaining scientific mark channel.
    changes[1]["value"] = 100
    request.write_text(json.dumps(changes))
    blocked = tmp_path / "invisible.vsz"
    failure = _worker("edit-document", str(document), "--changes", str(request),
        "--output-document", str(blocked), "--preview-png", str(tmp_path / "invisible.png"), failed=True)
    assert "must keep a visible marker" in failure["error"]
    assert not blocked.exists() and file_sha256(document) == original_hash


@pytest.mark.comprehensive
@pytest.mark.parametrize("template", ["curve", "point_line"])
def test_native_sample_style_keeps_initially_hidden_and_visible_markers_in_the_sample_color(tmp_path, template):
    from sciplot_core.studio_core.document_edit_policy import filter_editable_fields, validate_edit_science_policy
    from sciplot_core.studio_core.sample_style import expand_sample_styles

    source = tmp_path / "values.csv"
    source.write_text("Time,Force\ns,N\nA,A\n0,1\n1,3\n2,2\n")
    raw = source.read_bytes()
    rendered = render_to_dir(source, template=template, output_dir=tmp_path / "render",
                             export_formats=("pdf",), options={"size": "60x55"})
    document, spec_path = Path(rendered["veusz_documents"][0]), Path(rendered["veusz_specs"][0])
    original = file_sha256(document)
    spec = json.loads(spec_path.read_text())
    state = _worker("inspect-document-state", str(document))
    objects = filter_editable_fields(state["widgets"], spec_path)
    operations = expand_sample_styles(spec, objects, [
        {"op": "set_sample_style", "samples": ["A"], "style": {"color": "#A020F0"}}])
    assert len(operations) == 3
    changes = [{key: value for key, value in operation.items() if key != "op"} for operation in operations]
    validate_edit_science_policy(changes, spec_path)
    request = tmp_path / "changes.json"
    request.write_text(json.dumps(changes))
    candidate = tmp_path / "candidate.vsz"
    result = _worker("edit-document", str(document), "--changes", str(request),
        "--output-document", str(candidate), "--preview-png", str(tmp_path / "candidate.png"),
        "--audit-spec", str(spec_path))
    assert result["document_audit"]["status"] == "passed"
    reopened = _worker("inspect-document-state", str(candidate))["widgets"]["/page1/graph1/series_1"]
    assert all(reopened["settings"][key] == "#A020F0" for key in (
        "PlotLine/color", "MarkerFill/color", "MarkerLine/color"))
    assert file_sha256(document) == original and source.read_bytes() == raw


@pytest.mark.comprehensive
def test_native_candidate_preview_reopen_audit_and_rejected_batch(tmp_path: Path) -> None:
    source = tmp_path / "values.csv"
    source.write_text("Time,Force\ns,N\nA,A\n0,1\n1,3\n2,2\n")
    rendered = render_to_dir(source, template="curve", output_dir=tmp_path / "render",
                             export_formats=("pdf",), options={"size": "60x55"})
    document = Path(rendered["veusz_documents"][0])
    spec = Path(rendered["veusz_specs"][0])
    original = file_sha256(document)
    state = _worker("inspect-document-state", str(document))
    before = _worker("preview-document", str(document), "--out", str(tmp_path / "before.png"))
    font = next(field for field in state["widgets"]["/page1/graph1/x"]["editable_fields"]
                if field["field_id"] == "axis_label_font")
    font_name = next(name for name in font["choices"] if name != font["current_value"]
                     and name in {"Arial", "DejaVu Sans", "Times New Roman"})
    edits = []
    for path, field_id, value in [
        ("/page1/graph1/x", "axis_label_size", "10pt"),
        ("/page1/graph1/series_1", "series_line_color", "#A020F0"),
        ("/page1/graph1/series_1", "series_line_width", "2pt"),
        ("/page1/graph1/x", "major_tick_positions", [0, 0.5, 2]),
        ("/page1/graph1/x", "tick_label_rotation", "90"),
        ("/page1/graph1/series_1", "series_line_style", "dashed"),
        ("/page1/graph1/series_1", "series_marker", "diamond"),
        ("/page1/graph1/series_1", "series_marker_size", "4pt"),
        ("/page1/graph1/x", "axis_label_font", font_name),
        ("/page1/graph1/x", "axis_label_italic", True),
    ]:
        field = next(field for field in state["widgets"][path]["editable_fields"]
                     if field["field_id"] == field_id)
        edits.append({"object_path": path, "setting_path": field["setting_path"],
                      "expected_value": field["current_value"], "value": value})
    changes = tmp_path / "changes.json"
    changes.write_text(json.dumps(edits))
    candidate, png = tmp_path / "candidate.vsz", tmp_path / "after.png"
    result = _worker("edit-document", str(document), "--changes", str(changes),
                     "--output-document", str(candidate), "--preview-png", str(png), "--audit-spec", str(spec))
    assert result["document"]["sha256"] == original == file_sha256(document)
    assert result["candidate"]["sha256"] == file_sha256(candidate) != original
    assert result["preview"]["sha256"] != before["preview"]["sha256"]
    assert len(result["changes"]) == 11
    assert result["changes"][-1] == {"object_path": "/page1/graph1/series_1",
        "setting_path": "/page1/graph1/series_1/MarkerLine/hide", "old_value": True, "new_value": False}
    reopened = _worker("inspect-document-state", str(candidate))
    assert reopened["widgets"]["/page1/graph1/x"]["settings"]["Label/size"] == "10pt"
    assert reopened["widgets"]["/page1/graph1/x"]["settings"]["MajorTicks/manualTicks"] == [0, 0.5, 2]
    assert reopened["widgets"]["/page1/graph1/x"]["settings"]["TickLabels/rotate"] == "90"
    reopened_xy = reopened["widgets"]["/page1/graph1/series_1"]["editable_fields"]
    assert {field["field_id"]: field["current_value"] for field in reopened_xy
            if field["field_id"] in {"series_line_style", "series_marker", "series_marker_size"}} == {
        "series_line_style": "dashed", "series_marker": "diamond", "series_marker_size": "4pt",
    }
    reopened_axis = reopened["widgets"]["/page1/graph1/x"]["editable_fields"]
    assert next(field["current_value"] for field in reopened_axis if field["field_id"] == "axis_label_font") == font_name
    separate_audit = _worker("audit-spec-data", str(candidate), str(spec), "--allow-presentation-edits")
    assert separate_audit["status"] == "passed"
    assert result["document_audit"] == separate_audit
    # A valid first edit followed by a forbidden scientific edit must write nothing.
    edits.append({"object_path": "/page1/graph1/x", "setting_path": "/page1/graph1/x/label",
                  "expected_value": "Time (s)", "value": "Changed unit"})
    changes.write_text(json.dumps(edits))
    blocked = tmp_path / "blocked.vsz"
    error = _worker("edit-document", str(document), "--changes", str(changes),
                    "--output-document", str(blocked), "--preview-png", str(tmp_path / "blocked.png"),
                    failed=True)
    assert "outside the advertised safe setting catalog" in error["error"]
    assert not blocked.exists() and not (tmp_path / "blocked.png").exists()
    assert file_sha256(document) == original
    # Reusing the original expected value against the edited document is stale.
    changes.write_text(json.dumps(edits[:1]))
    stale = _worker("edit-document", str(candidate), "--changes", str(changes),
                    "--output-document", str(blocked), "--preview-png", str(tmp_path / "blocked.png"),
                    failed=True)
    assert "no longer has its expected value" in stale["error"]
    assert not blocked.exists()
    assert file_sha256(candidate) == result["candidate"]["sha256"]

    # The shared GUI validator and worker both use native normalization. The
    # prepared operations remain one native undoable edit on a live Document.
    undo_check = f"""
import json
from pathlib import Path
from sciplot_core.veusz_worker.document_edit import loaded_native_document, prepare_setting_batch
with loaded_native_document(Path({str(document)!r})) as d:
    from veusz.document.operations import OperationMultiple
    native, actual = prepare_setting_batch(d, json.loads({json.dumps(edits[:3])!r}))
    d.applyOperation(OperationMultiple(native, descr='SciPlot external style edit'))
    assert d.resolveSettingPath(None, '/page1/graph1/x/Label/size').get() == '10pt'
    d.undoOperation()
    assert d.resolveSettingPath(None, '/page1/graph1/x/Label/size').get() == actual[0]['old_value']
    assert d.resolveSettingPath(None, '/page1/graph1/series_1/PlotLine/color').get() == actual[1]['old_value']
    d.redoOperation()
    assert d.resolveSettingPath(None, '/page1/graph1/x/Label/size').get() == '10pt'
"""
    undone = subprocess.run([sys.executable, "-c", undo_check], text=True,
                            capture_output=True, env=veusz_worker_environment(), timeout=60)
    assert undone.returncode == 0, undone.stderr
