"""Fresh-document, scientific and pixel equivalence under a reused Qt process."""

import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.native_process import PersistentWorker
from sciplot_core.veusz_runtime import veusz_worker_environment


@pytest.mark.comprehensive
def test_warm_worker_matches_cold_audit_pixels_and_reopens_changed_vsz(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
                      "E2,E2,E4,E4\n400,1,400,2\n450,2,450,3\n500,3,500,4\n")
    source_sha = file_sha256(source)
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "studio", str(source),
        "--rule", "uvvis_spectrum", "--export", "pdf,tiff_300", "--json"],
        capture_output=True, text=True, check=True, timeout=180)
    project = Path(json.loads(result.stdout)["project_dir"])
    document, spec = project / "studio/document.vsz", project / "studio/spec.json"
    native_sha = file_sha256(document)
    prefix = [sys.executable, "-m", "sciplot_core.veusz_worker"]

    def cold(argv):
        result = subprocess.run([*prefix, *map(str, argv)], capture_output=True, text=True, check=True,
                                timeout=120, env=veusz_worker_environment())
        return json.loads(result.stdout)

    worker = PersistentWorker()
    try:
        def warm(argv):
            return json.loads(worker.run([*prefix, *map(str, argv)], check=True).stdout)

        audit_args = ["audit-spec-data", document, spec, "--allow-presentation-edits"]
        assert warm(audit_args) == cold(audit_args)
        cold(["preview-document", document, "--out", tmp_path / "cold.png"])
        warm(["preview-document", document, "--out", tmp_path / "warm.png"])
        for mode, runner in [("cold", cold), ("warm", warm)]:
            exported = runner(["export-document", document, "--formats", "pdf,tiff_300",
                               "--out", tmp_path / mode, "--audit-spec", spec])
            assert exported["document_audit"]["status"] == "passed"
        for cold_path, warm_path in [(tmp_path / "cold.png", tmp_path / "warm.png"),
                                    (tmp_path / "cold/document_300dpi.tiff", tmp_path / "warm/document_300dpi.tiff")]:
            with Image.open(cold_path) as a, Image.open(warm_path) as b:
                assert a.size == b.size and a.convert("RGBA").tobytes() == b.convert("RGBA").tobytes()
        copied = tmp_path / "copied.vsz"
        copied.write_bytes(document.read_bytes())
        before = warm(["inspect-document-state", copied])
        selected = before["widgets"]["/page1/graph1/series_1"]
        expected = selected["settings"]["PlotLine/width"]
        changes = tmp_path / "changes.json"
        changes.write_text(json.dumps([{"object_path": "/page1/graph1/series_1",
            "setting_path": "/page1/graph1/series_1/PlotLine/width", "expected_value": expected, "value": "1.3pt"}]))
        candidate = tmp_path / "candidate.vsz"
        warm(["edit-document", copied, "--changes", changes, "--output-document", candidate,
              "--preview-png", tmp_path / "candidate.png", "--audit-spec", spec])
        copied.write_bytes(candidate.read_bytes())
        after = warm(["inspect-document-state", copied])
        assert after["widgets"]["/page1/graph1/series_1"]["settings"]["PlotLine/width"] == "1.3pt"
        assert worker.starts == 1 and worker.last_pid is not None
        assert file_sha256(document) == native_sha and file_sha256(source) == source_sha
    finally:
        worker.close()
