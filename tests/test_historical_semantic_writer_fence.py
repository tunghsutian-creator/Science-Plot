"""The byte-frozen 597 pending writer succeeds before transfer and refuses after."""
from contextlib import nullcontext
import hashlib
import json
import os
import stat
import subprocess
import sys

import pytest

from frozen_semantic_597 import FIXTURE, ROOT, read_manifest


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
