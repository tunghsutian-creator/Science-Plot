"""Exercise supported saved scientific coordinates and an unrepresentable widget."""
import json
from pathlib import Path

import pytest
from managed_plot_helpers import patch
from test_legacy_saved_plot import _old_project, _tree

from sciplot_core.cli import main
from sciplot_core.foundation.file_hashing import file_sha256

_SAVED_AXES = """
To('/page1/graph1/x')
Set('label', 'Time (s)')
Set('min', 0.)
Set('max', 3.)
To('/page1/graph1/y')
Set('label', 'Signal (V)')
Set('min', 0.)
Set('max', 4.)
"""


def _original(tmp_path):
    project, native = _old_project(tmp_path)
    with native.open("a") as stream:
        stream.write(_SAVED_AXES)
    return project, native


@pytest.mark.comprehensive
def test_legacy_conversion_creates_editable_copy_with_exact_arrays_units_and_marks(tmp_path, capsys):
    from PIL import Image, ImageChops
    from sciplot_core.plot_engine.storage import load_head, read
    from sciplot_core.veusz_worker.operations import export_document

    archive, native = _original(tmp_path)
    before = _tree(archive)
    old = export_document(native, formats=["tiff_300"], output_dir=tmp_path / "old-redraw")
    destination = tmp_path / "converted"
    assert main(["project", "legacy-convert", str(archive), "--out", str(destination), "--json"]) == 0
    converted = json.loads(capsys.readouterr().out)
    assert converted["status"] == "converted" and converted["plot_type"] == "ManagedPlot"
    assert converted["original_vsz"] == {"path": str(native), "sha256": file_sha256(native)}
    root = Path(converted["plot"])
    assert root.is_relative_to(destination)
    head = load_head(root)
    ir = read(Path(head["binding"]["ir_path"]))
    columns = ir["datasets"]["saved:xy"]["columns"]
    assert [(item["unit"], item["values"]) for item in columns.values()] == [
        ("s", [0., 1., 2.]), ("V", [1., 3., 2.])]
    axes = ir["views"][0]["axes"]
    assert [axis["label"] for axis in axes] == ["Time (s)", "Signal (V)"]
    assert [scale["domain"] for scale in ir["scales"]] == [[0., 3.], [0., 4.]]
    marks = ir["views"][0]["layers"][0]["marks"]
    assert [mark["type"] for mark in marks] == ["line", "point"]
    assert marks[0]["style"]["line_width_pt"] == .5
    exported = {record["format"]: record["path"] for record in converted["exports"]}
    with Image.open(old["exports"][0]["path"]) as original, Image.open(exported["tiff_300"]) as redraw:
        assert abs(original.width - redraw.width) <= 1 and abs(original.height - redraw.height) <= 1
        for image in (original, redraw):
            assert ImageChops.difference(image.convert("RGB"), Image.new("RGB", image.size, "white")).getbbox()
    assert main(["plot", "open", str(root), "--direct", "--json"]) == 0
    opened = json.loads(capsys.readouterr().out)
    assert opened["plot_type"] == "ManagedPlot"
    change = tmp_path / "change.json"
    change.write_text(json.dumps(patch(opened, "label-after-conversion", "axis.label", "Elapsed time (s)", "axis:x")))
    assert main(["plot", "patch", str(root), "--request", str(change), "--direct", "--json"]) == 0
    edited = json.loads(capsys.readouterr().out)
    assert edited["ready_to_use"] and edited["revision"] == 1
    assert edited["scientific_hash"] == converted["scientific_hash"]
    assert _tree(archive) == before


@pytest.mark.comprehensive
def test_legacy_conversion_refuses_unmapped_widget_before_allocating_copy(tmp_path, capsys):
    archive, native = _original(tmp_path)
    with native.open("a") as stream:
        stream.write("To('/page1/graph1')\nAdd('label', name='note')\n")
    before = _tree(archive)
    destination = tmp_path / "converted"
    assert main(["project", "legacy-convert", str(archive), "--out", str(destination), "--json"]) == 1
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["reason_code"] == "legacy_conversion_unsupported"
    assert "without other objects" in rejected["message"]
    assert not destination.exists()
    assert _tree(archive) == before


def test_legacy_unit_does_not_treat_sample_labels_as_scientific_units():
    from sciplot_core.plot_document import DocumentError
    from sciplot_core.studio_core.legacy_conversion import _axis_unit

    with pytest.raises(DocumentError) as error:
        _axis_unit("Voltage (V) (sample A)", None)
    assert error.value.reason_code == "legacy_conversion_unit_required"
    assert _axis_unit("Voltage (V) (sample A)", "V") == "V"
    with pytest.raises(DocumentError, match="does not unambiguously"):
        _axis_unit("Voltage (sample A)", None)
    assert _axis_unit("Voltage (V)", None) == "V"
    with pytest.raises(DocumentError, match="declares"):
        _axis_unit("Voltage (V)", "A")


@pytest.mark.comprehensive
def test_legacy_conversion_layout_rejection_leaves_no_partial_destination(tmp_path, capsys):
    archive, native = _original(tmp_path)
    with native.open("a") as stream:
        stream.write("To('/page1')\nSet('width', '10mm')\nSet('height', '10mm')\n")
    before = _tree(archive)
    output = tmp_path / "tiny"
    args = ["project", "legacy-convert", str(archive), "--out", str(output), "--json"]
    for _ in range(2):
        assert main(args) == 1
        assert json.loads(capsys.readouterr().out)["reason_code"] == "figure_layout_no_space"
        assert not output.exists()
        assert _tree(archive) == before


def test_pending_conversion_retries_exact_request_without_touching_unowned_files(tmp_path, monkeypatch):
    from sciplot_core.plot_document import DocumentError
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.studio_core import legacy_conversion

    archive, native = _original(tmp_path)
    saved = {"document_sha256": file_sha256(native), "coordinates": {"x": [0., 1., 2.], "y": [1., 3., 2.]},
             "axes": {"x": {"label": "Time (s)", "domain": [0., 3.], "ticks": [0., 1., 2., 3.]},
                      "y": {"label": "Signal (V)", "domain": [0., 4.], "ticks": [0., 2., 4.]}},
             "marks": [{"id": "mark:line", "type": "line", "style": {}}],
             "layout": {"width_mm": 150., "height_mm": 150.}}
    monkeypatch.setattr(legacy_conversion, "_inspect", lambda _: saved)
    calls = []

    def create(_, request):
        calls.append(request)
        if len(calls) == 1:
            raise OSError("lost native worker")
        return {"ready_to_use": False}

    monkeypatch.setattr(PlotService, "create", create)
    output = tmp_path / "pending"
    old = _tree(archive)
    with pytest.raises(OSError, match="lost native worker"):
        legacy_conversion.convert_legacy_plot(archive, output=output)
    note = output / "user-note.txt"
    note.write_text("not conversion-owned")
    assert legacy_conversion.convert_legacy_plot(archive, output=output)["status"] == "blocked"
    assert calls[0] == calls[1] and len(calls) == 2
    saved["axes"]["x"]["label"] = "Time (min)"
    with pytest.raises(DocumentError) as error:
        legacy_conversion.convert_legacy_plot(archive, output=output)
    assert error.value.reason_code == "legacy_conversion_retry_conflict"
    assert note.read_text() == "not conversion-owned"
    assert _tree(archive) == old
