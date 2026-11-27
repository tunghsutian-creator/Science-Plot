"""Reuse only the exact audit already performed within one managed preview."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from time import monotonic, time_ns
from types import SimpleNamespace

import pytest
from managed_plot_helpers import patch, request_for_source
from test_managed_backend import managed_ir

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_engine import managed_backend
from sciplot_core.plot_engine.managed_state import ManagedPreparation
from sciplot_core.plot_engine.service import PlotService


def _inspection(document: Path) -> dict:
    return {"status": "unchanged", "document_sha256": file_sha256(document),
            "opaque_native_change": False,
            "scientific_audit": {"status": "passed", "coordinates": {"series:A": "exact"}},
            "publication_qa": {"status": "passed", "hard": []}}


def test_render_returns_the_actual_passed_scientific_audit(tmp_path, monkeypatch):
    document = tmp_path / "document.vsz"
    document.write_bytes(b"exact audited candidate")
    compiler = ManagedVeuszCompiler(warm=False)
    inspected = _inspection(document)
    original = deepcopy(inspected)
    monkeypatch.setattr(compiler, "inspect_ir", lambda *_: inspected)
    monkeypatch.setattr(compiler, "_run", lambda _: {
        "document": {"sha256": file_sha256(document)}, "preview": {"path": "preview.png"}})

    rendered = compiler.render_ir(managed_ir(), document, tmp_path / "preview.png")

    assert rendered["scientific_audit"] == inspected["scientific_audit"]
    assert rendered["publication_qa"] == inspected["publication_qa"]
    assert inspected == original


def test_backend_preview_consumes_render_audit_without_reinspection(tmp_path, monkeypatch):
    backend = object.__new__(managed_backend.ManagedBackend)
    audit = {"status": "passed", "coordinates": {"series:A": "exact"}}
    candidate = {"root": str(tmp_path), "output": str(tmp_path / "output"), "ir_hash": managed_ir()["ir_hash"]}
    backend.compiler = SimpleNamespace(render_ir=lambda *_: {
        "scientific_audit": audit, "preview": {"path": "preview.png"}})
    monkeypatch.setattr(managed_backend, "prepare_binding", lambda *_args, **_kwargs:
                        ManagedPreparation(candidate, managed_ir()))
    monkeypatch.setattr(managed_backend, "read_canonical", lambda _: {})
    monkeypatch.setattr(managed_backend, "verify_document_content", lambda *_: None)
    monkeypatch.setattr(managed_backend, "require_inputs", lambda _: None)
    monkeypatch.setattr(backend, "_materialize_native", lambda *_args, **_kwargs: (tmp_path / "document.vsz", None))

    result = backend.preview({}, candidate, {}, [], tmp_path / "review")

    assert result["scientific_audit"] == audit
    assert result["_managed_binding"] == candidate
    assert result["preview"] == {"path": "preview.png"}


def test_fresh_compile_preview_reuses_audited_bytes_only(tmp_path, monkeypatch):
    backend = object.__new__(managed_backend.ManagedBackend)
    native, image = tmp_path / "document.vsz", tmp_path / "compile.png"
    native.write_bytes(b"exact audited candidate")
    image.write_bytes(b"exact audited preview")
    ir = managed_ir()
    candidate = {"root": str(tmp_path), "output": str(tmp_path / "output"), "ir_hash": ir["ir_hash"]}
    built = {**_inspection(native), "preview": {"path": str(image), "sha256": file_sha256(image)}}
    backend.compiler = SimpleNamespace(render_ir=lambda *_: pytest.fail("A fresh compile already rendered the PNG"))
    monkeypatch.setattr(managed_backend, "prepare_binding", lambda *_args, **_kwargs: ManagedPreparation(candidate, ir))
    monkeypatch.setattr(managed_backend, "read_canonical", lambda _: {})
    monkeypatch.setattr(managed_backend, "verify_document_content", lambda *_: None)
    monkeypatch.setattr(managed_backend, "require_inputs", lambda _: None)
    monkeypatch.setattr(backend, "_materialize_native", lambda *_args, **_kwargs: (native, built))

    result = backend.preview({}, candidate, {}, [], tmp_path / "review")
    assert result["scientific_audit"] == built["scientific_audit"]
    assert result["preview"] == {**built["preview"], "path": str(tmp_path / "review" / "preview.png")}
    assert file_sha256(Path(result["preview"]["path"])) == built["preview"]["sha256"]

    image.write_bytes(b"changed preview")
    with pytest.raises(ValueError) as error:
        backend.preview({}, candidate, {}, [], tmp_path / "review2")
    assert error.value.reason_code == "managed_external_mutation"
    assert not (tmp_path / "review2" / "preview.png").exists()


def test_managed_render_reuses_only_this_invocations_exact_compile(tmp_path, monkeypatch):
    backend = object.__new__(managed_backend.ManagedBackend)
    ir = managed_ir()
    native, image = tmp_path / "document.vsz", tmp_path / "compile.png"
    native.write_bytes(b"exact native document")
    image.write_bytes(b"exact native preview")
    receipt = {**_inspection(native), "native_state_hash": "a" * 64,
               "compiler_identity": {"name": "native", "version": "2", "content_hash": "b" * 64},
               "preview": {"path": str(image), "sha256": file_sha256(image), "width": 110, "height": 100}}
    original_document, original_image = native.read_bytes(), image.read_bytes()
    compile_result = receipt
    monkeypatch.setattr(backend, "_bound_ir", lambda _: ({}, ir))
    monkeypatch.setattr(backend, "_materialize_native",
                        lambda *_args, **_kwargs: (native, compile_result))
    backend.compiler = SimpleNamespace(render_ir=lambda *_: pytest.fail("A fresh compile already rendered the PNG"))

    destination = tmp_path / "render" / "preview.png"
    result = backend.render({}, destination.parent)
    assert result == {
        "kind": "sciplot_document_preview", "version": 1, "status": "passed",
        "document": {"path": str(native), "sha256": file_sha256(native)},
        "preview": {**receipt["preview"], "path": str(destination)},
        **{key: receipt[key] for key in ("scientific_audit", "publication_qa", "native_state_hash",
                                         "compiler_identity")},
    }
    assert destination.read_bytes() == original_image and native.read_bytes() == original_document

    for path in (image, native):
        original = path.read_bytes()
        path.write_bytes(b"changed")
        with pytest.raises(managed_backend.EngineError) as error:
            backend.render({}, tmp_path / "stale")
        assert error.value.reason_code == "managed_external_mutation"
        assert not (tmp_path / "stale" / "preview.png").exists()
        path.write_bytes(original)

    # An existing or recovered candidate carries no current compile proof.
    compile_result = None

    def render_existing(observed_ir, observed_native, png):
        assert (observed_ir, observed_native, png) == (ir, native, destination)
        return result

    backend.compiler.render_ir = render_existing
    assert backend.render({}, destination.parent) == result


@pytest.mark.parametrize("failure,code", [
    ("science", "external_mutation"), ("publication", "publication_qa_failed"),
])
def test_failed_exact_science_or_publication_audit_never_renders(tmp_path, monkeypatch, failure, code):
    document = tmp_path / "document.vsz"
    document.write_bytes(b"candidate")
    compiler = ManagedVeuszCompiler(warm=False)
    inspected = _inspection(document)
    if failure == "science":
        inspected["scientific_audit"]["status"] = "failed"
    else:
        inspected["publication_qa"] = {"status": "failed", "hard": [{"code": "text_outside_frame"}]}
    monkeypatch.setattr(compiler, "inspect_ir", lambda *_: inspected)
    monkeypatch.setattr(compiler, "_run", lambda _: pytest.fail("A failed audit must not render a preview"))

    with pytest.raises(DocumentError) as error:
        compiler.render_ir(managed_ir(), document, tmp_path / "preview.png")
    assert error.value.reason_code == code


@pytest.mark.parametrize("mutation", ["native_bytes", "preview_receipt"])
def test_reused_audit_cannot_bless_native_or_preview_identity_drift(tmp_path, monkeypatch, mutation):
    document = tmp_path / "document.vsz"
    document.write_bytes(b"audited candidate")
    compiler = ManagedVeuszCompiler(warm=False)
    inspected = _inspection(document)
    monkeypatch.setattr(compiler, "inspect_ir", lambda *_: inspected)

    def raced_preview(_):
        if mutation == "native_bytes":
            document.write_bytes(b"independently changed candidate")
        return {"document": {"sha256": inspected["document_sha256"] if mutation == "native_bytes" else "0" * 64},
                "preview": {"path": "preview.png"}}

    monkeypatch.setattr(compiler, "_run", raced_preview)
    with pytest.raises(ValueError, match="changed between audit and preview"):
        compiler.render_ir(managed_ir(), document, tmp_path / "preview.png")


@pytest.mark.comprehensive
def test_real_width_patch_reuses_compile_preview_and_keeps_apply_export_inspections(tmp_path, monkeypatch):
    request = request_for_source(tmp_path)
    source = Path(request["data_binding"]["data_sources"][0]["path"])
    source_before = file_sha256(source)
    service = PlotService()
    service.backend.managed.compiler.close()
    compiler = service.backend.managed.compiler = ManagedVeuszCompiler(warm=False)
    commands = []
    run = compiler._run

    def counted(arguments):
        start = monotonic()
        try:
            return run(arguments)
        finally:
            commands.append({"operation": arguments[0], "seconds": monotonic() - start})

    monkeypatch.setattr(compiler, "_run", counted)
    try:
        created = service.create(request)
        assert created["ready_to_use"], created
        creation_commands = list(commands)
        commands.clear()
        changed = service.patch(Path(created["plot"]),
            patch(created, "width", "style.line.width", "0.9pt", "series:A"))
        counts = Counter(item["operation"] for item in commands)
        evidence = {"creation_commands": creation_commands, "patch_commands": commands,
            "counts": dict(counts), "result": changed, "source_sha256_before": source_before,
            "source_sha256_after": file_sha256(source),
            "scientific_hash_before": created["scientific_hash"], "scientific_hash_after": changed["scientific_hash"],
            "scope": "Cold compiler._run commands; separate export implementation is not timed here."}
        path = REPO_ROOT / ".tmp_verify/managed_preview_audit_reuse" / f"native-{time_ns()}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, indent=2))
        assert changed["ready_to_use"] and changed["status"] == "complete", changed
        assert changed["scientific_hash"] == created["scientific_hash"]
        assert file_sha256(source) == source_before
        assert [item["operation"] for item in commands] == [
            "compile-plot-ir", "inspect-plot-ir", "inspect-plot-ir"], evidence
        assert counts == {"compile-plot-ir": 1, "inspect-plot-ir": 2}
    finally:
        service.close()
