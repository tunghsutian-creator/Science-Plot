"""The byte-frozen 597 pending writer succeeds before transfer and refuses after."""
from contextlib import nullcontext
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from frozen_semantic_597 import FIXTURE, ROOT, read_manifest


def _profile_frame(filename, name, *, flags=2):
    return SimpleNamespace(f_code=SimpleNamespace(
        co_filename=str(filename), co_qualname=name, co_firstlineno=17, co_flags=flags))


def test_historical_counter_retains_every_call_and_exact_lexical_membership(monkeypatch, tmp_path):
    import frozen_semantic_597 as counter

    root, fixture = tmp_path / "checkout", tmp_path / "frozen"
    monkeypatch.setattr(counter, "ROOT", root)
    monkeypatch.setattr(counter, "FIXTURE", fixture)
    path_calls = []

    def counted_path(value):
        path_calls.append(value)
        return Path(value)

    monkeypatch.setattr(counter, "Path", counted_path)
    owned = root / "src/sciplot_core/owner.py"
    historical = fixture / "old.py"
    neighbor = root / "src/sciplot_core_neighbor/foreign.py"
    dotted = str(root) + "/src/sciplot_core/./owner.py"
    frames = [
        _profile_frame(owned, "first"), _profile_frame(owned, "second"),
        _profile_frame(historical, "old"), _profile_frame(neighbor, "foreign"),
        _profile_frame("relative/owner.py", "relative"), _profile_frame(dotted, "dotted"),
        _profile_frame(owned, "module", flags=0),
    ]
    executed, calls = set(), set()
    profile = counter.source_call_profile(executed, calls)
    for _ in range(40):
        for frame in frames:
            profile(frame, "call", None)
    profile(_profile_frame(root / "src/sciplot_core/unexecuted.py", "return"), "return", None)
    assert path_calls == [str(owned), str(historical), str(neighbor), "relative/owner.py", dotted]
    assert executed == {owned, historical}
    assert calls == {(str(owned), name, 17) for name in ("first", "second", "dotted")} | {
        (str(historical), "old", 17)}


def test_historical_counter_classification_is_not_shared_between_invocations(monkeypatch, tmp_path):
    import frozen_semantic_597 as counter

    root = tmp_path / "first"
    monkeypatch.setattr(counter, "ROOT", root)
    monkeypatch.setattr(counter, "FIXTURE", tmp_path / "frozen")
    filename = root / "src/sciplot_core/owner.py"
    first_files, first_calls = set(), set()
    counter.source_call_profile(first_files, first_calls)(_profile_frame(filename, "first"), "call", None)
    monkeypatch.setattr(counter, "ROOT", tmp_path / "second")
    second_files, second_calls = set(), set()
    counter.source_call_profile(second_files, second_calls)(_profile_frame(filename, "second"), "call", None)
    assert first_files == {filename} and first_calls == {(str(filename), "first", 17)}
    assert second_files == second_calls == set()


def test_historical_counter_membership_memo_never_caches_source_bytes(monkeypatch, tmp_path):
    import frozen_semantic_597 as counter

    monkeypatch.setattr(counter, "ROOT", tmp_path)
    monkeypatch.setattr(counter, "FIXTURE", tmp_path / "frozen")
    helper = tmp_path / "src/sciplot_core/helper.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("def measured():\n    return 1\n")
    manifest = {"operational_helpers": {"src/sciplot_core/helper.py": {
        "sha256": hashlib.sha256(helper.read_bytes()).hexdigest()}}}
    executed, calls = set(), set()
    profile = counter.source_call_profile(executed, calls)
    profile(_profile_frame(helper, "measured"), "call", None)
    counter.validate_operational_helpers(manifest, calls)
    helper.write_text("def measured():\n    return 2\n")
    profile(_profile_frame(helper, "measured"), "call", None)
    with pytest.raises(AssertionError, match="src/sciplot_core/helper.py"):
        counter.validate_operational_helpers(manifest, calls)


def _child(operation, case, phase):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    # Keep the actual guard/observer startup and earlier source-owner order.
    # An earlier foreign owner must be rejected, never masked by this fixture.
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (env.get("PYTHONPATH", ""), str(ROOT / "src"))))
    completed = subprocess.run([sys.executable, str(ROOT / "tests/frozen_semantic_597.py"),
        operation, str(case), phase], env=env, text=True, capture_output=True, timeout=30, check=False)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    manifest = read_manifest()
    assert result["loaded_owners"] == {name: str(FIXTURE / record["fixture"])
        for name, record in manifest["owners"].items()}
    return result


