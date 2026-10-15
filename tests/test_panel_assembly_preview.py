"""Current source previews are read-only and independent of export acceptance."""

import io
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pymupdf
import pytest

from sciplot_core.panel_assembly.errors import AssemblyError
from sciplot_core.panel_assembly.preview import render_preview
from sciplot_core.panel_assembly.sources import capture_source
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.veusz_runtime import veusz_worker_environment


def pixels(payload):
    with Image.open(io.BytesIO(payload)) as image:
        assert image.format == "PNG" and max(image.size) <= 800
        assert min(image.size) > 0
        return image.convert("RGB").copy()


def test_image_and_pdf_previews_are_bound_bounded_and_preserve_originals(tmp_path):
    path = tmp_path / "micrograph.tiff"
    Image.new("RGB", (1600, 1200), "blue").save(path)
    diagram = tmp_path / "diagram.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=1000)
        page.insert_text((40, 80), "Current diagram", fontsize=20)
        pdf.save(diagram)
    for original in (path, diagram):
        source = capture_source({"kind": "image", "path": str(original)})
        before = file_inventory(original)
        preview = pixels(render_preview(source))
        assert max(preview.size) == 800
        assert file_inventory(original) == before
    source = capture_source({"kind": "image", "path": str(path)})
    Image.new("RGB", (1600, 1200), "red").save(path)
    with pytest.raises(AssemblyError) as error:
        render_preview(source)
    assert error.value.code == "assembly_source_stale"


def test_preview_refuses_source_drift_during_render(tmp_path, monkeypatch):
    from sciplot_core.panel_assembly import preview

    path = tmp_path / "source.png"
    Image.new("RGB", (20, 20), "blue").save(path)
    source = capture_source({"kind": "image", "path": str(path)})

    def changed(_source):
        before = path.read_bytes()
        Image.new("RGB", (20, 20), "red").save(path)
        return before

    monkeypatch.setattr(preview, "_image_preview", changed)
    with pytest.raises(AssemblyError) as error:
        render_preview(source)
    assert error.value.code == "assembly_source_stale"


@pytest.mark.comprehensive
def test_legacy_preview_uses_current_native_not_adjacent_pdf_and_does_not_accept_export(tmp_path):
    from test_task_papers_native import _projects
    from test_panel_assembly_export import add
    from sciplot_core.panel_assembly.export import export_document
    from sciplot_core.panel_assembly.model import new_document
    from sciplot_core.studio_core.document_edit_state import run_document_worker
    from sciplot_core.studio_core.project_query import inspect_project

    raw, projects = _projects(tmp_path)
    for index, project in enumerate(projects):
        native = project / "studio/document.vsz"
        stale = native.with_suffix(".pdf")
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=100, height=100)
            page.draw_rect(page.rect, fill=(1, 0, 0))
            pdf.save(stale)
        source = capture_source({"kind": "project", "project": str(project),
                                 "figure_id": inspect_project(project)["primary_figure_id"]})
        before = {path: file_inventory(path) for path in [project, *raw]}
        rendered = pixels(render_preview(source))
        expected_path = tmp_path / f"direct-native-{index}.png"
        run_document_worker("preview-document", native, "--out", expected_path)
        expected = pixels(expected_path.read_bytes())
        assert rendered.size == expected.size
        assert rendered.tobytes() == expected.tobytes()
        assert min(rendered.getextrema()[0]) < 100  # Actual plot ink, not a blank placeholder.
        assert {path: file_inventory(path) for path in before} == before
        if index == 1:
            layout = add(new_document(rows=1, columns=1, width_mm=113, height_mm=98), source, name="ftir")
            with pytest.raises(AssemblyError) as error:
                export_document(layout, tmp_path / "still-not-accepted")
            assert error.value.code == "assembly_native_qa_failed"
            assert not (tmp_path / "still-not-accepted").exists()


@pytest.mark.comprehensive
def test_managed_preview_compiles_current_semantics_without_native_save_or_qa_claim(tmp_path):
    from test_panel_assembly_export import managed_source
    from sciplot_core.plot_engine.managed_state import make_binding
    from sciplot_core.plot_engine.storage import commit, load_head
    from sciplot_core.plot_ir.figure_document import figure_spec, store_spec

    root, _source = managed_source(tmp_path)
    head = load_head(root)
    spec = figure_spec(head["document"])
    # A current semantic annotation can be visually clipped. Source preview
    # must display it without turning that display into export acceptance.
    spec["annotations"] = [{"id": "annotation:long", "space": "view", "view_id": "view:A",
                             "x": .5, "y": .5, "text": "W" * 100, "visible": True, "style": {}}]
    document = store_spec(head["document"], spec)
    document["revision"] += 1
    binding = make_binding(root, document, output=tmp_path / "managed-output")
    commit(root, document, binding, "source-preview-control")
    source = capture_source({"kind": "managed", "project": str(root), "plot_id": document["plot_id"]})
    before = {path: file_inventory(path) for path in (root, tmp_path / "figure.csv")}
    rendered = pixels(render_preview(source))
    assert min(rendered.getextrema()[0]) < 100
    assert not Path(binding["document"]).exists()
    assert {path: file_inventory(path) for path in before} == before

    request, output = tmp_path / "preview-source.json", tmp_path / "read-only-preview.png"
    request.write_text(json.dumps(source))
    process = subprocess.run([sys.executable, "-m", "sciplot_core.panel_assembly.preview", str(request), str(output)],
                             env=veusz_worker_environment(), capture_output=True, text=True, timeout=120)
    assert process.returncode == 0, process.stderr
    evidence = json.loads(process.stdout)
    assert evidence["authority"] == "managed_document"
    assert evidence["is_export_acceptance"] is False
    assert evidence["target_export_readiness"] == "not_evaluated"
    assert {path: file_inventory(path) for path in before} == before
