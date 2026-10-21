"""Real item/source classification, independent of ambient test labels."""
from pathlib import Path
from types import SimpleNamespace
import json
import os

from sciplot_core.verification.input_scope import load_manifest
from sciplot_core.verification import private_exclusion_boundary as boundary


class Observer:
    def __init__(self, directory):
        self.frames = []
        self.nodeid = None
        self.directory = directory
        self.run = "a" * 32
        self.wrapper_environment = {"SCIPLOT_VERIFY_FINISH": str(directory / "finish.json")}
        (directory / "state.json").write_text(json.dumps({"child_pid": os.getpid()}))
        (directory / "request.json").write_text(json.dumps({"scope": {"kind": "pytest"}}))
        (directory / "root.jsonl").write_text(json.dumps({"event": "process_start", "run_id": self.run,
            "sha256": "generated-unit-root", "activation": boundary.owner_identity("suite_evidence.py", "_audit_environment")}))

    def record(self, value, **kwargs):
        frame = {**value, "sha256": str(len(self.frames))}
        self.frames.append(frame)
        return frame


def item(node, *, path=None):
    return SimpleNamespace(nodeid=node, path=path or boundary.REPO / node.split("::", 1)[0])


def test_phase_uses_exact_source_and_clears_context_after_each_phase(tmp_path, monkeypatch):
    node = load_manifest()["scopes"]["public"][0]
    observer = Observer(tmp_path)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/forged.py::test_approved (call)")
    boundary.bind_collection(observer, [node])
    for phase in ("setup", "call", "teardown"):
        boundary.begin_phase(observer, item(node), phase)
        assert observer._exclusion_phase["test_nodeid"] == node
        assert observer._exclusion_phase["phase"] == phase
        boundary.end_phase(observer, item(node), phase)
        assert observer._exclusion_phase is None and observer.nodeid is None
    assert [frame["event"] for frame in observer.frames] == ["pytest_phase_enter", "pytest_phase_exit"] * 3


def test_unknown_private_nested_or_wrong_source_never_get_public_phase(tmp_path):
    manifest = load_manifest()
    public, private = manifest["scopes"]["public"][0], manifest["scopes"]["private"][0]
    for node in ("tests/unknown.py::test_forged", private):
        observer = Observer(tmp_path)
        boundary.bind_collection(observer, [node])
        boundary.begin_phase(observer, item(node), "call")
        assert observer._exclusion_phase is None and not observer.frames
    observer = Observer(tmp_path)
    boundary.bind_collection(observer, [public])
    boundary.begin_phase(observer, item(public, path=Path("/generated/wrong.py")), "call")
    assert observer._exclusion_phase is None
    boundary.bind_collection(observer, [public])
    boundary.begin_phase(observer, item(public), "call")
    assert observer._exclusion_phase is None and not observer.frames


def test_a_different_durable_primary_pid_cannot_activate_known_public_item(tmp_path):
    node = load_manifest()["scopes"]["public"][0]
    observer = Observer(tmp_path)
    (tmp_path / "state.json").write_text(json.dumps({"child_pid": os.getpid() + 1}))
    boundary.bind_collection(observer, [node])
    boundary.begin_phase(observer, item(node), "call")
    assert observer._exclusion_collection is None and observer._exclusion_phase is None
    assert not observer.frames
