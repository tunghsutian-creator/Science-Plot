"""One binding resolves one scientific snapshot; later calls observe fresh bytes."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from managed_plot_helpers import request_for_source
from sciplot_core.plot_document import DocumentError, seal_document
from sciplot_core.plot_engine import managed_state
from sciplot_core.plot_engine.content_store import intern_document, resolve_document_content
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata
from sciplot_core.plot_ir import compile_document, create_managed_document
from sciplot_core.plot_transforms.graph import dependency_graph
from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_lifecycle.repository import FileProjectRepository


class ObservedRepository(FileProjectRepository):
    """Record real content reads through the existing filesystem repository port."""

    def __init__(self):
        super().__init__()
        self.content_reads = []

    def content_snapshot(self, path):
        snapshot = super().content_snapshot(path)
        self.content_reads.append((path, len(snapshot["bytes"])))
        return snapshot


@pytest.fixture(params=[False, True], ids=["inline", "content-addressed"])
def scientific_binding_case(tmp_path, request):
    original = request_for_source(tmp_path)
    repository = ObservedRepository()
    root = tmp_path / "semantic"
    with repository_scope(repository, capabilities=COMPATIBILITY_CAPABILITIES):
        document = create_managed_document(original["template_definition"], original["data_binding"], plot_id="binding")
        document = resolved_metadata(document, rule_id=original["rule_id"], executors={})
        document, _ = resolve_science(root, document)
        if request.param:
            document = intern_document(root, document, minimum_bytes=2)
        expanded = resolve_document_content(root, document)
        repository.content_reads.clear()
        yield repository, root, document, expanded


def test_binding_resolves_one_snapshot_and_preserves_complete_ir_and_graph(scientific_binding_case, monkeypatch):
    repository, root, document, expanded = scientific_binding_case
    before = deepcopy(document)
    expected_ir = compile_document(document, expanded["scientific"]["provenance"]["datasets"],
                                   capabilities=COMPATIBILITY_CAPABILITIES)
    expected_graph = dependency_graph(document, expanded["scientific"]["provenance"]["datasets"])
    resolved = []
    original = managed_state.resolve_document_content

    def observe(*args):
        resolved.append(args)
        return original(*args)

    monkeypatch.setattr(managed_state, "resolve_document_content", observe)
    binding = managed_state.prepare_binding(root, document, output=root / "generated").binding

    assert len(resolved) == 1
    assert document == before
    assert repository.read(Path(binding["ir_path"])) == expected_ir
    assert repository.read(Path(binding["canonical_document"])) == document
    assert binding["ir_hash"] == expected_ir["ir_hash"]
    assert binding["graph"] == expected_graph
    assert binding["scientific_content_files"] == managed_state.referenced_files(root, document)
    assert binding["fingerprint"]["files"] == managed_state.input_files(document)
    assert binding["fingerprint"]["artifacts"] == {binding["document"]: expected_ir["ir_hash"]}
    assert len(repository.content_reads) == len(binding["scientific_content_files"])
    assert not Path(binding["document"]).exists()


def test_later_binding_observes_every_content_blob_again(scientific_binding_case):
    repository, root, document, _ = scientific_binding_case
    first = managed_state.prepare_binding(root, document, output=root / "generated").binding
    first_reads = list(repository.content_reads)
    repository.content_reads.clear()
    second = managed_state.prepare_binding(root, document, output=root / "generated").binding
    assert second == first
    assert repository.content_reads == first_reads


@pytest.mark.parametrize("change", ["missing", "different_bytes"])
def test_later_binding_refuses_original_source_change(scientific_binding_case, change):
    _, root, document, _ = scientific_binding_case
    managed_state.prepare_binding(root, document, output=root / "generated")
    source = Path(document["scientific"]["data_sources"][0]["path"])
    if change == "missing":
        source.unlink()
    else:
        source.write_bytes(source.read_bytes().replace(b"0,2", b"0,3"))
    with pytest.raises(EngineError) as failure:
        managed_state.prepare_binding(root, document, output=root / "generated")
    assert failure.value.reason_code == "managed_inputs_changed"


@pytest.mark.parametrize("resource", ["canonical_document", "ir_path"])
def test_existing_immutable_binding_files_cannot_be_replaced(scientific_binding_case, resource):
    repository, root, document, _ = scientific_binding_case
    binding = managed_state.prepare_binding(root, document, output=root / "generated").binding
    path = Path(binding[resource])
    repository.write(path, {"corrupted": True})
    corrupted = path.read_bytes()
    with pytest.raises(EngineError) as failure:
        managed_state.prepare_binding(root, document, output=root / "generated")
    assert failure.value.reason_code == "managed_state_corrupt"
    assert path.read_bytes() == corrupted


def test_invalid_document_does_not_allocate_binding_products(scientific_binding_case):
    _, root, document, _ = scientific_binding_case
    document["unrepresented_field"] = {}
    with pytest.raises(DocumentError):
        managed_state.prepare_binding(root, document, output=root / "generated")
    assert not (root / "models").exists()
    assert not (root / "ir").exists()


def test_later_content_drift_is_not_hidden_by_the_prior_expansion(tmp_path):
    source = request_for_source(tmp_path)
    root = tmp_path / "semantic"
    repository = ObservedRepository()
    with repository_scope(repository, capabilities=COMPATIBILITY_CAPABILITIES):
        document = create_managed_document(source["template_definition"], source["data_binding"], plot_id="fresh-content")
        document = resolved_metadata(document, rule_id=source["rule_id"], executors={})
        document, _ = resolve_science(root, document)
        document = intern_document(root, document, minimum_bytes=2)
        binding = managed_state.prepare_binding(root, document, output=root / "generated").binding
        content = Path(next(iter(binding["scientific_content_files"])))
        before = content.read_bytes()
        content.write_bytes(bytes([before[0] ^ 1]) + before[1:])
        with pytest.raises(EngineError) as failure:
            managed_state.prepare_binding(root, document, output=root / "generated")
        assert failure.value.reason_code == "document_content_corrupt"


def test_missing_resolved_datasets_refuses_before_binding_writes(scientific_binding_case):
    _, root, _, expanded = scientific_binding_case
    del expanded["scientific"]["provenance"]["datasets"]
    document = seal_document(expanded)
    with pytest.raises(KeyError, match="datasets"):
        managed_state.prepare_binding(root, document, output=root / "generated")
    assert not (root / "models").exists()
    assert not (root / "ir").exists()


def test_preview_uses_one_compilation_but_later_ensure_reconstructs(scientific_binding_case, monkeypatch):
    from sciplot_core.plot_engine.managed_backend import ManagedBackend
    from sciplot_core import plot_ir

    _repository, root, document, _expanded = scientific_binding_case
    compiler, observations = plot_ir.compile_document, []

    def compile_once(*args, **kwargs):
        observations.append("compile")
        return compiler(*args, **kwargs)

    monkeypatch.setattr(plot_ir, "compile_document", compile_once)
    backend = object.__new__(ManagedBackend)
    backend.compiler = SimpleNamespace(render_ir=lambda *_: {
        "scientific_audit": {"status": "passed"}, "preview": {"path": "synthetic preview"}})
    monkeypatch.setattr(backend, "_materialize_native", lambda binding, _canonical, ir: (ir, Path(binding["document"])))
    before = deepcopy(document)
    review = backend.preview(document, {"root": str(root), "output": str(root / "generated")},
                             document, [], root / "preview")
    assert observations == ["compile"] and document == before
    binding = review["_managed_binding"]
    expected = _repository.read(Path(binding["ir_path"]))
    assert backend._ensure(binding)[0] == expected
    assert observations == ["compile", "compile"]


@pytest.mark.parametrize("resource", ["canonical", "payload", "source", "ir_identity"])
def test_preview_reobserves_persistence_before_any_native_effect(scientific_binding_case, monkeypatch, resource):
    from sciplot_core.plot_engine import managed_backend

    repository, root, document, _expanded = scientific_binding_case
    prepare = managed_backend.prepare_binding
    expected = "managed_state_corrupt" if resource == "canonical" else "managed_inputs_changed"
    if resource == "ir_identity":
        expected = "managed_ir_conflict"
    if resource == "payload":
        expected = "document_content_corrupt" if managed_state.referenced_files(root, document) else "document_hash_mismatch"

    def corrupt_after_persist(*args, **kwargs):
        prepared = prepare(*args, **kwargs)
        if resource == "ir_identity":
            prepared.ir["ir_hash"] = "0" * 64
        elif resource == "source":
            path = Path(document["scientific"]["data_sources"][0]["path"])
            path.write_bytes(path.read_bytes() + b"changed after persistence\n")
        elif resource == "payload" and managed_state.referenced_files(root, document):
            path = Path(next(iter(managed_state.referenced_files(root, document))))
            content = path.read_bytes()
            path.write_bytes(bytes([content[0] ^ 1]) + content[1:])
        else:
            path = Path(prepared.binding["canonical_document"])
            changed = repository.read(path)
            if resource == "canonical":
                changed["revision"] += 1
            else:
                changed["scientific"]["provenance"]["datasets"]["A"]["columns"]["column:0"]["values"][0] = 123
            repository.write(path, changed)
        return prepared

    monkeypatch.setattr(managed_backend, "prepare_binding", corrupt_after_persist)
    backend = object.__new__(managed_backend.ManagedBackend)
    monkeypatch.setattr(backend, "_materialize_native", lambda *_: pytest.fail("changed persistence reached native compilation"))
    with pytest.raises(ValueError) as failure:
        backend.preview(document, {"root": str(root), "output": str(root / "generated")}, document, [], root / "review")
    assert failure.value.reason_code == expected


def test_existing_model_preserves_literal_json_identity(scientific_binding_case):
    repository, root, document, _expanded = scientific_binding_case
    prepared = managed_state.prepare_binding(root, document, output=root / "generated")
    path = Path(prepared.binding["canonical_document"])
    changed = repository.read(path)
    changed["revision"] = float(changed["revision"])
    assert changed == document
    repository.write(path, changed)
    original = path.read_bytes()
    with pytest.raises(EngineError) as failure:
        managed_state.prepare_binding(root, document, output=root / "generated")
    assert failure.value.reason_code == "managed_state_corrupt" and path.read_bytes() == original
