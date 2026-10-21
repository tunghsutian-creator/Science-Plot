import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core.plot_document import DocumentError
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head, transaction_path
from sciplot_core._paths import REPO_ROOT
from sciplot_core.studio_core.document_edit import apply_document_edit, preview_document_edit
from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.studio_core.annotation_operations import preview_document_operations


@pytest.mark.comprehensive
def test_native_pattern_patch_keeps_science_and_saved_native_state(tmp_path):
    source = tmp_path / "spectra.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
                      "E2,E2,E4,E4\n400,1,400,2\n450,2,450,3\n500,3,500,4\n")
    raw = source.read_bytes()
    created = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "studio", str(source),
        "--rule", "uvvis_spectrum", "--export", "pdf,tiff_300", "--json"],
        capture_output=True, text=True, timeout=180, cwd=REPO_ROOT)
    assert created.returncode == 0, created.stdout + created.stderr
    project = Path(json.loads(created.stdout)["project_dir"])
    selected = inspect_project(project, native=True)["selected_figure"]
    seeded = preview_document_operations(project, [{"op": "add_annotation", "id": "opaque_note",
        "parent_path": "/page1/graph1", "text": "Saved native note", "position": {
        "mode": "relative", "x": 0.05, "y": 0.95}}], output_dir=tmp_path / "seed",
        expected_document_sha256=selected["document_sha256"])
    apply_document_edit(project, seeded)
    service = PlotService()
    try:
        opened = service.open(project)
        root = Path(opened["plot"])
        before = load_head(root)
        assert opened["plot_type"] == "LegacyPlot" and opened["coverage"]["mode"] == "legacy_shadow"
        series = [key for key, obj in opened["objects"].items() if obj["kind"] == "series"]
        assert len(series) == 2
        native = Path(before["binding"]["document"])
        spec = Path(before["binding"]["spec"])
        spec_before = spec.read_bytes()
        request = {"plot_id": opened["plot_id"], "base_revision": 0, "idempotency_key": "pattern-native",
            "intent_class": "presentation", "changes": [{"op": "set", "target": [series[1]],
            "property": "style.line.pattern", "value": "dashed"}]}
        result = service.patch(root, request)
        assert result["status"] == "complete", result
        assert result["scientific_hash_changed"] is False and result["presentation_hash_changed"] is True
        after = load_head(root)
        assert before["document"]["scientific_hash"] == after["document"]["scientific_hash"]
        assert spec.read_bytes() == spec_before
        assert "Saved native note" in native.read_text()
        assert source.read_bytes() == raw
        tx = json.loads(transaction_path(root, "pattern-native").read_text())
        assert tx["review"]["scientific_audit"]["status"] == "passed"
        assert tx["export"]["studio_run"]["qa"]["publication"]["status"] == "passed"
        saved = native.read_bytes()
        repeat = service.patch(root, request)
        assert repeat["revision"] == 1 and native.read_bytes() == saved
        for key, prop, value in [("bad-pattern", "style.line.pattern", "none"),
                                ("data-edit", "mapping.x", [8])]:
            invalid = {**request, "base_revision": 1, "idempotency_key": key,
                       "changes": [{"op": "set", "target": [series[1]], "property": prop, "value": value}]}
            with pytest.raises(DocumentError):
                service.patch(root, invalid)
            assert native.read_bytes() == saved and not transaction_path(root, key).exists()
        stale = {**request, "idempotency_key": "stale-revision"}
        with pytest.raises(DocumentError) as caught:
            service.patch(root, stale)
        assert caught.value.reason_code == "document_revision_conflict"
        assert native.read_bytes() == saved
        legend = next(key for key, obj in opened["objects"].items() if obj["kind"] == "legend")
        length = opened["objects"][legend]["properties"]["legend.sample_length"]
        binding = after["binding"]["targets"][legend]
        change = {"object_path": binding["object_path"],
                  "setting_path": binding["properties"]["legend.sample_length"]["setting_path"],
                  "expected_value": length, "value": "100cm"}
        # Actual native overflow, not a mocked metadata maximum. Candidate
        # validation runs before saving or publishing the unchanged source/head.
        with pytest.raises(ValueError, match="fit inside"):
            preview_document_edit(project, [change], output_dir=tmp_path / "overflow",
                                  expected_document_sha256=file_sha256(native))
        assert native.read_bytes() == saved and load_head(root) == after
        assert not list((tmp_path / "overflow").rglob("document.vsz"))
        longer = {**request, "base_revision": 1, "idempotency_key": "legend-length",
                  "changes": [{"op": "set", "target": [legend],
                               "property": "legend.sample_length", "value": "6mm"}]}
        length_result = service.patch(root, longer)
        assert length_result["status"] == "complete", length_result
        changed = load_head(root)
        assert changed["document"]["scientific_hash"] == before["document"]["scientific_hash"]
        assert spec.read_bytes() == spec_before and source.read_bytes() == raw
        updated_native = native.read_bytes()
        assert service.patch(root, longer)["revision"] == 2 and native.read_bytes() == updated_native
        with pytest.raises(ValueError, match="no longer has its expected value"):
            preview_document_edit(project, [{**change, "value": "5mm"}], output_dir=tmp_path / "stale-length",
                                  expected_document_sha256=file_sha256(native))
        assert native.read_bytes() == updated_native and load_head(root) == changed
        restored = service.rollback(root, {"base_revision": 2, "target_revision": 1,
                                           "idempotency_key": "restore-legend-length"})
        assert restored["status"] == "complete", restored
        rollback_head = load_head(root)
        assert rollback_head["document"]["presentation"]["objects"] == after["document"]["presentation"]["objects"]
        assert rollback_head["document"]["scientific_hash"] == before["document"]["scientific_hash"]
        assert spec.read_bytes() == spec_before and "Saved native note" in native.read_text()
    finally:
        service.close()
