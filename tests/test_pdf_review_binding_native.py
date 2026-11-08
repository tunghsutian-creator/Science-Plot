"""One real current-export -> annotated reference -> typed edit native chain."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import pymupdf
import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.visual_review.pdf_review_binding import create_pdf_review, read_pdf_review


def cli(*arguments):
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), *map(str, arguments), "--json"],
                            cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.comprehensive
def test_actual_export_copy_cold_read_and_existing_typed_edit_preserve_raw_values(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
                      "A,A,B,B\n400,1,400,2\n450,2,450,3\n500,3,500,4\n")
    raw = source.read_bytes()
    exported = cli("studio", source, "--out", tmp_path / "Visible", "--rule", "uvvis_spectrum",
                   "--export", "pdf,tiff_300")
    assert exported["studio_run"]["ready_to_use"] is True
    project = Path(exported["project_dir"])
    started = perf_counter()
    created = create_pdf_review(project, review_dir=tmp_path / "review")
    create_seconds = perf_counter() - started
    copy = Path(created["review_pdf"])
    original = copy.read_bytes()
    native = project / created["document"]["resource"]
    native_before = native.read_bytes()
    spec = project / "studio/spec.json"
    science_before = json.loads(spec.read_bytes())
    with pymupdf.open(copy) as document:
        document[0].add_text_annot((20, 30), "Color sample A red; retain all original values.")
        document[0].add_ink_annot([[(25, 50), (45, 60), (65, 50)]])
        marked = document.tobytes()
    copy.write_bytes(marked)
    reads = []
    for _ in range(3):
        started = perf_counter()
        result = read_pdf_review(project, review_id=created["review_id"])
        reads.append(perf_counter() - started)
        assert result["annotation_count"] == 2 and result["command_authority"] is False
    cold = subprocess.run([sys.executable, "-c",
        "import json,sys; from pathlib import Path; from sciplot_core.visual_review.pdf_review_binding import read_pdf_review; "
        "print(json.dumps(read_pdf_review(Path(sys.argv[1]), review_id=sys.argv[2])))",
        str(project), created["review_id"]], cwd=REPO_ROOT, text=True, capture_output=True, timeout=30)
    assert cold.returncode == 0, cold.stdout + cold.stderr
    assert json.loads(cold.stdout) == result
    assert native.read_bytes() == native_before and json.loads(spec.read_bytes()) == science_before
    assert copy.read_bytes() == marked and sha256(original).hexdigest() == created["original_pdf"]["sha256"]
    context = cli("task", "edit-context", project, "--figure", created["figure_id"],
                  "--operation", "set_sample_style")
    request = context["request_template"]
    assert request["expected_document_sha256"] == result["document"]["sha256"]
    request.update({"export": False, "operations": [
        {"op": "set_sample_style", "samples": ["A"], "style": {"color": "#C83E4D"}}]})
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    preview = cli("task", "start", "--request", request_path, "--task-dir", tmp_path / "edit")
    assert preview["status"] == "needs_review"
    assert preview["preview"]["scientific_audit"]["status"] == "passed"
    assert native.read_bytes() == native_before  # Marks did not bypass preview.
    response = tmp_path / "accept.json"
    response.write_text(json.dumps({"accept_preview": True,
        "expected_operation_id": preview["operation_id"]}))
    saved = cli("task", "resume", preview["task_dir"], "--response", response)
    assert saved["result"]["status"] == "saved" and saved["result"]["export_performed"] is False
    assert native.read_bytes() != native_before and json.loads(spec.read_bytes()) == science_before
    with pytest.raises(ValueError):
        read_pdf_review(project, review_id=created["review_id"])
    assert source.read_bytes() == raw and copy.read_bytes() == marked
    (tmp_path / "measurement.json").write_text(json.dumps({"create_seconds": create_seconds,
        "read_seconds": reads, "review_id": created["review_id"], "project": str(project),
        "native_revision_before": created["document"]["sha256"],
        "native_revision_after": saved["result"]["document_sha256"],
        "original_pdf_sha256": created["original_pdf"]["sha256"],
        "real_ai_calls": 0, "read_native_renders_or_exports": 0,
        "page_reference_dpi": 72}, indent=2))
