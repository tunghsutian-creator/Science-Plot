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
    edits = []
    for path, field_id, value in [
        ("/page1/graph1/x", "axis_label_size", "10pt"),
        ("/page1/graph1/series_1", "series_line_color", "#A020F0"),
        ("/page1/graph1/series_1", "series_line_width", "2pt"),
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
    assert len(result["changes"]) == 3
    reopened = _worker("inspect-document-state", str(candidate))
    assert reopened["widgets"]["/page1/graph1/x"]["settings"]["Label/size"] == "10pt"
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