def _current_application(backend):
    from sciplot_core.project_lifecycle.application import ProjectApplication
    from sciplot_core.project_lifecycle.attachment_preflight import preflight
    from sciplot_core.project_lifecycle.backend_paths import RepositoryBackendPaths
    from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
    from sciplot_core.project_lifecycle.repository_router import ComposedProjectRepository
    from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets

    repo = ComposedProjectRepository(lease=lambda _: nullcontext(),
        attachment_admission=lambda namespace, head, attachment:
            preflight(backend, COMPATIBILITY_CAPABILITIES, namespace, head, attachment))
    return ProjectApplication(RepositoryBackendPaths(backend, repo), repo,
        targets=FilesystemProjectTargets(repo), capabilities=COMPATIBILITY_CAPABILITIES)


def _files(root):
    return {path.relative_to(root).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(),
        stat.S_IMODE(path.stat().st_mode)) for path in sorted(root.rglob("*")) if path.is_file()}


def test_historical_fixture_pins_original_source_commit_and_bytes():
    manifest = read_manifest()
    assert manifest["source_commit"] == "597fee38f99b92f5f18860801f4630d81323012d"
    assert manifest["owners"]["sciplot_core.project_lifecycle.repository"]["sha256"] == (
        "6b2a2975a5bc2fc466034e672c534e9045887916b13c4a8317c7feaffe31dbd0")


@pytest.mark.parametrize("phase", ["prepared", "applying"])
@pytest.mark.parametrize("attached", [False, True], ids=["before-transfer", "after-transfer"])
@pytest.mark.focused
def test_original_pending_writer_has_no_native_or_state_write_after_attachment(tmp_path, phase, attached):
    from sciplot_core.project_store.repository import FileProjectStore
    from sciplot_core.project_store.runtime import project_runtime
    from test_plot_engine import FakeBackend

    _child("prepare", tmp_path, phase)
    native, semantic = tmp_path / "native", tmp_path / "semantic"
    raw_hash = hashlib.sha256((native / "raw.csv").read_bytes()).hexdigest()
    store = None
    if attached:
        backend = FakeBackend(native)
        store = FileProjectStore(native)
        store.snapshot(import_legacy=True)
        with project_runtime(store):
            opened = _current_application(backend).open(semantic)
        assert opened["plot_id"] == "test-plot"
        assert backend.calls["apply"] == 0
    before_files = _files(tmp_path)
    before_snapshot = store.snapshot() if store is not None else None
    result = _child("resume", tmp_path, phase)
    assert hashlib.sha256((native / "raw.csv").read_bytes()).hexdigest() == raw_hash
    if attached:
        assert result["backend_calls"]["apply"] == 0
        assert result["backend_calls"]["export"] == 0
        assert result["error"]["type"] == "EngineError"
        assert "revision pointer is invalid" in result["error"]["message"]
        old_repository = str(FIXTURE / read_manifest()["owners"]["sciplot_core.project_lifecycle.repository"]["fixture"])
        assert any(path == old_repository and name == "FileProjectRepository.load_head"
            for path, name, _line in result["functional_calls"])
        assert not (native / "native-writes.txt").exists()
        assert _files(tmp_path) == before_files
        assert store.snapshot() == before_snapshot
    else:
        assert "error" not in result
        assert result["backend_calls"]["apply"] == 1
        assert result["backend_calls"]["export"] == 1
        assert result["result"]["revision"] == 1
        assert (native / "native-writes.txt").read_text() == "1"


@pytest.mark.parametrize("mode", ["missing-bootstrap", "foreign-source"])
def test_historical_child_public_startup_refuses_missing_guard_or_foreign_source(tmp_path, mode):
    from sciplot_core.verification.public_input_guard import configure_environment

    foreign = tmp_path / "foreign-source"
    package = foreign / "sciplot_core"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# Unrelated source owner, never executed.\n")
    case = tmp_path / "never-launched-case"
    environment = configure_environment(ROOT, dict(os.environ),
        bootstrap=ROOT / "src/sciplot_core/verification/public_guard_bootstrap")
    code = f"""
import json, os, sys
from pathlib import Path
sys.path.insert(0, {str(ROOT / 'tests')!r})
from test_historical_semantic_writer_fence import _child
from sciplot_core.verification.public_input_guard import ENVIRONMENT_KEY, BOOTSTRAP_KEY
roots, bootstrap = os.environ[ENVIRONMENT_KEY], os.environ[BOOTSTRAP_KEY]
if {mode!r} == 'missing-bootstrap':
    os.environ['PYTHONPATH'] = {str(ROOT / 'src')!r}
else:
    os.environ['PYTHONPATH'] = {str(foreign)!r} + os.pathsep + os.environ['PYTHONPATH']
try:
    _child('prepare', Path({str(case)!r}), 'prepared')
except PermissionError as error:
    assert 'requires its guard bootstrap' in str(error), str(error)
else:
    raise AssertionError('An unguarded or foreign-source historical child was launched')
assert os.environ[ENVIRONMENT_KEY] == roots and os.environ[BOOTSTRAP_KEY] == bootstrap
assert not Path({str(case)!r}).exists()
print(json.dumps({{'status': 'rejected', 'mode': {mode!r}, 'guard_retained': True}}))
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"status": "rejected", "mode": mode, "guard_retained": True}
