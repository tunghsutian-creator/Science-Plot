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


@pytest.mark.comprehensive
def test_same_filename_changed_script_invalidates_only_dependent_managed_plot(tmp_path):
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
