"""Real general plotting and Studio preparation share one project publication."""

import json
import subprocess
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.project_publication_commands import _publication_store
from sciplot_core.studio_core.registry_state import _veusz_spec_path
from sciplot_core.studio_core.studio_prepare import prepare_studio_document
from sciplot_core.workflow.request_run import run_request


@pytest.mark.comprehensive
def test_general_run_publishes_native_delivery_and_matching_project_then_reopens(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "source").mkdir(parents=True)
    source = project / "source/data.csv"
    source.write_bytes(b"x,y\n0,1\n1,2\n2,4\n")
    source_before = source.read_bytes(), source.stat().st_mtime_ns
    request = project / "plot_request.json"
    request.write_text(json.dumps({"input": "source/data.csv", "template": "curve",
        "output": str(project / "runs/run_001"), "exports": ["pdf", "tiff_300"]}))
    (project / "intake_manifest.json").write_text(json.dumps({"kind": "sciplot_intake_project",
        "version": 1, "project_slug": "project"}))
    store = _publication_store(project)
    before = store.snapshot(import_legacy=True)
    classification = []
    observed_qa = []
    from sciplot_core.workflow import request_publish

    actual_qa = request_publish.run_qa
    def record_actual_qa(*args, **kwargs):
        observed = actual_qa(*args, **kwargs)
        observed_qa.append(deepcopy(observed))
        return observed
    monkeypatch.setattr(request_publish, "run_qa", record_actual_qa)

    def explicit_direct_source(path, **kwargs):
        classification.append(path)
        return {"semantic_family": "unknown", "rule_id": None, "confidence": 0,
                "needs_ai_intervention": True}

    try:
        result = run_request(request, _classifier=explicit_direct_source)
    except subprocess.CalledProcessError as exc:
        pytest.fail(f"native child exit={exc.returncode}: {exc.stderr}", pytrace=False)
    after = store.snapshot()
    assert len(classification) == 1  # Explicit template rendering needs no AI decision.
    assert after["sequence"] == before["sequence"] + 1
    assert after["outside_changes"] == {}
    assert result["output"] == str(project / "runs/run_001")
    assert result["request_path"] == str(request)
    for field in ("transform_ledger", "publication_intent", "request", "source_request", "raw_archive"):
        assert "sciplot-studio-candidate-" not in json.dumps(result.get(field)), field
    assert result["qa"] == observed_qa[0]  # Preserve the actual inspected paths and observations.
    study = result["study_model"]
    assert study["run"]["output"] == str(project / "runs/run_001")
    assert study["run"]["qa"] == observed_qa[0]
    for artifact in study["run"]["figure_artifacts"]:
        assert Path(artifact["path"]).is_file()
    assert (source.read_bytes(), source.stat().st_mtime_ns) == source_before
    native = project / "studio/document.vsz"
    native_before = file_sha256(native), native.stat().st_mtime_ns
    with zipfile.ZipFile(tmp_path / "project.zip") as archive:
        assert archive.read("project/studio/document.vsz") == native.read_bytes()
        assert archive.read("project/intake_manifest.json") == (project / "intake_manifest.json").read_bytes()
        assert archive.read("project/source/data.csv") == source_before[0]
    saved = json.loads(request.read_text())
    assert saved["input"] == "source/data.csv"
    assert list(project.rglob(".sciplot_store")) == [project / ".sciplot_store"]
    terminal = json.loads((project / "runs/run_001/figures/_veusz/single/plot_request.json").read_text())
    assert terminal["input"] == str(source)
    spec = json.loads(_veusz_spec_path(native).read_text())
    assert "sciplot-studio-candidate-" not in json.dumps(spec)
    try:
        reopened = prepare_studio_document(project)
    except subprocess.CalledProcessError as exc:
        pytest.fail(f"reopen child exit={exc.returncode}: {exc.stderr}", pytrace=False)
    assert reopened["preserved_existing_document"] is True
    assert (file_sha256(native), native.stat().st_mtime_ns) == native_before
    assert (source.read_bytes(), source.stat().st_mtime_ns) == source_before
    assert not (project / "studio/.sciplot_store").exists()
