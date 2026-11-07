"""Future output positions use whole host roots, never source-member evidence."""

import json
from pathlib import Path

import pytest

from sciplot_core.delivery.package_builder import _build_staged_delivery
from sciplot_core.delivery_identity import make_delivery_binding, read_delivery_binding
from sciplot_core.foundation.source_locations import literal_source_path
from sciplot_core.project_store import FileProjectStore, ProjectStoreError, ResourceRoot
from sciplot_core.project_store.runtime import project_runtime
from test_delivery_project_documents import _builder_manifest
from test_project_export_use_case import publication as publication


def _project(tmp_path, *, external=False, finite=False):
    project = tmp_path / "project"
    project.mkdir()
    run, manifest, _ = _builder_manifest(project)
    output = tmp_path / "external" if external else project / "delivery"
    locations = {}
    if external:
        output.mkdir()
        if finite:
            (output / "kept.txt").write_text("finite input grant")
        locations["delivery"] = ResourceRoot(output, ("kept.txt",) if finite else None)
    request = project / "plot_request.json"
    request.write_text(json.dumps({"input": manifest["input"], "delivery_output": str(output)}))
    manifest["request_path"] = str(request)
    store = FileProjectStore(project, locations=locations)
    snapshot = store.snapshot(import_legacy=True)
    return project, output, run, manifest, store, snapshot


def _binding(output, request, namespace):
    return make_delivery_binding(root=output, output_namespace=namespace,
        manifest={"request_path": str(request)},
        documents=[{"path": str(output / "project/figure.vsz"), "delivery_sha256": "a" * 64}])


def test_first_internal_delivery_build_uses_explicit_output_namespace_without_admitting_a_source(tmp_path):
    project, output, run, manifest, store, before = _project(tmp_path)
    assert not output.exists() and not any(name.startswith("delivery/") for name in before["files"])
    with project_runtime(store, generation=before["generation"]):
        with pytest.raises(ProjectStoreError, match="no exact preserved locator"):
            literal_source_path(output)
        with pytest.raises(ProjectStoreError, match="no exact preserved locator"):
            _binding(output, project / "plot_request.json", None)
        stage = tmp_path / "private-stage"
        record = _build_staged_delivery(run, manifest=manifest, delivery_dir=stage,
            final_root=output, output_namespace=project)
        assert record["complete"], record["verification"]
        binding = read_delivery_binding(stage)
        assert binding.root == str(output) and binding.request == str(project / "plot_request.json")
        assert binding.source == manifest["input"]
        with pytest.raises(ProjectStoreError, match="no exact preserved locator"):
            literal_source_path(output)
    assert not output.exists() and store.snapshot()["generation"] == before["generation"]


@pytest.mark.parametrize("external", [False, True], ids=["primary-root", "registered-resource-root"])
def test_future_output_identity_survives_official_cold_move_without_reconnecting_old_paths(tmp_path, external):
    project, output, _run, _manifest, store, before = _project(tmp_path, external=external)
    namespace = output if external else project
    request = project / "plot_request.json"
    with project_runtime(store):
        original = _binding(output, request, namespace)
    bundle = tmp_path / "complete.zip"
    store.export_bundle(bundle)
    project.rename(tmp_path / "offline-project")
    if external:
        output.rename(tmp_path / "offline-delivery")
    moved = FileProjectStore.import_bundle(bundle, tmp_path / "moved")
    current_output = moved.locations["delivery"] if external else moved.root / "delivery"
    current_namespace = current_output if external else moved.root
    generation = moved.snapshot()["generation"]
    with project_runtime(moved):
        current = _binding(current_output, moved.root / "plot_request.json", current_namespace)
        assert current == original
        assert current.root == str(output) and current.request == str(request)
        with pytest.raises(ProjectStoreError, match="no exact preserved locator"):
            literal_source_path(current_output)
    assert not project.exists() and (not output.exists())
    assert moved.snapshot()["generation"] == generation == before["generation"]


@pytest.mark.parametrize("case", ["no-runtime", "foreign-root", "outside-root", "finite-grant"])
def test_output_namespace_cannot_invent_an_identity_or_expand_a_capability(tmp_path, case):
    project, output, _run, _manifest, store, before = _project(tmp_path,
        external=case == "finite-grant", finite=case == "finite-grant")
    request = project / "plot_request.json"
    if case == "no-runtime":
        with pytest.raises(ValueError, match="explicitly selected project capability"):
            _binding(output, request, project)
    else:
        namespace = output if case == "finite-grant" else tmp_path if case == "foreign-root" else project
        target = tmp_path / "outside" if case == "outside-root" else output
        with project_runtime(store):
            with pytest.raises(ValueError):
                _binding(target, request, namespace)
    assert store.snapshot()["generation"] == before["generation"]


@pytest.mark.parametrize("member", ["request", "source"])
@pytest.mark.parametrize("change", ["bytes", "mode"])
def test_output_namespace_does_not_certify_changed_request_or_scientific_members(tmp_path, member, change):
    project, output, _run, manifest, store, before = _project(tmp_path)
    path = project / "plot_request.json" if member == "request" else Path(manifest["input"])
    if change == "bytes":
        path.write_bytes(path.read_bytes() + b" \n")
    else:
        path.chmod(0o600 if path.stat().st_mode & 0o777 != 0o600 else 0o644)
    changed = (path.read_bytes(), path.stat().st_mode)
    with project_runtime(store, generation=before["generation"]):
        with pytest.raises(ValueError, match="registered generation|changed outside"):
            _binding(output, project / "plot_request.json", project)
    assert (path.read_bytes(), path.stat().st_mode) == changed
    assert not output.exists() and store.snapshot()["generation"] == before["generation"]


def test_publication_host_forwards_its_existing_primary_output_namespace(publication):
    from sciplot_core.studio_core.project_export import export_project_document

    project, calls, _ = publication
    result = export_project_document(project_dir=project, formats=["pdf"])
    assert result.ready_to_use
    assert calls[1][1]["delivery_root"] == project / "delivery"
    assert calls[1][1]["delivery_namespace"] == project
