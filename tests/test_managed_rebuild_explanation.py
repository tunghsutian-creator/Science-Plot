"""Observed managed rebuild reasons are compact and never execute science/native work."""

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_plot_ir import managed_example

from sciplot_core.foundation.file_hashing import existing_file_sha256, file_sha256
from sciplot_core.plot_document import invalidated_nodes
from sciplot_core.plot_engine import service as service_module
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_ir import create_managed_document


def _graph() -> dict:
    nodes = [
        {"id": "source:A", "kind": "source", "dependencies": [], "parameters": {},
         "version": "1", "content_hash": "a" * 64},
        {"id": "source:B", "kind": "source", "dependencies": [], "parameters": {},
         "version": "1", "content_hash": "b" * 64},
        {"id": "transform:normalize-A", "kind": "transform", "dependencies": ["source:A"],
         "parameters": {}, "version": "1"},
        {"id": "transform:normalize-B", "kind": "transform", "dependencies": ["source:B"],
         "parameters": {}, "version": "1"},
        {"id": "mapping:series:A", "kind": "mapping", "dependencies": ["transform:normalize-A"],
         "parameters": {}, "version": "1"},
        {"id": "mapping:series:B", "kind": "mapping", "dependencies": ["transform:normalize-B"],
         "parameters": {}, "version": "1"},
        {"id": "compile", "kind": "compile", "dependencies": ["mapping:series:A", "mapping:series:B"],
         "parameters": {}, "version": "1"},
        {"id": "render", "kind": "render", "dependencies": ["compile"], "parameters": {}, "version": "1"},
        {"id": "export", "kind": "export", "dependencies": ["render"], "parameters": {}, "version": "1"},
    ]
    return {"kind": "sciplot_dependency_graph", "schema_version": 1, "nodes": nodes}


class ObservationOnlyBackend:
    def __init__(self, native: Path):
        self.native = native
        self.sealed_native_sha = file_sha256(native)
        self.managed = SimpleNamespace(compiler=object())
        self.fingerprint_calls = 0

    def fingerprint(self, binding):
        self.fingerprint_calls += 1
        return {"files": {path: existing_file_sha256(Path(path))
                          for path in binding["fingerprint"]["files"]},
                "artifacts": {str(self.native): ("external_native_mutation" if self.native.is_file()
                              and existing_file_sha256(self.native) != self.sealed_native_sha
                              else binding["ir_hash"])}}

    def preview(self, *_args, **_kwargs):
        raise AssertionError("description must not preview")

    def render(self, *_args, **_kwargs):
        raise AssertionError("description must not render")

    def export(self, *_args, **_kwargs):
        raise AssertionError("description must not export")

    def apply(self, *_args, **_kwargs):
        raise AssertionError("description must not apply")


@pytest.fixture
def case(tmp_path, monkeypatch):
    template, data_binding, _ = managed_example()
    sources = {}
    for item in data_binding["data_sources"]:
        path = tmp_path / f'{item["source_id"]}.csv'
        path.write_text("x,y\n1,2\n")
        item["path"], item["sha256"] = str(path), file_sha256(path)
        sources[item["source_id"]] = path
    document = create_managed_document(template, data_binding, plot_id="rebuild-observation")
    native = tmp_path / "document.vsz"
    native.write_bytes(b"sealed native input")
    root = tmp_path / "saved-plot"
    root.mkdir()
    (root / "head.json").write_bytes(b"untouched head")
    binding = {"document": str(native), "ir_hash": "c" * 64, "ir_path": str(tmp_path / "plot-ir.json"),
               "fingerprint": {"files": {str(path): file_sha256(path) for path in sources.values()},
                               "artifacts": {str(native): "c" * 64}}, "graph": _graph()}
    head = {"document": document, "binding": binding}
    backend = ObservationOnlyBackend(native)
    monkeypatch.setattr(service_module, "canonical_path", lambda path: path)
    monkeypatch.setattr(service_module, "external_project_session", lambda _: nullcontext())
    monkeypatch.setattr(service_module, "load_head", lambda _: head)
    monkeypatch.setattr(service_module, "active", lambda _: None)
    service = PlotService(backend=backend)
    return service, root, head, backend, sources, native


def _summary(case):
    service, root, *_ = case
    return service.describe(root, description={"scope": "summary"})


