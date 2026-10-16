"""Existing publication bytes are prerequisites, never a reason to re-export."""

import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_paper_publication import capture_publication, assert_publication_current


@pytest.fixture
def publication(tmp_path):
    project = tmp_path / "project"
    studio = project / "studio"
    run = project / "runs/studio_1"
    (run / "studio").mkdir(parents=True)
    studio.mkdir()
    request = {"input": str(tmp_path / "raw.csv")}
    for path, value in ((project / "plot_request.json", request), (run / "request_snapshot.json", request)):
        path.write_text(json.dumps(value))
    for folder in (studio, run / "studio"):
        (folder / "document.vsz").write_bytes(b"sealed native fixture; not a scientific acceptance")
        (folder / "spec.json").write_text(json.dumps({"series": []}))
    exports, qa = [], {"status": "passed", "pdfs": [], "tiffs": []}
    for fmt, suffix, key in (("pdf", ".pdf", "pdfs"), ("tiff_300", ".tiff", "tiffs")):
        path = run / ("figure" + suffix)
        path.write_bytes(b"audited fixture " + fmt.encode())
        record = {"path": str(path), "sha256": file_sha256(path)}
        exports.append({**record, "format": fmt, "document": str(run / "studio/document.vsz")})
        qa[key].append(record)
    manifest = {"request": request, "qa": qa, "result": {"exports": exports},
                "veusz_document_hashes": {str(run / "studio/document.vsz"): file_sha256(studio / "document.vsz")}}
    (run / "manifest.json").write_text(json.dumps(manifest))
    selected = {"project": str(project), "figure_id": "primary", "document": str(studio / "document.vsz"),
                "version": {"document_sha256": file_sha256(studio / "document.vsz")}}
    return selected, run


def test_capture_sealed_export_identity_and_full_original_inventory(publication):
    selected, run = publication
    before = {str(path): path.read_bytes() for path in run.rglob("*") if path.is_file()}
    captured = capture_publication(selected)
    assert [record["format"] for record in captured["exports"]] == ["pdf", "tiff_300"]
    assert captured["qa"]["scope"] == "existing_current_sealed_publication"
    assert_publication_current(captured, selected)
    assert before == {str(path): path.read_bytes() for path in run.rglob("*") if path.is_file()}


@pytest.mark.parametrize("change", ["missing_pdf", "edited_pdf", "native", "spec", "request", "qa_failed", "new_file"])
def test_unsealed_or_drifted_publication_blocks_without_repair(publication, change):
    selected, run = publication
    captured = capture_publication(selected)
    if change == "missing_pdf":
        (run / "figure.pdf").unlink()
    elif change == "edited_pdf":
        (run / "figure.pdf").write_bytes(b"external edited publication")
    elif change in {"native", "spec"}:
        (Path(selected["project"]) / "studio" / ("document.vsz" if change == "native" else "spec.json")).write_bytes(b"user changed original")
    elif change == "request":
        (Path(selected["project"]) / "plot_request.json").write_text(json.dumps({"revision": 2}))
    elif change == "qa_failed":
        path = run / "manifest.json"
        value = json.loads(path.read_text())
        value["qa"]["status"] = "failed"
        path.write_text(json.dumps(value))
    else:
        (run / "unrecorded.txt").write_bytes(b"preserve this file")
    before = {str(path): path.read_bytes() for path in Path(selected["project"]).rglob("*") if path.is_file()}
    with pytest.raises(TaskControlError):
        assert_publication_current(captured, selected)
    assert before == {str(path): path.read_bytes() for path in Path(selected["project"]).rglob("*") if path.is_file()}
