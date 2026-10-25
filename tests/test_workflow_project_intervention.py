"""Known pre-render repair evidence survives without replacing a saved figure."""

from functools import partial
import json

import pytest

from sciplot_core.project_store import FileProjectStore
from sciplot_core.workflow.one_step_entry import run_one_step
from sciplot_core.workflow.request_run import run_request


def test_existing_project_keeps_new_intervention_and_previous_usable_generation(tmp_path, monkeypatch):
    project = tmp_path / "outputs" / "example"
    (project / "studio").mkdir(parents=True)
    source = project / "source.csv"
    source.write_bytes(b"x,y\n0,1\n1,2\n2,4\n")
    request = project / "plot_request.json"
    request.write_text(json.dumps({"input": "source.csv", "template": "curve",
                                   "output": str(project / "runs/run_001")}))
    native = project / "studio/document.vsz"
    native.write_bytes(b"previous user-controlled native")
    (project / "runs/run_001").mkdir(parents=True)
    old_manifest = project / "runs/run_001/manifest.json"
    old_manifest.write_text('{"state":"ready"}')
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    protected = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (source, request, native, old_manifest)}
    calls = []

    def unknown(path, **kwargs):
        calls.append(path)
        return {"semantic_family": "unknown", "rule_id": None, "confidence": 0,
                "needs_ai_intervention": True}

    def forbidden(*args, **kwargs):
        pytest.fail("A pre-render intervention must not invoke native rendering")

    monkeypatch.setattr("sciplot_core.workflow.request_run.execute_request_render", forbidden)
    result = run_one_step(source, output_root=tmp_path / "outputs", project_name="example",
                          _request_runner=partial(run_request, _classifier=unknown))
    run = project / "runs/run_002"
    assert len(calls) == 1
    assert result["run_output"] == str(run)
    assert result["one_step"]["intervention_package"]["required"] is True
    assert result["one_step"]["render_request"]["path"] == str(request)
    assert result["one_step"]["source_package"]["source"] == str(source)
    assert result["one_step"]["project"] == project.name
    intervention = json.loads((run / "intervention_request.json").read_text())
    cleanup = json.loads((run / "assisted_cleanup_request.json").read_text())
    assert intervention["input"] == cleanup["raw_input"]["path"] == str(source)
    assert intervention["output"] == cleanup["output_dir"] == str(run)
    assert cleanup["intervention_request"] == str(run / "intervention_request.json")
    assert (run / "raw/source.csv").read_bytes() == source.read_bytes()
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in protected} == protected
    after = store.snapshot()
    assert after["sequence"] == before["sequence"] + 1
    assert after["projection_status"] == "current"
    assert after["outside_changes"] == {}
    assert not any("sciplot-studio-candidate-" in (run / name).read_text()
                   for name in ("one_step_status.json", "intervention_request.json", "assisted_cleanup_request.json"))