def test_current_and_presentation_only_revision_do_not_invent_rebuild_or_reuse(case):
    service, root, head, _backend, _sources, _native = case
    current = _summary(case)
    explanation = current["rebuild_explanation"]
    assert current["status"] == "current" and explanation["why_dirty"] == []
    assert explanation["affected_nodes"] == []
    assert explanation["verified_reused_nodes"] == []
    assert explanation["not_marked_invalid_by_saved_graph"] == [node["id"] for node in _graph()["nodes"]]
    before = head["document"]["scientific_hash"]
    updated = deepcopy(head["document"])
    updated["revision"] += 1
    updated["presentation_hash"] = "d" * 64
    head["document"] = updated
    head["binding"]["graph"]["nodes"][-3]["parameters"]["presentation_hash"] = "d" * 64
    after = service.describe(root, description={"scope": "summary"})
    assert after["scientific_hash"] == before
    assert after["rebuild_explanation"]["why_dirty"] == []
    assert after["rebuild_explanation"]["affected_nodes"] == []


@pytest.mark.parametrize("missing", [False, True])
def test_changed_or_missing_source_has_exact_saved_graph_descendants_and_no_parse(case, monkeypatch, missing):
    _service, root, head, _backend, sources, native = case
    before_head, before_native = deepcopy(head), native.read_bytes()
    monkeypatch.setattr("sciplot_core.plot_engine.managed_sources.load_sources",
                        lambda *_: (_ for _ in ()).throw(AssertionError("source parsed")))
    if missing:
        sources["A"].unlink()
    else:
        sources["A"].write_bytes(b"invalid scientific table bytes")
    before_source = sources["A"].read_bytes() if sources["A"].exists() else None
    summary = _summary(case)
    explanation = summary["rebuild_explanation"]
    assert summary["status"] == "stale" and summary["changed_inputs"] == [str(sources["A"])]
    assert explanation["why_dirty"] == [{"code": "source_missing" if missing else "source_changed",
                                         "input": str(sources["A"]), "node": "source:A"}]
    assert explanation["affected_nodes"] == summary["dependencies"]["invalidated"] == invalidated_nodes(
        head["binding"]["graph"], ["source:A"])
    assert explanation["not_marked_invalid_by_saved_graph"] == [
        "source:B", "transform:normalize-B", "mapping:series:B"]
    assert explanation["verified_reused_nodes"] == []
    assert "source_content_requires_validation" in explanation["unknown"]
    assert summary["next_step"]["action"] == "refresh_scientific_binding"
    assert head == before_head and native.read_bytes() == before_native
    assert (root / "head.json").read_bytes() == b"untouched head"
    assert (sources["A"].read_bytes() if sources["A"].exists() else None) == before_source
    assert not (root / "transform-cache").exists()
    assert "invalid scientific table bytes" not in str(summary)


def test_changed_native_summary_defers_inspection_and_preserves_resolution_guard(case, monkeypatch):
    _service, root, head, _backend, sources, native = case
    from sciplot_core.plot_engine import managed_external

    monkeypatch.setattr(managed_external, "inspect_managed_mutation",
                        lambda *_: (_ for _ in ()).throw(AssertionError("native inspector launched")))
    native.write_bytes(b"human changed native bytes")
    before_head, before_native = deepcopy(head), native.read_bytes()
    summary = _summary(case)
    explanation = summary["rebuild_explanation"]
    assert summary["status"] == "stale" and summary["artifact_status"] == "changed"
    assert summary["next_step"] == {"action": "resolve_external_mutation", "automatic_adoption": False}
    assert summary["external_mutation_unavailable"]["reason_code"] == "native_inspection_deferred"
    assert explanation["why_dirty"] == [{"code": "native_artifact_changed", "input": str(native), "node": "render"}]
    assert explanation["affected_nodes"] == invalidated_nodes(head["binding"]["graph"], ["render"])
    assert explanation["verified_reused_nodes"] == []
    assert head == before_head and native.read_bytes() == before_native
    assert (root / "head.json").read_bytes() == b"untouched head"
    assert all(source.read_text() == "x,y\n1,2\n" for source in sources.values())
    assert not (root / "transform-cache").exists()


