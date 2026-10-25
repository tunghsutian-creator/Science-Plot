"""One-step admission must precede all writes to a recognized project."""

import json

import pytest

from sciplot_core.project_store import FileProjectStore
from sciplot_core.workflow.one_step_entry import run_one_step


def test_existing_project_one_step_carries_new_intent_without_overwriting_request_or_creating_run(tmp_path):
    source = tmp_path / "source.csv"
    source.write_bytes(b"x,y\n1,2\n")
    root = tmp_path / "outputs" / "example"
    root.mkdir(parents=True)
    request = root / "plot_request.json"
    request.write_text(json.dumps({"input": "original.csv", "output": str(root / "runs/run_001")}))
    (root / "original.csv").write_bytes(b"old source")
    (root / "runs/run_001").mkdir(parents=True)
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    original = request.read_bytes(), request.stat().st_mtime_ns
    calls = []
    def admission(path, **kwargs):
        assert path == request
        assert (request.read_bytes(), request.stat().st_mtime_ns) == original
        assert not (root / "runs/run_002").exists()
        assert kwargs["_incoming_request"]["input"] == str(source)
        assert kwargs["_incoming_request"]["output"] == str(root / "runs/run_002")
        calls.append(path)
        raise ValueError("rejected before private preparation")
    with pytest.raises(ValueError, match="rejected before private preparation"):
        run_one_step(source, output_root=tmp_path / "outputs", project_name="example", _request_runner=admission)
    assert calls == [request]
    assert (request.read_bytes(), request.stat().st_mtime_ns) == original
    assert not (root / "runs/run_002").exists()
    assert store.snapshot()["generation"] == before["generation"]
    assert (root / "original.csv").read_bytes() == b"old source"
