"""Real native adapter acceptance: import, semantic delta, publication and undo."""

import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_backends import VeuszBackend
from sciplot_core.plot_document import DocumentError, apply_patch
from sciplot_core.studio_core.annotation_operations import preview_document_operations
from sciplot_core.studio_core.document_edit import apply_document_edit
from sciplot_core.studio_core.project_query import inspect_project


@pytest.mark.comprehensive
def test_native_saved_style_title_hide_export_replay_and_restore(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
                      "E2,E2,E4,E4\n400,1,400,2\n450,2,450,3\n500,3,500,4\n")
    original_source = source.read_bytes()
    created = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "studio", str(source),
                              "--rule", "uvvis_spectrum", "--export", "pdf,tiff_300", "--json"],
                             capture_output=True, text=True, timeout=180, cwd=REPO_ROOT)
    assert created.returncode == 0, created.stdout + created.stderr
    project = Path(json.loads(created.stdout)["project_dir"])
    current = inspect_project(project, native=True)["selected_figure"]
    initial = [{"op": "add_annotation", "id": "spectrum_title", "parent_path": "/page1/graph1",
                "text": "Measured spectra", "position": {"mode": "relative", "x": 0.05, "y": 0.96}},
               {"op": "set_sample_style", "samples": ["E2", "E4"], "style": {"width": "0.9pt"}}]
    review = preview_document_operations(project, initial, output_dir=tmp_path / "initial",
                                         expected_document_sha256=current["document_sha256"])
    apply_document_edit(project, review)
    backend = VeuszBackend()
    document, binding = backend.import_project(project, plot_id="native_acceptance")
    objects = document["presentation"]["objects"]
    assert objects["series:E2"]["properties"]["style.line.width"] == "0.9pt"
    assert objects["series:E4"]["properties"]["style.line.width"] == "0.9pt"
    assert document["scientific"]["guards"]["source_status_at_import"] == "current"
    native = Path(binding["document"])
    original_native = native.read_bytes()
    request = {"plot_id": document["plot_id"], "base_revision": 0, "idempotency_key": "style-and-title",
               "intent_class": "presentation", "changes": [
                   {"op": "set", "target": ["series:E2", "series:E4"], "property": "style.line.width", "value": "0.7pt"},
                   {"op": "set", "target": ["title:spectrum_title"], "property": "title.visible", "value": False}]}
    changed, diff, risk = apply_patch(document, request)
    assert risk == "presentation" and changed["scientific_hash"] == document["scientific_hash"]
    review = backend.preview(document, binding, changed, diff, tmp_path / "candidate")
    assert review["scientific_audit"]["status"] == "passed"
    assert native.read_bytes() == original_native
    applied = backend.apply(binding, review)
    assert backend.apply(binding, review)["status"] == "already_applied"
    binding = backend.refresh_binding(binding, applied)
    # Serializing and using a fresh adapter simulates a cold application restart.
    binding = json.loads(json.dumps(binding))
    backend = VeuszBackend()
    exported = backend.export(binding)
    assert exported["ready_to_use"] is True
    assert len(exported["evidence_files"]) > 5
    assert all(file_sha256(Path(path)) == digest for path, digest in exported["evidence_files"].items())
    saved = inspect_project(project, native=True, include_annotations=True)["selected_figure"]
    assert saved["annotations"] == []
    for number in (1, 2):
        assert saved["objects"][f"/page1/graph1/series_{number}"]["settings"]["PlotLine/width"] == "0.7pt"
    restore = {**request, "idempotency_key": "restore", "changes": [
        {"op": "set", "target": ["series:E2", "series:E4"], "property": "style.line.width", "value": "0.9pt"},
        {"op": "set", "target": ["title:spectrum_title"], "property": "title.visible", "value": True}]}
    restored, difference, _ = apply_patch(changed, restore)
    review = backend.preview(changed, binding, restored, difference, tmp_path / "restore")
    binding = backend.refresh_binding(binding, backend.apply(binding, review))
    assert inspect_project(project, native=True, include_annotations=True)["selected_figure"]["annotations"][0]["text"] == "Measured spectra"
    assert source.read_bytes() == original_source
    native.write_bytes(native.read_bytes() + b"\n")
    with pytest.raises(DocumentError, match="changed"):
        backend.render(binding, tmp_path / "stale")
    assert not (tmp_path / "stale").exists()