def test_source_and_native_drift_keep_both_guards_without_read_side_effects(case, monkeypatch):
    service, root, head, _backend, sources, native = case
    from sciplot_core.plot_engine import managed_external

    monkeypatch.setattr(managed_external, "inspect_managed_mutation",
                        lambda *_: (_ for _ in ()).throw(AssertionError("native inspector launched")))
    monkeypatch.setattr("sciplot_core.plot_engine.managed_sources.load_sources",
                        lambda *_: (_ for _ in ()).throw(AssertionError("source parsed")))
    sources["A"].write_bytes(b"changed source bytes, not a parsed table")
    native.write_bytes(b"changed native artifact")
    before_head = deepcopy(head)
    before_files = {path: path.read_bytes() for path in (*sources.values(), native, root / "head.json")}

    summary = service.describe(root, description={"scope": "summary"})

    assert summary["status"] == "stale"
    assert set(summary["changed_inputs"]) == {str(sources["A"]), str(native)}
    assert summary["artifact_status"] == "changed"
    assert summary["external_mutation_unavailable"]["reason_code"] == "native_inspection_deferred"
    assert summary["next_step"] == {"action": "resolve_external_mutation", "automatic_adoption": False}
    assert summary["rebuild_explanation"]["why_dirty"] == [
        {"code": "source_changed", "input": str(sources["A"]), "node": "source:A"},
        {"code": "native_artifact_changed", "input": str(native), "node": "render"},
    ]
    assert {"source_content_requires_validation", "native_receipt_requires_resolution"} <= set(
        summary["rebuild_explanation"]["unknown"])
    assert summary["rebuild_explanation"]["verified_reused_nodes"] == []
    assert "figure_spec" not in summary and "figure_template_schema" not in summary
    assert head == before_head
    assert {path: path.read_bytes() for path in before_files} == before_files
    assert not (root / "transform-cache").exists()


def test_default_full_retains_existing_native_inspection(case, monkeypatch):
    service, root, _head, _backend, _sources, native = case
    from sciplot_core.plot_engine import managed_external

    observed = []
    monkeypatch.setattr(managed_external, "inspect_managed_mutation",
                        lambda *_: observed.append("inspected") or {"classification": "opaque_native_change"})
    native.write_bytes(b"human changed native bytes")
    full = service.describe(root)
    assert observed == ["inspected"]
    assert full["external_mutation"]["classification"] == "opaque_native_change"
    assert "rebuild_explanation" not in full
    summary = _summary(case)
    assert observed == ["inspected"]
    assert summary["external_mutation_unavailable"]["reason_code"] == "native_inspection_deferred"


def test_missing_native_is_disposable_but_future_reuse_remains_unknown(case):
    _service, root, head, _backend, _sources, native = case
    native.unlink()
    summary = _summary(case)
    explanation = summary["rebuild_explanation"]
    assert summary["status"] == "dirty" and summary["next_step"]["action"] == "plot.export"
    assert explanation["why_dirty"] == [{"code": "native_artifact_missing", "node": "render"}]
    assert explanation["affected_nodes"] == ["render", "export"]
    assert explanation["native_receipt"] == "native_missing"
    assert explanation["verified_reused_nodes"] == []
    assert not native.exists() and not Path(head["binding"]["ir_path"]).exists()
    assert not (root / "transform-cache").exists()


def test_changed_executor_maps_only_its_branch_and_requires_validation(case):
    _service, _root, head, _backend, _sources, native = case
    script, executable = native.parent / "executor.py", native.parent / "executable"
    script.write_bytes(b"old executor")
    executable.write_bytes(b"old binary")
    head["document"]["scientific"]["transforms"][0]["executor"] = {"kind": "external", "id": "executor:A"}
    head["document"]["scientific"]["provenance"]["managed"]["executors"] = {
        "executor:A": {"script": str(script), "executable": str(executable)}}
    head["binding"]["fingerprint"]["files"].update({str(script): file_sha256(script),
                                                        str(executable): file_sha256(executable)})
    script.write_bytes(b"new executor")
    summary = _summary(case)
    explanation = summary["rebuild_explanation"]
    assert explanation["why_dirty"] == [{"code": "executor_changed", "input": str(script),
                                         "nodes": ["transform:normalize-A"]}]
    assert explanation["affected_nodes"] == invalidated_nodes(
        head["binding"]["graph"], ["transform:normalize-A"])
    assert "transform:normalize-B" in explanation["not_marked_invalid_by_saved_graph"]
    assert "executor_requires_validation" in explanation["unknown"]
    assert summary["next_step"]["action"] == "refresh_scientific_binding"


