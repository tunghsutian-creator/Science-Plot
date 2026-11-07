"""Delivery identity is inert data; legacy shells are strict read-only inputs."""

import json
from dataclasses import replace

import pytest

from sciplot_core.delivery_identity import (
    DeliveryBinding, delivery_identity_path,
    inspect_delivery_identity, read_delivery_binding, write_delivery_identity,
)
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.delivery_target import resolve_delivery_target
from sciplot_core.workflow.project_results import project_workflow_result
from test_delivery_project_continuation import _linked_delivery


def test_current_identity_continues_the_same_owner_and_checks_visible_edits(tmp_path, monkeypatch):
    root, project, canonical, launcher = _linked_delivery(tmp_path, multiple=True)
    old = read_delivery_binding(root)
    assert old is not None
    launcher.unlink()
    identity = write_delivery_identity(root, binding=old)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert identity.stat().st_mode & 0o111 == 0
    assert inspect_delivery_identity(root)["ready"] is True
    expected = {"mode": "project", "project_dir": project, "request": project / "plot_request.json"}
    assert resolve_delivery_target(root) == resolve_delivery_target(identity) == expected
    assert {path: path.read_bytes() for path in before} == before
    visible = root / "project/secondary.vsz"
    visible.write_bytes(b"user's separate native edit")
    with pytest.raises(ValueError, match="skip these edits"):
        resolve_delivery_target(root)
    assert visible.read_bytes() == b"user's separate native edit"
    assert canonical.read_bytes() == b"canonical Veusz project"


@pytest.mark.parametrize("change", ["copy", "move", "missing_project"])
def test_inert_delivery_cannot_reattach_a_copied_moved_or_orphan_snapshot(tmp_path, change):
    import shutil

    root, project, _, launcher = _linked_delivery(tmp_path, multiple=True)
    binding = read_delivery_binding(root)
    launcher.unlink()
    write_delivery_identity(root, binding=binding)
    if change == "missing_project":
        shutil.rmtree(project)
    else:
        moved = tmp_path / "elsewhere"
        if change == "copy":
            shutil.copytree(root, moved)
        else:
            root.rename(moved)
        root = moved
    assert resolve_delivery_target(root) == {"mode": "vsz", "document": root / "project/primary.vsz"}


@pytest.mark.parametrize("mutation", [
    "kind", "version", "boolean_version", "unknown", "relative_root",
    "missing_source", "primary", "digest", "escape", "non_document", "bad_documents",
])
def test_present_invalid_record_never_falls_back_to_an_otherwise_valid_legacy_shell(tmp_path, mutation):
    root, _, _, launcher = _linked_delivery(tmp_path)
    binding = read_delivery_binding(root)
    assert binding is not None
    identity = write_delivery_identity(root, binding=binding)
    value = json.loads(identity.read_text())
    if mutation == "kind":
        value["kind"] = "foreign"
    elif mutation == "version":
        value["version"] = 2
    elif mutation == "boolean_version":
        value["version"] = True
    elif mutation == "unknown":
        value["grant"] = True
    elif mutation == "relative_root":
        value["binding"]["root"] = "."
    elif mutation == "missing_source":
        value["binding"]["source"] = None
    elif mutation == "primary":
        value["binding"]["primary"] = "foreign.vsz"
    elif mutation == "digest":
        value["binding"]["documents"]["primary.vsz"] = "hash-is-not-origin"
    elif mutation == "escape":
        value["binding"]["documents"] = {"../foreign.vsz": "0" * 64}
    elif mutation == "non_document":
        value["binding"]["documents"] = {"image.pdf": "0" * 64}
    else:
        value["binding"]["documents"] = []
    identity.write_text(json.dumps(value))
    old = launcher.read_bytes()
    with pytest.raises(ValueError):
        read_delivery_binding(root)
    assert delivery_identity_path(root) == identity
    assert inspect_delivery_identity(root)["ready"] is False
    assert launcher.read_bytes() == old


def test_inert_identity_rejects_symlink_and_legacy_read_requires_complete_shell(tmp_path):
    root, _, _, launcher = _linked_delivery(tmp_path)
    old = read_delivery_binding(root)
    assert old is not None
    target = tmp_path / "outside.json"
    identity = write_delivery_identity(root, binding=old)
    identity.rename(target)
    identity.symlink_to(target)
    with pytest.raises(ValueError, match="non-symlink"):
        read_delivery_binding(root)
    identity.unlink()
    assert read_delivery_binding(root) == old
    launcher.write_text("#!/bin/zsh\nexit 0\n" + launcher.read_text().splitlines()[-1] + "\n")
    with pytest.raises(ValueError, match="not a valid SciPlot launcher"):
        read_delivery_binding(root)


def test_new_identity_is_the_only_authority_when_a_legacy_artifact_is_also_present(tmp_path):
    root, _, _, _ = _linked_delivery(tmp_path)
    old = read_delivery_binding(root)
    assert old is not None
    current = replace(old, root=str(tmp_path / "different-root"))
    write_delivery_identity(root, binding=current)
    assert read_delivery_binding(root) == current
    assert resolve_delivery_target(root)["mode"] == "vsz"


