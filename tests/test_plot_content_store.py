"""Large scientific provenance stays lossless while transaction snapshots stay small."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from sciplot_core.plot_document import apply_patch, seal_document
from sciplot_core.plot_engine import content_store
from sciplot_core.plot_engine.content_store import intern_document, resolve_document_content, verify_document_content
from sciplot_core.plot_engine.errors import EngineError


def document(points=65000):
    return seal_document({"kind": "sciplot_document", "schema_version": 1, "plot_id": "dense-nmr", "revision": 0,
        "scientific": {"data_sources": [{"path": "/raw/NMR.csv", "sha256": "a" * 64}], "transforms": [],
            "mappings": {"series:nmr": {"x": "ppm", "y": "intensity", "x_unit": "ppm", "y_unit": "a.u."}},
            "guards": {"point_count": points, "preserve_order": True},
            "provenance": {"imported_specification": {"series": [{"sample": "E2", "x": list(range(points)),
                "y": [None if index % 101 == 0 else index / 7 for index in range(points)]}],
                "annotations": [{"text": "科学标注", "unit": "ppm"}]}, "small_note": {"method": "raw, no fitting"}}},
        "presentation": {"objects": {"series:nmr": {"kind": "series", "label": "E2",
            "properties": {"style.line.width": "1pt"},
            "capabilities": {"style.line.width": {"type": "physical_size", "risk": "presentation"}}}},
            "layout": {}, "theme": {}, "export_configuration": {"formats": ["pdf", "tiff_300"]}},
        "coverage": {"mode": "legacy_shadow", "limitations": ["Native original retained"]}})


def blob_path(root, compact):
    ref = compact["scientific"]["provenance"]["imported_specification"]
    return root / "content" / (ref["sha256"] + ".json")


def test_dense_provenance_round_trips_all_coordinates_order_units_and_missing_values(tmp_path):
    original = document()
    untouched = deepcopy(original)
    compact = intern_document(tmp_path, original)
    reference = compact["scientific"]["provenance"]["imported_specification"]
    assert set(reference) == {"kind", "schema_version", "sha256", "encoding", "byte_length"}
    assert reference["byte_length"] > 1_000_000
    assert "path" not in reference and str(tmp_path) not in json.dumps(compact["scientific"])
    assert hashlib.sha256(blob_path(tmp_path, compact).read_bytes()).hexdigest() == reference["sha256"]
    assert resolve_document_content(tmp_path, compact) == original and original == untouched
    assert compact["scientific_hash"] != original["scientific_hash"]  # Different canonical representation.
    assert compact["presentation_hash"] == original["presentation_hash"]


def test_presentation_transaction_size_is_bounded_instead_of_repeating_65000_points(tmp_path):
    compact = intern_document(tmp_path, document())
    after, diff, _ = apply_patch(compact, {"plot_id": "dense-nmr", "base_revision": 0, "idempotency_key": "width",
        "intent_class": "presentation", "changes": [{"op": "set", "target": ["series:nmr"],
        "property": "style.line.width", "value": "0.7pt"}]})
    encoded = json.dumps({"before": compact, "document": after, "diff": diff}).encode()
    assert len(encoded) < 6000 and after["scientific_hash"] == compact["scientific_hash"]
    assert resolve_document_content(tmp_path, after)["scientific"] == document()["scientific"]


def test_small_documents_remain_inline_and_do_not_allocate_content_directories(tmp_path):
    original = document(10)
    compact = intern_document(tmp_path, original)
    assert compact == original and not (tmp_path / "content").exists()


def test_repeated_import_and_compact_reimport_reuse_exact_blob_without_rewrite(tmp_path):
    original = document()
    first = intern_document(tmp_path, original)
    path = blob_path(tmp_path, first)
    before = path.stat()
    assert intern_document(tmp_path, original) == first
    assert intern_document(tmp_path, first) == first
    after = path.stat()
    assert before.st_ino == after.st_ino and before.st_mtime_ns == after.st_mtime_ns
    assert len(list((tmp_path / "content").iterdir())) == 1


def test_content_identity_is_independent_of_document_store_location(tmp_path):
    original = document()
    first = intern_document(tmp_path / "one", original)
    second = intern_document(tmp_path / "two", original)
    assert first == second and first["scientific_hash"] == second["scientific_hash"]


@pytest.mark.parametrize("mutation,code", [
    (lambda path: path.write_bytes(b"corrupt scientific state"), "document_content_corrupt"),
    (lambda path: path.unlink(), "document_content_unavailable"),
])
def test_missing_or_changed_content_stops_currentness_verification_and_resolution(tmp_path, mutation, code):
    compact = intern_document(tmp_path, document())
    mutation(blob_path(tmp_path, compact))
    for operation in (verify_document_content, resolve_document_content):
        with pytest.raises(EngineError) as error:
            operation(tmp_path, compact)
        assert error.value.reason_code == code


def test_corrupt_existing_blob_is_not_overwritten_by_reimport(tmp_path):
    original = document()
    compact = intern_document(tmp_path, original)
    path = blob_path(tmp_path, compact)
    path.write_bytes(b"evidence of corruption")
    with pytest.raises(EngineError) as error:
        intern_document(tmp_path, original)
    assert error.value.reason_code == "document_content_corrupt"
    assert path.read_bytes() == b"evidence of corruption"


@pytest.mark.parametrize("field,value", [("sha256", "../../outside"), ("byte_length", True),
                                         ("schema_version", True), ("path", "/untrusted/location")])
def test_malformed_reference_is_rejected_before_any_file_lookup(tmp_path, field, value, monkeypatch):
    compact = intern_document(tmp_path, document())
    reference = compact["scientific"]["provenance"]["imported_specification"]
    reference[field] = value
    monkeypatch.setattr(content_store, "_stable_file_snapshot", lambda *_args, **_kwargs: pytest.fail("Unsafe reference reached filesystem"))
    with pytest.raises(EngineError) as error:
        verify_document_content(tmp_path, compact)
    assert error.value.reason_code == "document_content_reference_invalid"


def test_currentness_guard_never_parses_or_reserializes_large_json(tmp_path, monkeypatch):
    compact = intern_document(tmp_path, document())
    monkeypatch.setattr(content_store.json, "loads", lambda *_: pytest.fail("Blob verification must not parse JSON"))
    monkeypatch.setattr(content_store, "_encoded", lambda *_: pytest.fail("Blob verification must not serialize JSON"))
    verify_document_content(tmp_path, compact)


def test_process_interruption_after_blob_publish_preserves_recoverable_complete_bytes(tmp_path, monkeypatch):
    original = document()
    sync = content_store._fsync_directory
    monkeypatch.setattr(content_store, "_fsync_directory", lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        intern_document(tmp_path, original)
    monkeypatch.setattr(content_store, "_fsync_directory", sync)
    recovered = intern_document(tmp_path, original)
    assert resolve_document_content(tmp_path, recovered) == original
    assert not list((tmp_path / "content").glob(".content-*.tmp"))


def test_content_publication_never_replaces_a_concurrent_different_blob(tmp_path, monkeypatch):
    original = document()
    link = content_store.os.link

    def conflicting_link(source, target):
        Path(target).write_bytes(b"concurrent corrupt bytes")
        return link(source, target)

    monkeypatch.setattr(content_store.os, "link", conflicting_link)
    with pytest.raises(EngineError) as error:
        intern_document(tmp_path, original)
    assert error.value.reason_code == "document_content_corrupt"
    assert not list((tmp_path / "content").glob(".content-*.tmp"))


def content_engine(tmp_path):
    from test_plot_engine import FakeBackend
    from sciplot_core.plot_engine.content_store import referenced_files
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.plot_engine.storage import commit

    backend = FakeBackend(tmp_path / "backend")
    original, binding = backend.initial()
    original["scientific"]["provenance"] = document()["scientific"]["provenance"]
    original = seal_document(original)
    root = tmp_path / "plot"
    compact = intern_document(root, original)
    binding["scientific_content_files"] = referenced_files(root, compact)
    commit(root, compact, binding, "import")
    return PlotService(backend), backend, root, compact, original


def test_corrupt_blob_blocks_service_before_native_calls(tmp_path):
    from test_plot_engine import request

    service, backend, root, compact, _original = content_engine(tmp_path)
    blob_path(root, compact).write_bytes(b"altered scientific proof")
    for operation in (lambda: service.describe(root), lambda: service.patch(root, request()), lambda: service.export(root)):
        with pytest.raises(EngineError) as exc:
            operation()
        assert exc.value.reason_code == "document_content_corrupt"
    assert not any(backend.calls.values())


def test_content_bound_style_and_noop_preserve_original_science_and_blob(tmp_path):
    from test_plot_engine import request
    from sciplot_core.plot_engine.storage import load_head

    service, backend, root, compact, original = content_engine(tmp_path)
    path = blob_path(root, compact)
    before = path.read_bytes()
    edited = service.patch(root, request())
    noop = service.patch(root, request(key="noop", revision=1))
    assert edited["status"] == noop["status"] == "complete" and backend.native_writes == 1
    assert noop["changed"] is False and backend.calls["export"] == 1
    current = load_head(root)["document"]
    assert current["scientific_hash"] == compact["scientific_hash"] and path.read_bytes() == before
    assert resolve_document_content(root, current)["scientific"] == original["scientific"]


def test_blob_changed_after_preview_blocks_apply_before_native_write(tmp_path, monkeypatch):
    from test_plot_engine import request

    service, backend, root, compact, _original = content_engine(tmp_path)
    preview = backend.preview

    def corrupt_after_preview(*args):
        reviewed = preview(*args)
        blob_path(root, compact).write_bytes(b"corrupt after audit")
        return reviewed

    monkeypatch.setattr(backend, "preview", corrupt_after_preview)
    result = service.patch(root, request())
    assert result["status"] == "blocked" and result["error"]["reason_code"] == "document_content_corrupt"
    assert backend.native_writes == 0 and backend.calls["apply"] == 0


def test_storage_refuses_content_reference_without_matching_runtime_guard(tmp_path):
    from sciplot_core.plot_engine.storage import commit

    compact = intern_document(tmp_path, document())
    with pytest.raises(EngineError) as exc:
        commit(tmp_path, compact, {"fingerprint": {}}, "import")
    assert exc.value.reason_code == "document_content_binding_invalid"