def test_unmapped_changed_content_does_not_claim_unaffected_nodes(case):
    _service, _root, head, _backend, _sources, native = case
    internal = native.parent / "content.json"
    internal.write_text("old")
    head["binding"]["scientific_content_files"] = {str(internal): file_sha256(internal)}
    internal.write_text("changed")
    summary = _summary(case)
    explanation = summary["rebuild_explanation"]
    assert summary["status"] == "stale" and explanation["affected_nodes"] == []
    assert explanation["why_dirty"] == [{"code": "unmapped_input_changed", "input": str(internal)}]
    assert explanation["not_marked_invalid_by_saved_graph"] == []
    assert explanation["not_marked_invalid_count"] is None
    assert "unmapped_affected_nodes" in explanation["unknown"]


def test_not_marked_ids_are_bounded_without_losing_the_total(case):
    _service, _root, head, _backend, _sources, _native = case
    for number in range(40):
        head["binding"]["graph"]["nodes"].append({
            "id": f"source:extra-{number}", "kind": "source", "dependencies": [],
            "parameters": {}, "version": "1", "content_hash": "e" * 64})
    explanation = _summary(case)["rebuild_explanation"]
    assert explanation["not_marked_invalid_count"] == 49
    assert len(explanation["not_marked_invalid_by_saved_graph"]) == 32
    assert explanation["not_marked_invalid_by_saved_graph"][0] == "source:A"
    assert explanation["not_marked_invalid_by_saved_graph"][-1] == "source:extra-22"


def test_foreign_renderer_receipt_does_not_claim_reuse(case, monkeypatch):
    _service, _root, head, _backend, _sources, native = case
    from sciplot_core.foundation.json_io import atomic_write_json
    from sciplot_core.plot_engine import managed_rebuild_explanation

    monkeypatch.setattr("sciplot_core.plot_backends.managed.compiler_identity",
                        lambda: {"name": "sciplot.veusz.plot_ir", "version": "2", "content_hash": "d" * 64})
    atomic_write_json(native.parent / "build.json", {"ir_hash": head["binding"]["ir_hash"],
        "document_sha256": file_sha256(native),
        "compiler_identity": {"name": "foreign.renderer", "version": "1", "content_hash": "e" * 64}})
    summary = _summary(case)
    explanation = summary["rebuild_explanation"]
    assert summary["status"] == "current"
    assert explanation["why_dirty"] == [{"code": "renderer_identity_mismatch", "evidence": "native_receipt"}]
    assert explanation["affected_nodes"] == []
    assert explanation["native_receipt"] == "renderer_identity_mismatch"
    assert explanation["verified_reused_nodes"] == []
    assert "native_receipt_requires_resolution" in explanation["unknown"]
    assert managed_rebuild_explanation._native_receipt(head["binding"], "current") == "renderer_identity_mismatch"

    atomic_write_json(native.parent / "build.json", {"ir_hash": head["binding"]["ir_hash"],
        "document_sha256": file_sha256(native),
        "compiler_identity": {"name": "sciplot.veusz.plot_ir", "version": "2", "content_hash": "d" * 64}})
    matching = _summary(case)["rebuild_explanation"]
    assert matching["native_receipt"] == "byte_sealed_receipt"
    assert matching["why_dirty"] == [] and matching["verified_reused_nodes"] == []


def test_pending_is_preserved_without_rebuild_advice(case, monkeypatch):
    _service, _root, _head, _backend, _sources, _native = case
    monkeypatch.setattr(service_module, "active", lambda _: {
        "request": {"idempotency_key": "existing-tx"}, "phase": "needs_review"})
    summary = _summary(case)
    assert summary["pending"] == {"idempotency_key": "existing-tx", "phase": "needs_review"}
    assert "next_step" not in summary
    assert summary["rebuild_explanation"]["verified_reused_nodes"] == []


def test_existing_rpc_scope_routes_the_same_explanation(case):
    service, root, _head, _backend, _sources, _native = case
    from sciplot_core.plot_protocol import rpc

    requested = {"scope": "summary"}
    expected = service.describe(root, description=requested)["rebuild_explanation"]
    for method, params in (("plot.describe", {"plot": str(root), "description": requested}),
                           ("project.open", {"target": str(root), "description": requested})):
        response = rpc.handle(service, {"jsonrpc": "2.0", "id": method, "method": method, "params": params})
        assert response["result"]["rebuild_explanation"] == expected
