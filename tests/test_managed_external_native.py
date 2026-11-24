"""Fixed-file scientific execution is content-bound through the public engine."""

import json
from pathlib import Path
import shutil
import sys

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_transforms import ExternalExecutor
from managed_plot_helpers import patch, request_for_source
from sciplot_core.host_grants import EXECUTE_TRANSFORM, HostRegistry, SourceScope, using_host_registry


@pytest.fixture
def trusted_host(tmp_path):
    registry = HostRegistry(tmp_path.resolve() / "explicit-host/grants.json")
    with using_host_registry(registry):
        yield registry


@pytest.mark.comprehensive
def test_same_filename_changed_script_invalidates_only_dependent_managed_plot(tmp_path, trusted_host):
    request = request_for_source(tmp_path)
    script = tmp_path / "scientific_pipeline.py"
    shutil.copyfile(REPO_ROOT / "tests/fixtures/managed_normalize_executor.py", script)
    parameters = {"type": "object", "properties": {"factor": {"type": "number"}},
                  "required": ["factor"], "additionalProperties": False}
    executor = ExternalExecutor(Path(sys.executable), script, parameters)
    request["scientific_executors"] = {"fixed-normalizer": executor.to_dict("fixed-normalizer")}
    request["data_binding"]["transforms"] = [{"id": "external-A", "kind": "external", "inputs": ["A"],
        "output": "A-normalized", "parameters": {"factor": .1}, "executor": executor.descriptor("fixed-normalizer"),
        "determinism": "deterministic"}]
    scope = SourceScope.local_file("A", Path(request["data_binding"]["data_sources"][0]["path"]))
    trusted_host.grant("fixed-normalizer", executor.to_dict("fixed-normalizer"), [scope], action=EXECUTE_TRANSFORM)
    service = PlotService()
    try:
        created = service.create(request)
        assert created["ready_to_use"], created
        root = Path(created["plot"])
        unrelated = service.create(request_for_source(tmp_path, "B"))
        unrelated_root = Path(unrelated["plot"])
        before = service.describe(root)
        old_registration = request["scientific_executors"]["fixed-normalizer"]
        script.write_text(script.read_text() + "\n# Scientific pipeline version two, same path.\n")
        changed = service.describe(root)
        assert {"transform:external-A", "compile", "render", "export"} <= set(changed["dependencies"]["invalidated"])
        assert "source:A" not in changed["dependencies"]["invalidated"]
        assert service.describe(unrelated_root)["status"] == "current"
        registration = executor.to_dict("fixed-normalizer")
        assert registration["identity"]["content_hash"] != old_registration["identity"]["content_hash"]
        trusted_host.grant("fixed-normalizer", registration, [scope], action=EXECUTE_TRANSFORM)
        updated = service.patch(root, patch(before, "executor-version-two", "executor.registration", registration,
                                            "executor:fixed-normalizer", scientific=True))
        assert updated["ready_to_use"] and updated["scientific_hash"] != before["scientific_hash"], updated
        assert updated["transform_execution"]["executed"] == ["external-A"]
        assert service.describe(unrelated_root)["scientific_hash"] == unrelated["scientific_hash"]
        replayed = service.patch(root, patch(before, "executor-version-two", "executor.registration", registration,
                                             "executor:fixed-normalizer", scientific=True))
        assert replayed["replayed"] and replayed["revision"] == updated["revision"]
        evidence = REPO_ROOT / ".tmp_verify/managed_architecture_20261008/external_executor_acceptance.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps({"created": created, "old_executor": old_registration,
            "dirty": changed, "new_executor": registration, "updated": updated,
            "replayed": replayed, "unrelated_plot_unchanged": True}, ensure_ascii=False, indent=2))
    finally:
        service.close()


@pytest.mark.comprehensive
def test_public_executor_store_creation_preserves_grant_and_unknown_outcome(tmp_path, trusted_host, monkeypatch):
    from copy import deepcopy

    from sciplot_core.plot_engine.storage import digest
    from sciplot_core.plot_transforms import execution
    from sciplot_core.project_store import FileProjectStore

    source_dir = tmp_path / "originals"
    source_dir.mkdir()
    request = {**request_for_source(source_dir), "out": str(tmp_path / "visible")}
    script = tmp_path / "scientific_pipeline.py"
    shutil.copyfile(REPO_ROOT / "tests/fixtures/managed_normalize_executor.py", script)
    schema = {"type": "object", "properties": {"factor": {"type": "number"}},
              "required": ["factor"], "additionalProperties": False}
    executor = ExternalExecutor(Path(sys.executable), script, schema)
    registration = executor.to_dict("fixed-normalizer")
    request["scientific_executors"] = {"fixed-normalizer": registration}
    request["data_binding"]["transforms"] = [{"id": "external-A", "kind": "external", "inputs": ["A"],
        "output": "A-normalized", "parameters": {"factor": .1}, "executor": executor.descriptor("fixed-normalizer"),
        "determinism": "deterministic"}]
    source = Path(request["data_binding"]["data_sources"][0]["path"])
    outer = source_dir / ".sciplot_documents" / "managed"
    store_root = outer / digest(request["idempotency_key"])
    launches = []

    real_execute = execution.execute_node

    def execute(node, *args, **kwargs):
        result = real_execute(node, *args, **kwargs)
        if node["kind"] == "external":
            launches.append(node["id"])
        return result

    monkeypatch.setattr(execution, "execute_node", execute)
    service = PlotService(read_only_legacy=True)
    try:
        with pytest.raises(ValueError) as ungranted:
            service.create(request)
        assert ungranted.value.reason_code == "host_executor_ungranted"
        assert not store_root.exists() and not Path(request["out"]).exists() and not launches
        trusted_host.grant("fixed-normalizer", registration, [SourceScope.local_file("A", source)], action=EXECUTE_TRANSFORM)
        created = service.create(request)
        assert created["ready_to_use"] and Path(created["plot"]).parent.parent == store_root
        assert launches == ["external-A"]
        files = FileProjectStore(store_root).snapshot()["files"]
        assert sum(name.endswith(".started.json") for name in files) == 1
        assert sum(name.endswith(".result.json") for name in files) == 1
        assert not any(name.endswith("grants.json") for name in files)
        assert service.create(request)["ready_to_use"] and launches == ["external-A"]

        interrupted = {**deepcopy(request), "idempotency_key": "worker-reply-lost",
                       "out": str(tmp_path / "interrupted")}
        pending_store = outer / digest(interrupted["idempotency_key"])

        def lose_result(node, *args, **kwargs):
            result = execute(node, *args, **kwargs)
            if node["kind"] == "external":
                raise RuntimeError("the fixed worker finished but its reply was lost")
            return result

        monkeypatch.setattr(execution, "execute_node", lose_result)
        with pytest.raises(RuntimeError, match="reply was lost"):
            service.create(interrupted)
        pending = FileProjectStore(pending_store).snapshot()["files"]
        assert sum(name.endswith(".started.json") for name in pending) == 1
        assert not any(name.endswith(".result.json") for name in pending)
        assert not Path(interrupted["out"]).exists()
    finally:
        service.close()

    cold = PlotService(read_only_legacy=True)
    try:
        with pytest.raises(ValueError) as unknown:
            cold.create(interrupted)
        assert unknown.value.reason_code == "external_transform_outcome_unknown"
        assert launches == ["external-A", "external-A"]
        assert not Path(interrupted["out"]).exists()
    finally:
        cold.close()