def test_new_binding_has_no_science_or_permission_claim(tmp_path):
    root = tmp_path / "package"
    root.mkdir()
    binding = DeliveryBinding(str(root), None, None, "a.vsz", (("a.vsz", "0" * 64),))
    identity = write_delivery_identity(root, binding=binding)
    assert set(json.loads(identity.read_text())) == {"kind", "version", "binding"}
    assert read_delivery_binding(root) == binding
    assert not (root / "Open_in_Veusz.command").exists()
    assert file_sha256(identity) == inspect_delivery_identity(root)["content_sha256"]


def test_closed_workflow_delivery_projection_does_not_rewrite_scientific_source_fields(tmp_path):
    private, canonical = tmp_path / "private", tmp_path / "canonical"
    physical = str(private / "delivery")
    source = str(private / "source.csv")
    payload = {
        "request": {"input": source}, "source_binding": {"source": source},
        "delivery_package": {
            "path": physical, "identity": physical + "/SciPlot_delivery.json",
            "identity_contract": {"path": physical + "/SciPlot_delivery.json"},
            "open_in_veusz": physical + "/Open_in_Veusz.command",
            "open_in_sciplot": physical + "/Open_in_SciPlot.command",
            "data_dir": physical + "/data", "project_file": physical + "/project/a.vsz",
            "editable": physical + "/project",
            "project_documents": [{"path": physical + "/project/a.vsz", "source": str(private / "run/a.vsz")}],
            "data_csvs": [{"path": physical + "/data/a.csv", "source": str(private / "run/a.csv")}],
            "artifacts": [{"path": physical + "/SciPlot_delivery.json"}],
        },
    }

    def logical(path):
        return str(canonical / path[len(str(private)) + 1:]) if path.startswith(str(private) + "/") else path

    result = project_workflow_result(payload, logical)
    assert result["request"] == payload["request"]
    assert result["source_binding"] == payload["source_binding"]
    assert result["delivery_package"]["identity"] == str(canonical / "delivery/SciPlot_delivery.json")
    assert all(str(private) not in json.dumps(item) for item in result["delivery_package"].values())
    assert payload["delivery_package"]["path"] == physical


def test_v7_identity_uses_current_physical_delivery_not_a_readonly_source_cache(tmp_path):
    from sciplot_core.project_store.runtime import project_runtime, projected_runtime_directory, resolve_runtime_path
    from sciplot_core.project_store.errors import ProjectStoreError
    from test_project_delivery_runtime import _project_and_delivery

    project, delivery, store = _project_and_delivery(tmp_path, legacy_identity=False)
    with project_runtime(store):
        cache = resolve_runtime_path(delivery)
        assert cache != delivery and (cache / "SciPlot_delivery.json").read_bytes() == (delivery / "SciPlot_delivery.json").read_bytes()
        assert projected_runtime_directory(delivery) == delivery
        assert read_delivery_binding(delivery) is not None
        with pytest.raises(ProjectStoreError, match="source cache cannot prove"):
            read_delivery_binding(cache)


@pytest.mark.parametrize("internal", [False, True])
def test_cold_import_keeps_literal_identity_and_observes_only_current_physical_files(tmp_path, internal):
    from sciplot_core.delivery_identity import make_delivery_binding
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.studio_core.project_query_paths import bound_delivery_project
    from test_project_delivery_runtime import _project_and_delivery

    project, delivery, store = _project_and_delivery(tmp_path, internal=internal, legacy_identity=False, bind_internal=internal)
    original = read_delivery_binding(delivery)
    assert original is not None
    bundle = tmp_path / "whole-project.zip"
    store.export_bundle(bundle)
    project.rename(tmp_path / "offline-project")
    if not internal:
        delivery.rename(tmp_path / "offline-delivery")
    moved = FileProjectStore.import_bundle(bundle, tmp_path / "moved")
    physical = moved.root / "delivery" if internal else moved.locations["delivery"]
    generation = moved.snapshot()["generation"]
    with project_runtime(moved):
        assert read_delivery_binding(physical) == original
        if internal:
            from sciplot_core.project_store.errors import ProjectStoreError
            with pytest.raises(ProjectStoreError, match="exact bound physical resource root"):
                bound_delivery_project(physical)
        else:
            assert bound_delivery_project(physical) == moved.root
        # A future export uses the same literal authority despite current IO at
        # the moved roots; it cannot replace historical origin with a new hash.
        rebuilt = make_delivery_binding(root=physical,
            manifest={"request_path": str(moved.root / "plot_request.json")},
            documents=[{"path": str(physical / "project" / name), "delivery_sha256": digest}
                       for name, digest in original.documents])
        assert rebuilt == original
    assert moved.snapshot()["generation"] == generation
