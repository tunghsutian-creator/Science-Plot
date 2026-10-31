"""Suite source diagnostics translate only the exact proved byte conflict."""

import subprocess

import pytest

from sciplot_core.foundation.source_errors import SourceVersionMismatch
from sciplot_core.foundation.source_locations import source_location_scope
from sciplot_core.project_store import ProjectConflict
from sciplot_core.project_store.errors import ProjectSourceVersionMismatch
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.workflow.rheology_tts_saved_state import _check_sources

from test_project_incoming_sources import changed_external
from test_project_query_readonly_sources import inventory


def test_exact_external_source_byte_drift_keeps_typed_proof_and_suite_diagnostic(tmp_path, monkeypatch):
    store, raw, fresh, sealed, original = changed_external(tmp_path)
    before = inventory(tmp_path)
    source = {"path": str(raw), "sha256": sealed.sha256, "source_id": sealed.source_id}
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("Source refusal started native work"))
    with project_runtime(store):
        with pytest.raises(ProjectSourceVersionMismatch) as lower:
            store.resolve_path(raw, expected_sha256=sealed.sha256, source_id=sealed.source_id)
        assert isinstance(lower.value, ProjectConflict)
        assert (lower.value.literal, lower.value.expected_sha256, lower.value.observed_sha256) == (str(raw), sealed.sha256, fresh.sha256)
        with pytest.raises(ValueError, match="Original source changed") as public:
            _check_sources([source])
        assert isinstance(public.value.__cause__, ProjectSourceVersionMismatch)
        assert inventory(tmp_path) == before
        raw.write_bytes(original)
        _check_sources([source])
    assert raw.read_bytes() == original


@pytest.mark.parametrize("fault", ["missing", "alias", "unknown-id"])
def test_nonbyte_store_source_rejections_never_become_byte_mismatches(tmp_path, fault):
    store, raw, _fresh, sealed, original = changed_external(tmp_path)
    raw.write_bytes(original)
    source_id = sealed.source_id
    if fault == "missing":
        raw.unlink()
    elif fault == "alias":
        raw.unlink()
        raw.symlink_to(store.root / "raw/same.csv")
    else:
        source_id = "f" * 32
    with project_runtime(store):
        with pytest.raises(ValueError) as error:
            _check_sources([{"path": str(raw), "sha256": sealed.sha256, "source_id": source_id}])
    assert not isinstance(error.value, SourceVersionMismatch)
    assert not str(error.value).startswith("Original source changed")


@pytest.mark.parametrize("error", [PermissionError("unreadable"), ProjectConflict("mode or membership changed"),
    ValueError("The exact original source differs from its registered version."),
    SourceVersionMismatch("/foreign/source.csv", "a" * 64, "b" * 64, "foreign byte mismatch")])
def test_suite_boundary_preserves_unrelated_failures_without_string_matching(error):
    class Resolver:
        def resolve_path(self, *_args, **_kwargs):
            raise error
        def literal_path(self, path):
            return str(path)

        def file_paths(self, actual, *, expected_sha256=None, source_id=None):
            literal = self.literal_path(actual)
            return literal, self.resolve_path(actual, expected_sha256=expected_sha256, source_id=source_id)

    with source_location_scope(Resolver()), pytest.raises(type(error)) as caught:
        _check_sources([{"path": "/selected/source.csv", "sha256": "a" * 64}])
    assert caught.value is error
