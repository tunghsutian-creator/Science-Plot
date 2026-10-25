"""The native audit explicitly identifies private produced input tables."""

import json

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
from sciplot_core.studio_core.preparation_commands import audit_studio_candidate


def test_audited_private_derived_table_binds_its_output_and_original_input_stays_live(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "source.csv"
    source.write_bytes(b"x,y\n0,1\n")
    (project / "plot_request.json").write_text(json.dumps({"input": "source.csv"}))
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    with studio_preparation_candidate(store) as candidate:
        derived = candidate.project_dir / "generated/derived.csv"
        derived.parent.mkdir()
        derived.write_bytes(b"x,y\n0,2\n")
        native = candidate.project_dir / "studio/document.vsz"
        native.parent.mkdir()
        native.write_bytes(b"native audit port double")
        spec = native.parent / "spec.json"
        spec.write_text("{}")
        records = {str(source): file_sha256(source),
                   str(project / "generated/derived.csv"): file_sha256(derived)}
        calls = []

        def audit(**options):
            assert options["document_path"] == native
            assert options["spec_path"] == spec
            calls.append(native)
            return {"status": "passed", "kind": "native-port-double"}, {"records": records}

        monkeypatch.setattr("sciplot_core.source_coverage.document_audit._audit_exact_document_data", audit)
        monkeypatch.setattr("sciplot_core.source_coverage.managed_documents.source_records", lambda payload: payload["records"])
        _, sources = audit_studio_candidate(candidate, {"document": str(native)})
        by_locator = {item.locator: item for item in sources}
        assert by_locator[str(source)].produced_resource is None
        produced = by_locator[str(project / "generated/derived.csv")]
        assert produced.produced_resource == "generated/derived.csv"
        assert produced.version == file_sha256(derived)
        assert produced.data == derived.read_bytes()
        assert len(calls) == 1
        assert not (project / "generated").exists()
    assert source.read_bytes() == b"x,y\n0,1\n"
    assert store.snapshot()["generation"] == before["generation"]
