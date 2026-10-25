"""Private external outputs inherit only the host's existing resource grants."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.foundation.source_locations import literal_source_path, resolve_source_path, selected_source_resolver
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ProjectStoreError, ResourceRoot
from sciplot_core.project_store.io import sha
from sciplot_core.project_store.runtime import logical_runtime_resource, project_candidate_runtime, resolve_runtime_output_path
from sciplot_core.project_store.worker_binding import native_runtime_binding, worker_project_runtime


def resource_fixture(tmp_path):
    root = tmp_path / "active"
    root.mkdir()
    (root / "raw").mkdir()
    (root / "raw/input.csv").write_bytes(b"x,y\n1,2\n")
    (root / "state.json").write_bytes(b'{"science":"preserved"}')
    output = tmp_path / "admitted-output"
    output.mkdir()
    (output / "baseline.pdf").write_bytes(b"old audited output")
    (output / "baseline.pdf").chmod(0o640)
    (output / "input.csv").write_bytes(b"sealed external source")
    archive = tmp_path / "archive-parent"
    archive.mkdir()
    (archive / "selected.vsz").write_bytes(b"selected document")
    (archive / "private-sibling.vsz").write_bytes(b"unselected user document")
    store = FileProjectStore(root, locations={"run_exact": output,
        "snapshot": ResourceRoot(archive, ("selected.vsz",))})
    before = store.snapshot(import_legacy=True)
    primary, resources = tmp_path / "private-primary", tmp_path / "private-resources"
    primary.mkdir(mode=0o700)
    resources.mkdir(mode=0o700)
    for name, entry in before["files"].items():
        if name.startswith("@"):
            continue
        target = primary / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(store.read_bytes(name))
        target.chmod(entry["mode"])
    return store, before, primary, resources


@contextmanager
def selected_resource_candidate(tmp_path):
    store, before, primary, resources = resource_fixture(tmp_path)
    with project_candidate_runtime(store, primary, generation=before["generation"], resources_root=resources):
        yield store, before, primary, resources


def test_external_output_maps_to_private_view_and_preserves_exact_source_generation(tmp_path):
    with selected_resource_candidate(tmp_path) as (store, before, primary, resources):
        output = store.locations["run_exact"]
        assert resolve_source_path(output / "baseline.pdf") == resources / "run_exact/baseline.pdf"
        assert (resources / "run_exact/baseline.pdf").stat().st_mode & 0o777 == 0o640
        document = resolve_runtime_output_path(output / "nested/result.pdf")
        assert document == resources / "run_exact/nested/result.pdf"
        document.write_bytes(b"private new output")
        assert resolve_source_path(document, expected_sha256=sha(b"private new output")) == document
        assert literal_source_path(document) == str(output / "nested/result.pdf")
        assert literal_source_path(resources / "run_exact") == str(output)
        assert logical_runtime_resource(document, private_only=True) == "@run_exact/nested/result.pdf"
        assert logical_runtime_resource(output / "nested/result.pdf", private_only=True) is None
        assert logical_runtime_resource(output / "nested/result.pdf") == "@run_exact/nested/result.pdf"
        assert logical_runtime_resource(primary / "state.json", private_only=True) == "state.json"
        assert logical_runtime_resource(store.root / "state.json", private_only=True) is None
        assert not (resources / "snapshot/private-sibling.vsz").exists()
        assert resolve_source_path(store.locations["snapshot"]).is_dir()
        assert store.snapshot() == before and not (output / "nested").exists()
        assert (output / "baseline.pdf").read_bytes() == b"old audited output"
    assert selected_source_resolver() is None and logical_runtime_resource(document) is None


@pytest.mark.parametrize("failure", ["finite-sibling", "finite-new", "finite-parent", "foreign-key", "resources-parent",
    "project-raw", "new-project-raw", "external-input", "new-external-source", "whole-resource-root"])
def test_outputs_cannot_expand_finite_grants_or_overwrite_scientific_inputs(tmp_path, failure):
    with selected_resource_candidate(tmp_path) as (store, _before, primary, resources):
        targets = {"finite-sibling": store.locations["snapshot"] / "private-sibling.vsz",
            "finite-new": resources / "snapshot/new.pdf", "finite-parent": store.locations["snapshot"].parent / "other.pdf",
            "foreign-key": resources / "ungranted/file.pdf", "resources-parent": resources,
            "project-raw": primary / "raw/input.csv", "new-project-raw": primary / "raw/new.csv",
            "external-input": resources / "run_exact/input.csv", "new-external-source": resources / "run_exact/source/new.csv",
            "whole-resource-root": resources / "run_exact"}
        with pytest.raises((ProjectConflict, ProjectStoreError)):
            resolve_runtime_output_path(targets[failure])


@pytest.mark.parametrize("failure", ["source-bytes", "source-mode", "source-uuid", "source-version", "symlink", "hardlink",
    "logical-symlink", "logical-hardlink", "directory-mode", "directory-extra"])
def test_resource_read_guards_preserve_input_identity_and_closed_finite_views(tmp_path, failure):
    with selected_resource_candidate(tmp_path) as (store, before, _primary, resources):
        path = resources / "run_exact/input.csv"
        entry = before["files"]["@run_exact/input.csv"]
        if failure == "source-bytes":
            path.write_bytes(b"changed")
        elif failure in {"source-mode", "directory-mode"}:
            path.chmod(0o700)
        elif failure in {"symlink", "hardlink", "logical-symlink", "logical-hardlink"}:
            path.unlink()
            if failure.endswith("symlink"):
                path.symlink_to(store.locations["run_exact"] / "input.csv")
            else:
                path.hardlink_to(store.locations["run_exact"] / "input.csv")
        elif failure == "directory-extra":
            (resources / "snapshot/private-sibling.vsz").write_bytes(b"ungranted")
            path = resources / "snapshot"
        with pytest.raises((ProjectConflict, ProjectStoreError, OSError)):
            if failure.startswith("logical-"):
                logical_runtime_resource(path, private_only=True)
            else:
                resolve_source_path(path.parent if failure == "directory-mode" else path,
                    source_id="b" * 32 if failure == "source-uuid" else None,
                    expected_sha256="0" * 64 if failure == "source-version" else entry["sha256"] if failure == "source-uuid" else None)


@pytest.mark.parametrize("failure", ["root-symlink", "root-mode", "overlap", "ungranted-key", "foreign-copy"])
def test_host_initialization_never_adopts_foreign_views_or_resource_parent_grants(tmp_path, failure):
    store, _before, primary, resources = resource_fixture(tmp_path)
    if failure == "root-symlink":
        actual = tmp_path / "actual"
        resources.rename(actual)
        resources.symlink_to(actual, target_is_directory=True)
    elif failure == "root-mode":
        resources.chmod(0o755)
    elif failure == "overlap":
        resources = primary
    else:
        key = "ungranted" if failure == "ungranted-key" else "run_exact"
        (resources / key).mkdir(mode=0o700)
        (resources / key / "foreign.pdf").write_bytes(b"cannot adopt")
    with pytest.raises((ProjectConflict, ProjectStoreError)):
        with project_candidate_runtime(store, primary, resources_root=resources):
            pytest.fail("Foreign private resource authority admitted")


@pytest.mark.parametrize("failure", ["container-replaced", "view-replaced", "view-mode", "parent-symlink", "view-symlink", "second-store"])
def test_bound_resource_identity_is_checked_on_each_host_and_worker_access(tmp_path, monkeypatch, failure):
    with selected_resource_candidate(tmp_path) as (store, _before, _primary, resources):
        argv = ["inspect-document-state", str(resources / "run_exact/baseline.pdf")]
        with native_runtime_binding(argv) as reference:
            monkeypatch.setattr(os, "getppid", os.getpid)
            view = resources / "run_exact"
            if failure == "container-replaced":
                resources.rename(tmp_path / "retired-resources")
                resources.mkdir(mode=0o700)
            elif failure == "view-replaced":
                view.rename(resources / "old-run_exact")
                view.mkdir(mode=0o700)
            elif failure == "view-mode":
                view.chmod(0o755)
            elif failure == "parent-symlink":
                resources.rename(tmp_path / "retired-resources")
                resources.symlink_to(tmp_path / "retired-resources", target_is_directory=True)
            elif failure == "view-symlink":
                view.rename(resources / "old-run_exact")
                view.symlink_to(resources / "old-run_exact", target_is_directory=True)
            else:
                (view / ".sciplot_store").mkdir()
            with pytest.raises((ProjectConflict, ProjectStoreError, OSError)):
                resolve_source_path(argv[1])
            with pytest.raises((ProjectConflict, ProjectStoreError, OSError)):
                with worker_project_runtime(reference, argv):
                    pytest.fail("Worker recreated or accepted a replaced resource view")


def test_missing_resources_argument_retains_the_original_primary_only_behavior(tmp_path):
    store, _before, primary, resources = resource_fixture(tmp_path)
    with project_candidate_runtime(store, primary):
        assert not list(resources.iterdir())
        assert logical_runtime_resource(resources / "run_exact/result.pdf", private_only=True) is None
        with pytest.raises(ProjectConflict):
            resolve_runtime_output_path(resources / "run_exact/result.pdf")


def test_cold_registered_resource_mounts_keep_original_literals_and_selected_modes(tmp_path):
    store, before, _primary, _resources = resource_fixture(tmp_path)
    original_output = store.locations["run_exact"]
    bundle = store.export_bundle(tmp_path / "bundle")
    cold = FileProjectStore.import_bundle(bundle, tmp_path / "moved-project")
    store.root.rename(tmp_path / "offline-project")
    original_output.rename(tmp_path / "offline-output")
    store.locations["snapshot"].rename(tmp_path / "offline-archive")
    primary, resources = tmp_path / "cold-primary", tmp_path / "cold-resources"
    primary.mkdir(mode=0o700)
    resources.mkdir(mode=0o700)
    for name, entry in before["files"].items():
        if name.startswith("@"):
            continue
        path = primary / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(cold.read_bytes(name))
        path.chmod(entry["mode"])
    with project_candidate_runtime(cold, primary, resources_root=resources):
        path = resolve_source_path(cold.locations["run_exact"] / "baseline.pdf")
        assert path == resources / "run_exact/baseline.pdf"
        assert path.read_bytes() == b"old audited output" and path.stat().st_mode & 0o777 == 0o640
        assert literal_source_path(path) == str(original_output / "baseline.pdf")
        assert logical_runtime_resource(cold.locations["run_exact"] / "baseline.pdf") == "@run_exact/baseline.pdf"
        assert logical_runtime_resource(cold.locations["run_exact"] / "baseline.pdf", private_only=True) is None
        assert resolve_source_path(original_output / "baseline.pdf") == path


def test_new_explicit_host_output_grant_needs_no_unregistered_old_active_copy(tmp_path):
    store, before, primary, resources = resource_fixture(tmp_path)
    new_output = tmp_path / "new-admitted-output"
    new_output.mkdir()
    locations = {key: ResourceRoot(path, store.location_members[key]) for key, path in store.locations.items()}
    locations["run_new"] = ResourceRoot(new_output)
    admitted = FileProjectStore(store.root, locations=locations)
    with project_candidate_runtime(admitted, primary, resources_root=resources):
        target = resolve_runtime_output_path(new_output / "nested/result.pdf")
        target.write_bytes(b"new candidate only")
        assert literal_source_path(target) == str(new_output / "nested/result.pdf")
        assert logical_runtime_resource(target, private_only=True) == "@run_new/nested/result.pdf"
    assert store.snapshot() == before and not list(new_output.iterdir())


def test_narrow_selected_capability_clones_only_its_exact_members(tmp_path):
    store, before, primary, resources = resource_fixture(tmp_path)
    locations = {key: ResourceRoot(path, store.location_members[key]) for key, path in store.locations.items()}
    locations["run_exact"] = ResourceRoot(store.locations["run_exact"], ("baseline.pdf",))
    selected = FileProjectStore(store.root, locations=locations)
    with project_candidate_runtime(selected, primary, resources_root=resources):
        assert (resources / "run_exact/baseline.pdf").read_bytes() == b"old audited output"
        assert not (resources / "run_exact/input.csv").exists()
        for actual in (resources / "run_exact/input.csv", store.locations["run_exact"] / "input.csv"):
            with pytest.raises(ProjectConflict):
                resolve_source_path(actual)
    assert store.snapshot() == before


def test_finite_original_parent_keeps_primary_and_new_explicit_siblings_separate(tmp_path, monkeypatch):
    from test_project_runtime_capabilities import finite_store
    store, before, archive = finite_store(tmp_path)
    primary, resources = tmp_path / "private-primary", tmp_path / "private-resources"
    primary.mkdir(mode=0o700)
    resources.mkdir(mode=0o700)
    for logical, entry in before["files"].items():
        if logical.startswith("@"):
            continue
        target = primary / logical
        target.write_bytes(store.read_bytes(logical))
        target.chmod(entry["mode"])
    incoming = tmp_path / "explicit-new.csv"
    incoming.write_bytes(b"new separately admitted source")
    with project_candidate_runtime(store, primary, resources_root=resources):
        assert resolve_source_path(store.root / "source.csv") == primary / "source.csv"
        assert resolve_source_path(archive) == resources / "snapshot/project.zip"
        assert resolve_source_path(incoming) == incoming
        assert literal_source_path(incoming) == str(incoming)
        assert logical_runtime_resource(incoming) is None
        with pytest.raises(ProjectConflict):
            resolve_runtime_output_path(incoming)
        with pytest.raises(ProjectConflict):
            resolve_source_path(resources / "snapshot/explicit-new.csv")
        argv = ["inspect-document-state", str(archive)]
        with native_runtime_binding(argv) as reference:
            monkeypatch.setattr(os, "getppid", os.getpid)
            with worker_project_runtime(reference, argv):
                assert resolve_source_path(archive) == resources / "snapshot/project.zip"
                assert resolve_source_path(store.root / "source.csv") == primary / "source.csv"
                assert resolve_source_path(incoming) == incoming
    assert store.snapshot() == before


@pytest.mark.parametrize("failure", ["unknown-key", "missing-key", "unknown-field", "view-identity", "root-identity", "missing-view", "argv", "parent"])
def test_worker_resource_binding_is_closed_and_cannot_mint_or_recreate_views(tmp_path, monkeypatch, failure):
    with selected_resource_candidate(tmp_path) as (_store, _before, _primary, resources):
        argv = ["inspect-document-state", str(resources / "run_exact/baseline.pdf")]
        with native_runtime_binding(argv) as reference:
            monkeypatch.setattr(os, "getppid", os.getpid)
            path = Path(reference["path"])
            value = json.loads(path.read_bytes())
            cap = value["project"]["candidate"]["resources"]
            if failure == "unknown-key":
                cap["views"]["unknown"] = cap["views"]["run_exact"]
            elif failure == "missing-key":
                del cap["views"]["snapshot"]
            elif failure == "unknown-field":
                cap["allow_parent"] = True
            elif failure == "view-identity":
                cap["views"]["run_exact"]["inode"] += 1
            elif failure == "root-identity":
                cap["inode"] += 1
            elif failure == "missing-view":
                (resources / "run_exact").rename(resources / "retired")
            elif failure == "parent":
                value["parent_pid"] += 1
            else:
                argv.append("unbound")
            data = json.dumps(value).encode()
            path.chmod(0o600)
            path.write_bytes(data)
            reference["sha256"] = sha(data)
            with pytest.raises((ProjectConflict, ProjectStoreError, OSError)):
                with worker_project_runtime(reference, argv):
                    pytest.fail("Unbound resource capability admitted")


@pytest.mark.comprehensive
def test_actual_child_reads_only_host_initialized_resource_view_and_retains_literal(tmp_path):
    with selected_resource_candidate(tmp_path) as (store, before, _primary, resources):
        artifact = resolve_runtime_output_path(store.locations["run_exact"] / "nested/result.pdf")
        artifact.write_bytes(b"private audited candidate")
        argv = ["inspect-document-state", str(artifact)]
        script = """import json,sys
from sciplot_core.project_store.worker_binding import worker_project_runtime
from sciplot_core.foundation.source_locations import resolve_source_path,literal_source_path,selected_source_resolver
from sciplot_core.project_store.runtime import logical_runtime_resource
with worker_project_runtime(json.loads(sys.argv[1]),json.loads(sys.argv[2])):
 path=resolve_source_path(sys.argv[3]);print(json.dumps({'data':path.read_text(),'literal':literal_source_path(path),'logical':logical_runtime_resource(path,private_only=True)}))
assert selected_source_resolver() is None
"""
        with native_runtime_binding(argv) as reference:
            child = subprocess.run([sys.executable, "-c", script, json.dumps(reference), json.dumps(argv), str(artifact)],
                text=True, capture_output=True, check=True, timeout=30)
        assert json.loads(child.stdout) == {"data": "private audited candidate",
            "literal": str(store.locations["run_exact"] / "nested/result.pdf"), "logical": "@run_exact/nested/result.pdf"}
        assert store.snapshot() == before and not (store.locations["run_exact"] / "nested").exists()
