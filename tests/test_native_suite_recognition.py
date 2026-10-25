"""A shared store alone cannot select NativeSuite or discard its saved proof."""
import json

import pytest

from sciplot_core.project_commands import ProjectCommand
from sciplot_core.project_store import FileProjectStore, ProjectStoreError
from sciplot_core.project_store.io import digest, sha
from sciplot_core.workflow.native_suite_objects import resolve_native_object
from sciplot_core.workflow.native_suite_runtime import current_store, read_bound_store, suite_runtime

from test_native_suite_project_commands import bound as bound


def recorded_project(tmp_path, *, adapter=None, workspace=False):
    root, delivery = tmp_path / "project", tmp_path / "delivery"
    root.mkdir()
    delivery.mkdir()
    target = root / "document.vsz"
    target.write_bytes(b"generic saved native authority")
    request_path = root / "request.json"
    request = {"out": str(delivery), "prepared_plan": str(tmp_path / "prepared.json")}
    request_path.write_text(json.dumps(request))
    store = FileProjectStore(root, locations={"delivery": delivery})
    snapshot = store.snapshot(import_legacy=True)
    command = None
    if adapter == "lowlevel":
        store.reserve("ordinary-lowlevel", "ordinary-digest", expected_generation=snapshot["generation"],
            read_set={}, write_set=[], metadata={"kind": "synthetic", "key": "domain-owned-lowlevel-label"})
    elif adapter is not None:
        command = ProjectCommand.create("native_create", "owned-create", project_id=snapshot["project_id"],
            expected_generation=snapshot["generation"], read_set={}, write_set=[], request={"adapter": adapter,
                "request_file": {"path": str(request_path), "sha256": sha(request_path.read_bytes())},
                "request": request, "binding": {"delivery": str(delivery)}})
        store.reserve(command.key, command.command_digest, expected_generation=command.expected_generation,
            read_set={}, write_set=[], metadata=command.to_payload())
        store.mark_applying(command.key, command.command_digest)
        if workspace:
            store.claim_native_workspace(command.key, command.command_digest, "native_suite_create_v1")
    return store, target, request_path, command


@pytest.mark.parametrize("adapter", [None, "managed_document", "legacy_semantic_import", "lowlevel"])
def test_real_generic_store_is_not_a_pending_native_suite_and_does_not_repair(tmp_path, monkeypatch, adapter):
    store, target, _request, _command = recorded_project(tmp_path, adapter=adapter)
    head = (store.root / ".sciplot_store/head.json").read_bytes()
    native = target.read_bytes()
    monkeypatch.setattr(FileProjectStore, "recover", lambda *_a: pytest.fail("Non-suite selection cannot repair a project"))
    assert read_bound_store(target) is None
    assert resolve_native_object(target, repair=True) is None
    with suite_runtime(target, repair=True):
        assert current_store() is None
    assert (store.root / ".sciplot_store/head.json").read_bytes() == head and target.read_bytes() == native


@pytest.mark.parametrize("adapter,workspace", [("prepared_native_suite", False), ("analysis_native_suite", True), ("foreign_adapter", True)])
def test_only_admitted_fixed_suite_or_verified_native_workspace_proof_selects_pending(tmp_path, adapter, workspace):
    store, target, _request, _command = recorded_project(tmp_path, adapter=adapter, workspace=workspace)
    before = (store.root / ".sciplot_store/head.json").read_bytes()
    with pytest.raises(ValueError, match="Pending native creation"):
        read_bound_store(target)
    assert (store.root / ".sciplot_store/head.json").read_bytes() == before


def test_exact_prepared_pending_request_retains_its_existing_bound_continuation(tmp_path):
    store, _target, request, _command = recorded_project(tmp_path, adapter="prepared_native_suite", workspace=True)
    selected = read_bound_store(request, role="prepared_request")
    assert selected is not None and selected.root == store.root and selected.locations == store.locations


@pytest.mark.parametrize("role", ["native", "prepared_request"])
def test_external_deletion_of_registered_suite_never_becomes_generic_or_fresh_pending(bound, role):
    workspace, delivery, *_ = bound
    FileProjectStore(workspace, locations={"delivery": delivery}).snapshot(import_legacy=True)
    manifest = workspace / "suite.json"
    manifest.unlink()
    with pytest.raises(ValueError, match="registered NativeSuite manifest is missing"):
        read_bound_store(workspace, role=role)
    assert not manifest.exists()


@pytest.mark.parametrize("damage", ["metadata-digest", "metadata-kind", "metadata-request", "workspace-marker", "record-json"])
def test_damaged_pending_records_are_refused_without_falling_through_to_generic(tmp_path, damage):
    store, target, _request, command = recorded_project(tmp_path, adapter="prepared_native_suite", workspace=True)
    path = store.root / ".sciplot_store/commands" / (digest(command.key) + ".json")
    value = json.loads(path.read_bytes())
    if damage == "workspace-marker":
        marker = store.root / ".sciplot_store/native_work" / digest(command.key) / "binding.json"
        marker.write_text("{}")
    elif damage == "record-json":
        path.write_text("{broken")
    else:
        if damage == "metadata-digest":
            value["metadata"]["request"]["request"]["out"] = "changed"
        elif damage == "metadata-kind":
            value["metadata"]["kind"] = "style"
        else:
            value["metadata"]["request"] = []
        path.write_text(json.dumps(value))
    with pytest.raises((ValueError, ProjectStoreError)):
        read_bound_store(target)


@pytest.mark.parametrize("damage", ["adapter-before-workspace", "typed-version-before-workspace"])
def test_typed_admission_cannot_be_hidden_by_corrupting_its_suite_tag(tmp_path, damage):
    store, target, _request, command = recorded_project(tmp_path, adapter="prepared_native_suite")
    path = store.root / ".sciplot_store/commands" / (digest(command.key) + ".json")
    record = json.loads(path.read_bytes())
    record["metadata"]["request"]["adapter"] = "unrelated-generic-label"
    if damage == "typed-version-before-workspace":
        record["metadata"]["version"] = 2
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        read_bound_store(target)
