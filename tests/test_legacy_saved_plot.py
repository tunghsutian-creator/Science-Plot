"""A legacy plot can be viewed and redrawn without admitting a writable project."""
import json
from pathlib import Path

import pytest

from sciplot_core.cli import main
from sciplot_core.foundation.file_hashing import file_sha256

_SAVED_VSZ = """SetData('x', [0., 1., 2.])
SetData('y', [1., 3., 2.])
Add('page', name='page1', autoadd=False)
To('page1')
Add('graph', name='graph1', autoadd=False)
To('graph1')
Add('axis', name='x', autoadd=False)
Add('axis', name='y', autoadd=False)
To('y')
Set('direction', 'vertical')
To('..')
Add('xy', name='curve', autoadd=False)
To('curve')
Set('xData', 'x')
Set('yData', 'y')
"""


def _old_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "archive"
    studio = project / "studio"
    studio.mkdir(parents=True)
    (project / "plot_request.json").write_text("{}")
    (project / "keep.txt").write_text("old scientific notes")
    (studio / "spec.json").write_text("{}")
    native = studio / "document.vsz"
    native.write_text(_SAVED_VSZ)
    return project, native


def _tree(root: Path) -> dict[str, tuple[int, int, bytes | None]]:
    return {str(path.relative_to(root)): (path.stat().st_mode, path.stat().st_mtime_ns,
            path.read_bytes() if path.is_file() else None) for path in (root, *root.rglob("*"))}


@pytest.mark.comprehensive
def test_legacy_open_and_redraw_read_exact_saved_vsz_without_writing_project(tmp_path, capsys):
    from PIL import Image, ImageChops
    from sciplot_core.veusz_worker.operations import export_document

    project, native = _old_project(tmp_path)
    expected = export_document(native, formats=["png_300"], output_dir=tmp_path / "before")
    old_tree = _tree(project)
    assert main(["project", "legacy-open", str(project), "--json"]) == 0
    opened = json.loads(capsys.readouterr().out)
    assert opened["read_only"] and opened["new_features_require_conversion"]
    assert opened["document"] == {"path": str(native), "sha256": file_sha256(native)}
    assert opened["pages"] == ["page1"]
    assert _tree(project) == old_tree

    output = tmp_path / "redrawn"
    assert main(["project", "legacy-redraw", str(project), "--out", str(output),
                 "--formats", "pdf,png_300", "--json"]) == 0
    redrawn = json.loads(capsys.readouterr().out)
    assert redrawn["document_sha256"] == opened["document"]["sha256"]
    exports = {record["format"]: record for record in redrawn["exports"]}
    assert set(exports) == {"pdf", "png_300"}
    for record in exports.values():
        assert Path(record["path"]).is_relative_to(output)
        assert file_sha256(Path(record["path"])) == record["sha256"]
    with Image.open(expected["exports"][0]["path"]) as original, Image.open(exports["png_300"]["path"]) as actual:
        assert original.size == actual.size
        assert ImageChops.difference(original.convert("RGB"), actual.convert("RGB")).getbbox() is None
    assert _tree(project) == old_tree


def test_exact_legacy_vsz_rejects_output_inside_original_project(tmp_path, capsys):
    project, native = _old_project(tmp_path)
    old_tree = _tree(project)
    assert main(["project", "legacy-redraw", str(native), "--out", str(project / "export"), "--json"]) == 1
    assert "outside the original project" in capsys.readouterr().out
    assert _tree(project) == old_tree
