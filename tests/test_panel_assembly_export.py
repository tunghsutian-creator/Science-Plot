"""Frozen source authority, physical image composition and publication failure guards."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image
import pymupdf
import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.panel_assembly.errors import AssemblyError
from sciplot_core.panel_assembly.export import export_document
from sciplot_core.panel_assembly.model import apply_operations, new_document, resolve_document
from sciplot_core.panel_assembly.sources import assert_source_current, capture_source
from sciplot_core.veusz_runtime import veusz_worker_environment


def add(document, source, *, name="image", row=0, column=0, crop=None):
    return apply_operations(document, [{"op": "add_panel", "panel": {"id": name, "source": source,
        "row": row, "column": column, "row_span": 1, "column_span": 1, "label": None, "crop": crop}}])


def image_source(tmp_path, *, name="source.png"):
    path = tmp_path / name
    image = Image.new("RGB", (200, 100), "red")
    for x in range(100, 200):
        for y in range(100):
            image.putpixel((x, y), (0, 0, 255))
    image.save(path)
    return path, capture_source({"kind": "image", "path": str(path)})


def managed_source(tmp_path):
    from test_figure_document import request_for_figure
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata
    from sciplot_core.plot_engine.managed_state import make_binding
    from sciplot_core.plot_engine.storage import commit

    request = request_for_figure(tmp_path)
    root = tmp_path / "managed"
    document = create_managed_document(request["template_definition"], request["data_binding"], plot_id="assembly-managed")
    document = resolved_metadata(document, rule_id=request["rule_id"], executors={})
    document, _ = resolve_science(root, document)
    binding = make_binding(root, document, output=tmp_path / "managed-output")
    commit(root, document, binding, "assembly-test")
    return root, capture_source({"kind": "managed", "project": str(root), "plot_id": document["plot_id"]})


@pytest.mark.parametrize("suffix", ["png", "jpg", "tiff"])
def test_image_capture_closes_bytes_and_replacement_identity(tmp_path, suffix):
    path, source = image_source(tmp_path, name="source." + suffix)
    assert source["binding"]["width"] == 200
    assert source["binding"]["height"] == 100
    assert_source_current(source)
    replacement = path.with_name("replacement." + suffix)
    replacement.write_bytes(path.read_bytes())
    replacement.replace(path)
    with pytest.raises(AssemblyError, match="stale") as error:
        assert_source_current(source)
    assert error.value.code == "assembly_source_stale"


def test_vector_pdf_diagram_is_supported_and_multipage_is_refused(tmp_path):
    path = tmp_path / "diagram.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=100, height=100)
        page.insert_text((10, 20), "Vector diagram")
        pdf.save(path)
    source = capture_source({"kind": "image", "path": str(path)})
    assert source["binding"]["media_type"] == "application/pdf"
    document = add(new_document(rows=1, columns=1), source, crop=[0, 0, .8, .8])
    output = export_document(document, tmp_path / "vector")
    with pymupdf.open(output["pdf"]) as pdf:
        assert "Vector diagram" in pdf[0].get_text()
    with pymupdf.open(path) as pdf:
        pdf.new_page()
        pdf.save(tmp_path / "multiple.pdf")
    with pytest.raises(AssemblyError, match="one unencrypted page"):
        capture_source({"kind": "image", "path": str(tmp_path / "multiple.pdf")})


def test_image_crop_deterministic_pdf_tiff_physical_size_and_source_bytes(tmp_path):
    path, source = image_source(tmp_path)
    original = path.read_bytes()
    document = add(new_document(rows=1, columns=1, width_mm=60, height_mm=45), source,
                   crop=[.5, 0, 1, 1])
    first = export_document(document, tmp_path / "first", dpi=300)
    second = export_document(document, tmp_path / "second", dpi=300)
    assert file_sha256(Path(first["pdf"])) == file_sha256(Path(second["pdf"]))
    assert file_sha256(Path(first["tiff"])) == file_sha256(Path(second["tiff"]))
    assert path.read_bytes() == original
    assert json.loads(Path(first["layout"]).read_text()) == document
    with pymupdf.open(first["pdf"]) as pdf:
        assert pdf[0].rect.width * 25.4 / 72 == pytest.approx(60, abs=.001)
        assert pdf[0].rect.height * 25.4 / 72 == pytest.approx(45, abs=.001)
    with Image.open(first["tiff"]) as tiff:
        assert tiff.info["dpi"] == (300., 300.)
        assert tiff.getpixel((tiff.width // 2, tiff.height // 2)) == (0, 0, 255)
    assert first["source_currentness"] == "passed"
    assert first["panels"][0]["evidence"]["resampling_of_source"] is False
    assert (tmp_path / "first/panels/001/sources/index.json").is_file()


def test_house_panel_label_uses_seven_point_bold_and_measured_reserved_band(tmp_path):
    _path, source = image_source(tmp_path)
    document = add(new_document(rows=1, columns=1, width_mm=60, height_mm=45), source)
    output = export_document(document, tmp_path / "house-label")
    with pymupdf.open(output["pdf"]) as pdf:
        spans = [span for block in pdf[0].get_text("dict")["blocks"] if "lines" in block
                 for line in block["lines"] for span in line["spans"]]
    assert len(spans) == 1 and spans[0]["text"] == "a"
    assert spans[0]["size"] == 7.0
    assert spans[0]["font"] == "Helvetica-Bold"
    label = output["panels"][0]["evidence"]["panel_label"]
    assert label["font_weight"] == "bold" and label["requested_font_family"] == "Arial"
    assert label["bounds_mm"][1] >= label["allowed_band_mm"][1]
    assert label["bounds_mm"][1] + label["bounds_mm"][3] < output["panels"][0]["content_mm"][1]


def test_empty_panel_label_is_hidden_and_long_or_unicode_label_refuses_export(tmp_path):
    _path, source = image_source(tmp_path)
    document = add(new_document(rows=1, columns=1, width_mm=18, height_mm=45), source)
    hidden = apply_operations(document, [{"op": "set_label", "id": "image", "label": ""}])
    output = export_document(hidden, tmp_path / "hidden-label")
    with pymupdf.open(output["pdf"]) as pdf:
        assert not pdf[0].get_text().strip()
    assert not output["panels"][0]["evidence"]["panel_label"]["visible"]
    long = apply_operations(document, [{"op": "set_label", "id": "image", "label": "W" * 16}])
    with pytest.raises(AssemblyError) as error:
        export_document(long, tmp_path / "long-label")
    assert error.value.code == "assembly_label_clipping"
    from sciplot_core.panel_assembly.export import _label

    with pymupdf.open() as pdf:
        page = pdf.new_page()
        with pytest.raises(AssemblyError) as error:
            _label(page, "Ω", [1, 3], [0, 0, 60, 45], [2, 8, 56, 35])
    assert error.value.code == "assembly_label_unsupported"


def test_stale_source_and_existing_output_fail_without_publication(tmp_path):
    path, source = image_source(tmp_path)
    document = add(new_document(), source)
    old = tmp_path / "previous"
    old.mkdir()
    marker = old / "keep.txt"
    marker.write_text("previous package")
    with pytest.raises(AssemblyError) as error:
        export_document(document, old)
    assert error.value.code == "assembly_output_exists"
    assert marker.read_text() == "previous package"
    path.write_bytes(b"changed")
    with pytest.raises(AssemblyError) as error:
        export_document(document, tmp_path / "must-not-exist")
    assert error.value.code == "assembly_source_stale"
    assert not (tmp_path / "must-not-exist").exists()


def test_failure_after_staging_cannot_publish_or_destroy_previous_package(tmp_path, monkeypatch):
    _path, source = image_source(tmp_path)
    document = add(new_document(), source)
    from sciplot_core.panel_assembly import export as owner

    original = owner._source_package

    def failure(*args):
        original(*args)
        raise RuntimeError("injected package assembly failure")

    monkeypatch.setattr(owner, "_source_package", failure)
    with pytest.raises(AssemblyError, match="injected"):
        export_document(document, tmp_path / "failed")
    assert not (tmp_path / "failed").exists()
    assert not list(tmp_path.glob(".failed.assembly-*"))


def test_atomic_install_race_preserves_newly_occupied_output(tmp_path, monkeypatch):
    _path, source = image_source(tmp_path)
    document = add(new_document(), source)
    from sciplot_core.panel_assembly import export as owner

    install = owner.install_new_delivery

    def race(candidate, destination):
        destination.mkdir()
        (destination / "occupied.txt").write_text("concurrent output")
        install(candidate, destination)

    monkeypatch.setattr(owner, "install_new_delivery", race)
    with pytest.raises(AssemblyError):
        export_document(document, tmp_path / "occupied")
    assert (tmp_path / "occupied/occupied.txt").read_text() == "concurrent output"
    assert not (tmp_path / "occupied/assembly.pdf").exists()


def test_source_drift_between_image_composition_and_packaging_is_refused(tmp_path, monkeypatch):
    path, source = image_source(tmp_path)
    document = add(new_document(), source)
    from sciplot_core.panel_assembly import export as owner

    package = owner._source_package

    def drift(source, folder):
        Image.new("RGB", (200, 100), "green").save(path)
        return package(source, folder)

    monkeypatch.setattr(owner, "_source_package", drift)
    with pytest.raises(AssemblyError) as error:
        export_document(document, tmp_path / "drifted")
    assert error.value.code == "assembly_source_stale"
    assert not (tmp_path / "drifted").exists()


def test_scientific_pdf_size_mismatch_is_never_scaled_to_fit(tmp_path):
    from sciplot_core.panel_assembly.export import _place_scientific

    native = tmp_path / "unexpected.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=100, height=100)
        pdf.save(native)
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        with pytest.raises(AssemblyError) as error:
            _place_scientific(page, native, [0, 0, 80, 80], [0, 0, 84, 84])
    assert error.value.code == "assembly_native_size_invalid"


def test_managed_source_semantic_inputs_head_and_external_native_drift(tmp_path):
    root, source = managed_source(tmp_path)
    assert_source_current(source)
    from sciplot_core.plot_engine.storage import load_head

    native = Path(load_head(root)["binding"]["document"])
    native.parent.mkdir(parents=True)
    native.write_text("externally changed cache")
    with pytest.raises(AssemblyError) as error:
        assert_source_current(source)
    assert error.value.code == "assembly_source_stale"
    native.unlink()
    assert_source_current(source)  # Disposable absence does not replace science authority.
    raw = tmp_path / "figure.csv"
    raw.write_text(raw.read_text().replace("5,5", "5,7"))
    with pytest.raises(AssemblyError):
        assert_source_current(source)


def test_forged_source_kind_binding_and_empty_assembly_fail_closed(tmp_path):
    _path, source = image_source(tmp_path)
    forged = deepcopy(source)
    forged["binding"]["media_type"] = "image/jpeg"
    with pytest.raises(AssemblyError):
        assert_source_current(forged)
    with pytest.raises(AssemblyError):
        capture_source({"kind": "image", "path": str(tmp_path / "source.png"), "binding": {}})
    with pytest.raises(AssemblyError) as error:
        export_document(new_document(), tmp_path / "empty")
    assert error.value.code == "assembly_empty"
    assert not (tmp_path / "empty").exists()


@pytest.mark.comprehensive
def test_native_legacy_mixed_export_preserves_state_science_and_portable_sources(tmp_path):
    from sciplot_core.task_control import start_task
    from sciplot_core.studio_core.project_query import inspect_project
    from sciplot_core.studio_core.document_edit_state import run_document_worker

    raw = tmp_path / "UVvis.csv"
    raw.write_text("Wavelength,Absorbance\nnm,a.u.\nE3,E3\n400,1\n425,2\n450,4\n475,2\n500,1\n")
    created = start_task({"version": 1, "action": "create", "source": str(raw)}, task_dir=tmp_path / "create",
                         defer_creation_export=True)
    assert created["status"] == "complete", created
    project = Path(created["project"])
    native = project / "studio/document.vsz"
    spec = json.loads((project / "studio/spec.json").read_text())
    series = spec["series"][0]
    linked = tmp_path / "native-linked.txt"
    linked.write_text("".join(f"{x:.17g} {y:.17g}\n" for x, y in zip(series["x_values"], series["y_values"], strict=True)))
    script = tmp_path / "manual-save.py"
    script.write_text("from pathlib import Path\nfrom sciplot_core.veusz_worker.document_edit import loaded_native_document\n"
        "from sciplot_core.studio_core.persistence import atomic_save_veusz_document\n"
        f"path=Path({str(native)!r})\nwith loaded_native_document(path) as doc:\n"
        " from veusz.document import CommandInterface\n"
        f" CommandInterface(doc).ImportFile({str(linked)!r},{(series['x_name'] + '(numeric), ' + series['y_name'] + '(numeric)')!r},linked=True)\n"
        " doc.resolveSettingPath(None,'/page1/graph1/series_1/PlotLine/color').set('#A34455')\n"
        " atomic_save_veusz_document(doc,path)\n")
    saved = subprocess.run([sys.executable, str(script)], env=veusz_worker_environment(), capture_output=True, text=True, timeout=120)
    assert saved.returncode == 0, saved.stderr
    native_bytes = native.read_bytes()
    selection = capture_source({"kind": "project", "project": str(project),
                                "figure_id": inspect_project(project)["primary_figure_id"]})
    _path, image = image_source(tmp_path)
    document = add(new_document(rows=1, columns=2, width_mm=180, height_mm=85), selection, name="science")
    document = add(document, image, column=1, crop=[.5, 0, 1, 1])
    output = export_document(document, tmp_path / "mixed")
    repeated = export_document(document, tmp_path / "mixed-repeated")
    assert file_sha256(Path(output["pdf"])) == file_sha256(Path(repeated["pdf"]))
    assert file_sha256(Path(output["tiff"])) == file_sha256(Path(repeated["tiff"]))
    scientific = output["panels"][0]["evidence"]
    assert scientific["physical_size"]["scale"] == 1
    assert scientific["physical_size"]["actual_page_within_content"]
    assert all(0 <= value < 25.4 / 72 for value in scientific["physical_size"]["rounding_slack_mm"])
    assert scientific["publication_qa"]["native_text_checked"]
    assert scientific["publication_qa"]["status"] == "passed"
    assert scientific["portable_original"]["imports"]
    assert scientific["portable_reflowed"]["portable_sha256"] == file_sha256(tmp_path / "mixed/panels/001/native/reflowed/document.vsz")
    assert native.read_bytes() == native_bytes
    assert raw.read_text().startswith("Wavelength")
    exported = tmp_path / "mixed/panels/001/native"
    original = run_document_worker("inspect-document-state", exported / "original/document.vsz")
    reflowed = run_document_worker("inspect-document-state", exported / "reflowed/document.vsz")
    original_audit = run_document_worker("audit-spec-data", exported / "original/document.vsz",
                                         exported / "source.spec.json", "--allow-presentation-edits")
    reflowed_audit = run_document_worker("audit-spec-data", exported / "reflowed/document.vsz",
                                         exported / "source.spec.json", "--allow-presentation-edits")
    assert original_audit["units"] == reflowed_audit["units"]
    for path, before in original["widgets"].items():
        if before["type"] not in {"document", "page"}:
            assert before == reflowed["widgets"][path]
    with pymupdf.open(output["pdf"]) as pdf:
        assert "Wavelength" in pdf[0].get_text()
    assert reflowed["widgets"]["/page1/graph1/series_1"]["settings"]["PlotLine/color"] == "#A34455"
    relocated = tmp_path / "relocated"
    shutil.copytree(tmp_path / "mixed", relocated)
    linked.rename(linked.with_suffix(".hidden"))
    (tmp_path / "mixed").rename(tmp_path / "held-original-package")
    try:
        reexport = run_document_worker("export-document", relocated / "panels/001/native/reflowed/document.vsz",
                                        "--out", relocated / "reexported")
        assert len(reexport["exports"]) == 2
    finally:
        linked.with_suffix(".hidden").rename(linked)
        (tmp_path / "held-original-package").rename(tmp_path / "mixed")
    assert_source_current(selection)
    replacement = native.with_suffix(".replacement")
    replacement.write_bytes(native_bytes)
    replacement.replace(native)
    with pytest.raises(AssemblyError) as error:
        assert_source_current(selection)
    assert error.value.code == "assembly_source_stale"


@pytest.mark.comprehensive
def test_native_managed_reflows_canonical_document_without_source_artifacts(tmp_path):
    root, source = managed_source(tmp_path)
    from sciplot_core.plot_engine.storage import load_head

    before = deepcopy(load_head(root))
    document = add(new_document(rows=1, columns=1, width_mm=105, height_mm=90), source, name="managed")
    output = export_document(document, tmp_path / "managed-package")
    evidence = output["panels"][0]["evidence"]
    assert evidence["authority"] == "managed_document"
    assert evidence["scientific_hash"] == before["document"]["scientific_hash"]
    assert evidence["publication_qa"]["status"] == "passed"
    assert evidence["source_ir_hash"] != evidence["reflowed_ir_hash"]
    assert load_head(root) == before
    assert not Path(before["binding"]["document"]).exists()
    native = tmp_path / "managed-package/panels/001/native"
    original = json.loads((native / "canonical-document.json").read_text())
    reflowed = json.loads((native / "reflowed-document.json").read_text())
    assert original["scientific"] == reflowed["scientific"]
    assert (native / "original/document.vsz").exists()
    assert (native / "reflowed/document.vsz").exists()


@pytest.mark.comprehensive
def test_native_target_size_clipping_refuses_export(tmp_path):
    _root, source = managed_source(tmp_path)
    document = add(new_document(rows=1, columns=1, width_mm=25, height_mm=25), source, name="too-small")
    assert resolve_document(document)["panels"][0]["content_mm"][2] < 25
    with pytest.raises(AssemblyError) as error:
        export_document(document, tmp_path / "rejected")
    assert error.value.code == "assembly_native_export_failed"
    assert not (tmp_path / "rejected").exists()


@pytest.mark.comprehensive
def test_native_measured_data_label_clipping_blocks_legacy_panel(tmp_path):
    from test_task_papers_native import _projects
    from sciplot_core.studio_core.project_query import inspect_project

    raw, projects = _projects(tmp_path)
    project = projects[1]
    source = capture_source({"kind": "project", "project": str(project),
                             "figure_id": inspect_project(project)["primary_figure_id"]})
    protected = [*raw, project / "studio/document.vsz", project / "studio/spec.json"]
    before = {path: file_sha256(path) for path in protected}
    # The existing FTIR label is anchored at its actual endpoint, aligned top.
    # At this bounded height its measured glyph extends below the plot frame.
    document = add(new_document(rows=1, columns=1, width_mm=113, height_mm=98), source, name="ftir")
    with pytest.raises(AssemblyError) as error:
        export_document(document, tmp_path / "clipped-label")
    assert error.value.code == "assembly_native_qa_failed"
    assert "annotation_outside_view" in str(error.value)
    assert not (tmp_path / "clipped-label").exists()
    assert {path: file_sha256(path) for path in protected} == before
