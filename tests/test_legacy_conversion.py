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
