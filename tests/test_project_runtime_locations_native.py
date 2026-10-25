"""Real Qt cold and pooled IO consume the same moved scientific project bytes."""
import json

from PIL import Image
import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.native_process import PersistentWorker
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.source_coverage.document_audit import _audit_exact_document_data
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot
from sciplot_core.source_coverage.managed_documents import _verify_prepared_data, source_records
from sciplot_core.studio_core.document_edit_state import run_document_worker
from sciplot_core.studio_core.series_request import _series_from_request
from sciplot_core.studio_core.veusz_document import _write_veusz_document


@pytest.mark.comprehensive
def test_real_qt_cold_and_pool_audit_export_after_original_project_is_offline(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    source = original / "UVvis.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
                      "A,A,B,B\n400,1,400,2\n450,2,450,3\n500,3,500,4\n")
    request = {"input": str(source), "rule_id": "uvvis_spectrum", "template": "curve"}
    series, axes, _, _ = _series_from_request(request, base_dir=original)
    document = original / "studio/document.vsz"
    spec_path = _write_veusz_document(document, request=request, series=series, axis_info=axes)
    before = {"source": file_sha256(source), "document": file_sha256(document), "spec": file_sha256(spec_path)}
    spec_bytes = spec_path.read_bytes()
    store = FileProjectStore(original)
    head = store.snapshot(import_legacy=True)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "moved")
    original.rename(tmp_path / "original-offline")
    assert not source.exists() and not document.exists() and not spec_path.exists()
    worker = PersistentWorker()
    try:
        with project_runtime(cold):
            cold_audit, spec = _audit_exact_document_data(document_path=document, spec_path=spec_path)
            snapshots = [stable_file_snapshot(path, label="offline original") for path in source_records(spec)]
            assert _verify_prepared_data(spec, snapshots)["status"] == "passed"
            cold_export = run_document_worker("export-document", document, "--out", tmp_path / "cold-export",
                                             "--formats", "pdf,tiff_300", "--audit-spec", spec_path)
            with worker.activate():
                warm_audit, warm_spec = _audit_exact_document_data(document_path=document, spec_path=spec_path)
                warm_export = run_document_worker("export-document", document, "--out", tmp_path / "warm-export",
                                                 "--formats", "pdf,tiff_300", "--audit-spec", spec_path)
        assert cold_audit["status"] == warm_audit["status"] == "passed"
        assert cold_audit["units"] == warm_audit["units"] and spec == warm_spec == json.loads(spec_bytes)
        assert cold_export["document_audit"]["status"] == warm_export["document_audit"]["status"] == "passed"
        for folder in ("cold-export", "warm-export"):
            assert (tmp_path / folder / "document.pdf").stat().st_size > 0
        with Image.open(tmp_path / "cold-export/document_300dpi.tiff") as first, Image.open(tmp_path / "warm-export/document_300dpi.tiff") as second:
            assert first.size == second.size and first.convert("RGBA").tobytes() == second.convert("RGBA").tobytes()
        assert worker.starts == 1
        assert file_sha256(cold.root / "UVvis.csv") == before["source"]
        assert file_sha256(cold.root / "studio/document.vsz") == before["document"]
        assert (cold.root / "studio/spec.json").read_bytes() == spec_bytes
        assert cold.snapshot()["generation"] == head["generation"]
    finally:
        worker.close()
