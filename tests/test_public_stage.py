"""Generated namespace/byte controls, not private scientific acceptance."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.verification import public_stage
from sciplot_core.verification.public_control_boundary import generated_control
from sciplot_core.verification.public_input_guard import BOOTSTRAP_KEY, ENVIRONMENT_KEY, configure_environment


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=root, text=True, capture_output=True, check=True).stdout


def test_affected_selection_is_exact_public_focused_and_preserves_canonical_profiles() -> None:
    nodes = ["tests/test_generated.py::test_value[a]", "tests/test_generated.py::test_value[b]",
             "tests/test_generated.py::test_value_extra", "tests/test_generated.py::test_native",
             "tests/test_generated.py::test_private"]
    manifest = {"scopes": {"public": nodes[:4], "private": nodes[4:]},
                "tiers": {"focused": [*nodes[:3], nodes[4]], "comprehensive": nodes[3:4]}}
    source = {"tests/test_generated.py": "generated source digest"}
    assert public_stage._selected_public_nodes(manifest, source, "public-focused", None) == set(nodes[:3])
    assert public_stage._selected_public_nodes(manifest, source, "public-comprehensive", None) == set(nodes[3:4])
    assert public_stage._selected_public_nodes(manifest, source, "public-all", None) == set(nodes[:4])
    assert public_stage._selected_public_nodes(manifest, source, "public-affected", ["tests/test_generated.py::test_value"]) == set(nodes[:2])
    assert public_stage._selected_public_nodes(manifest, source, "public-affected", [nodes[0]]) == {nodes[0]}
    assert public_stage._selected_public_nodes(manifest, source, "public-affected", ["tests/test_generated.py"]) == set(nodes[:3])
    for target in [nodes[3], nodes[4], "../tests/test_generated.py", "-q", "tests/untracked.py", "tests/test_generated.py::missing"]:
        with pytest.raises(ValueError, match="current tracked public focused"):
            public_stage._selected_public_nodes(manifest, source, "public-affected", [target])


def test_only_affected_profile_can_request_explicit_selection(tmp_path: Path) -> None:
    for profile, targets in [("public-affected", None), ("public-affected", []),
                             ("public-focused", []), ("public-all", ["tests/test_generated.py"])]:
        with pytest.raises(ValueError, match="requires explicit nonempty"):
            public_stage.run_public_stage(tmp_path, tmp_path / "never-created", profile, targets=targets)
        assert not (tmp_path / "never-created").exists()


def test_stage_binding_owner_import_does_not_require_the_pytest_plugin() -> None:
    script = '''import builtins
original = builtins.__import__
def without_dev(name, *args, **kwargs):
    if name == "pytest" or name.startswith("pytest."):
        raise ImportError("generated control: pytest is not installed")
    return original(name, *args, **kwargs)
builtins.__import__ = without_dev
from sciplot_core.verification.public_stage import validate_stage
assert callable(validate_stage)
'''
    result = subprocess.run([sys.executable, "-c", script], env=dict(os.environ), capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("partial_collection", (False, True))
def test_affected_selector_runs_after_exhaustive_scope_validation(tmp_path: Path, partial_collection: bool) -> None:
    nodes = ["test_generated.py::test_one", "test_generated.py::test_one_extra"]
    manifest = {"scopes": {"public": nodes, "private": []}, "tiers": {"focused": nodes, "comprehensive": []}}
    (tmp_path / "conftest.py").write_text(f'''import json
from pathlib import Path
import pytest
from sciplot_core.verification.input_scope import select_scope
def pytest_addoption(parser):
    parser.addoption("--input-scope")
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    collected = [item.nodeid for item in items]
    Path("collected.json").write_text(json.dumps(collected))
    try:
        select_scope(config.getoption("input_scope"), manifest={manifest!r}, collected=collected,
                     tiers={{node: "focused" for node in collected}}, private_nodes=set())
    except ValueError as error:
        raise pytest.UsageError(str(error)) from error
''')
    (tmp_path / "test_generated.py").write_text('''from pathlib import Path
def test_one():
    Path("executed.txt").write_text("exact selected body")
def test_one_extra():
    raise AssertionError("a prefix neighbour must not execute")
''')
    # cwd alone does not stop pytest discovering a parent project's root.
    command = [sys.executable, "-m", "pytest", "-q", f"--rootdir={tmp_path}", "-p", "sciplot_core.verification.public_stage_selection",
               "--input-scope", "public-focused", "--sciplot-public-target", nodes[0]]
    if partial_collection:
        command.append(nodes[0])
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(str(Path(entry).absolute()) for entry in environment.get("PYTHONPATH", "").split(os.pathsep))
    result = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True, check=False)
    assert (tmp_path / "collected.json").is_file(), result.stdout + result.stderr
    assert json.loads((tmp_path / "collected.json").read_text()) == (nodes[:1] if partial_collection else nodes)
    if partial_collection:
        assert result.returncode != 0 and "Input scope drift" in result.stderr
        assert not (tmp_path / "executed.txt").exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed, 1 deselected" in result.stdout
        assert (tmp_path / "executed.txt").read_text() == "exact selected body"


def test_affected_stage_reports_limited_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sciplot_core.verification import input_scope

    node = "tests/test_generated.py::test_one"
    output = tmp_path / "output"
    stage = tmp_path / "stage"
    stage.mkdir()
    output.mkdir()
    source = {"tests/test_generated.py": "bound"}
    before = {"source_bytes": source, "origin_source_bytes": source, "stage_head": "head",
              "origin_head": "head", "runtime": {"runtime": "bound"}}
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.setattr(public_stage, "create_stage", lambda *_args: (stage, {}, before))
    monkeypatch.setattr(input_scope, "load_manifest", lambda *_args: {
        "scopes": {"public": [node]}, "tiers": {"focused": [node]}})
    monkeypatch.setattr(public_stage, "assert_private_absent", lambda *_args: None)
    monkeypatch.setattr(public_stage, "source_binding", lambda *_args: source)
    monkeypatch.setattr(public_stage, "_git", lambda *_args: "head")
    monkeypatch.setattr(public_stage, "runtime_binding", lambda *_args: {"runtime": "bound"})
    monkeypatch.setattr(public_stage, "assert_stage_helpers", lambda *_args: None)
    def run(command, **_kwargs):
        marker = {"complete": True, "exit_code": 0, "selected_tests": [node], "executed_tests": [node]}
        reports = {"exit_code": 0, "selected_tests": [node], "reports": [
            {"nodeid": node, "when": phase, "outcome": "passed"} for phase in ("setup", "call", "teardown")]}
        (output / "finish.json").write_text(json.dumps(marker))
        (output / "reports.json").write_text(json.dumps(reports))
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(public_stage.subprocess, "run", run)
    result = public_stage.run_public_stage(tmp_path, output, "public-affected", targets=[node])
    assert result["status"] == "PASS"
    assert result["claim"] == "limited_affected_public_behavior_not_canonical_profile"
    assert result["canonical_profile_executed"] is False
    assert result["scientific_acceptance"] is False and result["access_capture_complete"] is False
    assert all(value is True for value in result["binding_checks"].values())


def _origin(tmp_path: Path) -> Path:
    root = tmp_path / "origin"
    root.mkdir()
    (root / ".gitignore").write_text(".tmp_verify/\n.local\n*.so\n")
    (root / "src").mkdir()
    (root / "src/generated.py").write_text("VALUE = 'generated software control'\n")
    owner = root / "src/sciplot_core/verification/public_stage.py"
    owner.parent.mkdir(parents=True)
    owner.write_bytes(Path(public_stage.__file__).read_bytes())
    private = root / "tests/fixtures/rendering_profiles/generated/input.csv"
    private.parent.mkdir(parents=True)
    private.write_text("generated private-namespace sentinel; no scientific data\n")
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Generated control")
    _git(root, "config", "user.email", "generated@invalid")
    _git(root, "add", ".")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-qm", "Generated source")
    helpers = root / "third_party/veusz/veusz/helpers"
    helpers.mkdir(parents=True)
    for name in public_stage.HELPERS:
        (helpers / f"{name}.so").write_bytes(f"generated non-executable {name}".encode())
    return root


@pytest.mark.parametrize("mutation", ("file", "directory", "private_alias", "dangling_alias", "ancestor_alias", "reference_environment"))
def test_controlled_stage_rejects_actual_private_namespace_and_aliases(tmp_path: Path, mutation: str) -> None:
    root = tmp_path / "source"
    root.mkdir()
    private = root / "tests/fixtures/real_world"
    private.parent.mkdir(parents=True)
    environment = {}
    if mutation == "file":
        private.write_text("generated sentinel")
    elif mutation == "directory":
        private.mkdir()
    elif mutation in {"private_alias", "dangling_alias"}:
        target = tmp_path / "target"
        if mutation == "private_alias":
            target.mkdir()
        private.symlink_to(target)
    elif mutation == "ancestor_alias":
        private.parent.rmdir()
        target = tmp_path / "target"
        target.mkdir()
        private.parent.symlink_to(target)
    else:
        environment["SCIPLOT_REFERENCE_DATA"] = str(tmp_path / "absent")
    with pytest.raises(ValueError):
        public_stage.assert_private_absent(root, environment)


def test_source_stage_copies_public_bytes_and_independent_git_without_reading_private_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _origin(tmp_path)
    private = root / "tests/fixtures/rendering_profiles/generated/input.csv"
    original_private = private.read_bytes()
    hash_file = public_stage._hash

    def public_hash(path: Path) -> str:
        assert not path.is_relative_to(private.parent)
        return hash_file(path)

    monkeypatch.setattr(public_stage, "_hash", public_hash)
    monkeypatch.setattr(public_stage, "runtime_binding", lambda *_: {"helpers": "synthetic unit instrumentation"})
    environment = {"SCIPLOT_RUNTIME_REPO": str(root)}
    for profile in ("public-focused", "public-comprehensive"):
        stage, child, receipt = public_stage.create_stage(root, root / (".tmp_verify/" + profile), environment)
        assert (stage / "src/generated.py").read_bytes() == (root / "src/generated.py").read_bytes()
        assert private.read_bytes() == original_private
        assert receipt["stage_head"] != receipt["origin_head"]
        assert receipt["source_bytes"] == receipt["origin_source_bytes"]
        assert not any(path.exists() or path.is_symlink() for path in public_stage.private_namespace_paths(stage))
        assert child["SCIPLOT_SOURCE_ROOT"] == str(stage / "src")
        assert child["SCIPLOT_RUNTIME_REPO"] == str(stage)
        assert public_stage.source_binding(stage) == receipt["source_bytes"]
        assert _git(root, "status", "--porcelain") == ""



@pytest.mark.parametrize("mutation", ("dirty_source", "source_alias", "inherited_reference", "wrong_source_environment", "traversal_output", "aliased_output"))
def test_source_stage_blocks_before_creation_when_origin_is_not_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    root = _origin(tmp_path)
    environment = {"SCIPLOT_RUNTIME_REPO": str(root)}
    if mutation == "dirty_source":
        (root / "src/generated.py").write_text("VALUE = 'changed'\n")
    elif mutation == "source_alias":
        source = root / "src/generated.py"
        source.unlink()
        source.symlink_to(tmp_path / "missing.py")
    elif mutation == "inherited_reference":
        environment["SCIPLOT_REFERENCE_DATA"] = str(tmp_path / "absent")
    elif mutation == "wrong_source_environment":
        environment["SCIPLOT_SOURCE_ROOT"] = str(tmp_path / "old/src")
    output = root / ".tmp_verify/new-stage"
    if mutation == "traversal_output":
        output = root / ".tmp_verify/../../escaped-stage"
    elif mutation == "aliased_output":
        (root / ".tmp_verify").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError):
        public_stage.create_stage(root, output, environment)
    assert not output.exists()


def test_unknown_caller_cannot_authorize_an_unguarded_generated_child(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENVIRONMENT_KEY, json.dumps([str(tmp_path / "private")]))
    with pytest.raises(PermissionError, match="source-owned"):
        with generated_control(dict(os.environ), [sys.executable, "-S", "-c", "pass"], tmp_path, durable=False):
            pytest.fail("unknown caller entered generated control")


def test_owned_test_identity_matches_actual_pytest_assertion_rewrite() -> None:
    import importlib
    from sciplot_core.verification.public_control_boundary import _test_codes
    from sciplot_core.verification.private_process_boundaries import _code_hash

    module = importlib.import_module("test_private_observer")
    actual = module.test_real_parent_child_access_and_genuine_finish_complete
    source = Path(module.__file__)
    assert _code_hash(actual.__code__) in _test_codes(source)[actual.__name__]


@pytest.mark.parametrize("mutation", ("healthy", "private_member", "stage_source", "origin_source", "receipt_alias", "helper_bytes", "helper_alias", "wrong_environment", "stage_head", "ignored_source"))
def test_stage_revalidation_blocks_actual_drift_with_explicit_synthetic_runtime_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    root = _origin(tmp_path)

    def synthetic_runtime(repo: Path, environment: dict[str, str]) -> dict:
        return {"claim": "synthetic instrumentation; no runtime/capture acceptance",
                "helpers": {name: public_stage._hash(path) for name, path in public_stage._helper_paths(repo, environment).items()}}

    monkeypatch.setattr(public_stage, "runtime_binding", synthetic_runtime)
    stage, environment, _ = public_stage.create_stage(root, root / ".tmp_verify/stage", {"SCIPLOT_RUNTIME_REPO": str(root)})
    # This unit fixture substitutes only the loaded-path witness; real staged
    # interpreter controls separately exercise the actual unmodified owner.
    monkeypatch.setattr(public_stage, "__file__", str(stage / "src/sciplot_core/verification/public_stage.py"))
    if mutation == "private_member":
        private = stage / "tests/fixtures/real_world"
        private.parent.mkdir(parents=True, exist_ok=True)
        private.mkdir()
    elif mutation == "stage_source":
        (stage / "src/generated.py").write_text("changed stage\n")
    elif mutation == "origin_source":
        (root / "src/generated.py").write_text("changed origin\n")
    elif mutation == "receipt_alias":
        receipt = stage / public_stage.RECEIPT
        copy = stage / ".tmp_verify/other.json"
        receipt.rename(copy)
        receipt.symlink_to(copy)
    elif mutation == "helper_bytes":
        next(iter(public_stage._helper_paths(stage, environment).values())).write_bytes(b"changed helper")
    elif mutation == "helper_alias":
        helper = next(iter(public_stage._helper_paths(stage, environment).values()))
        external = tmp_path / "same-helper.so"
        external.write_bytes(helper.read_bytes())
        helper.unlink()
        helper.symlink_to(external)
    elif mutation == "wrong_environment":
        environment["SCIPLOT_SOURCE_ROOT"] = str(root / "src")
    elif mutation == "stage_head":
        _git(stage, "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "Different independent identity")
    elif mutation == "ignored_source":
        (stage / ".git/info/exclude").write_text("src/unreviewed.py\n")
        (stage / "src/unreviewed.py").write_text("VALUE='unreviewed executable input'\n")
    if mutation == "healthy":
        assert public_stage.validate_stage(stage, environment)["source_bytes"] == public_stage.source_binding(stage)
    else:
        with pytest.raises(ValueError):
            public_stage.validate_stage(stage, environment)


@pytest.mark.parametrize("mutation", ("healthy", "missing_body", "unreviewed_skip", "failure", "duplicate_call", "unexpected_node", "unexpected_phase"))
def test_stage_completion_requires_actual_complete_reports(mutation: str) -> None:
    node = "tests/test_generated.py::test_generated"
    marker = {"complete": True, "exit_code": 0, "selected_tests": [node], "executed_tests": [node]}
    rows = [{"nodeid": node, "when": phase, "outcome": "passed", "skip_reason": None} for phase in ("setup", "call", "teardown")]
    if mutation == "missing_body":
        rows.pop(1)
        marker["executed_tests"] = []
    elif mutation == "unreviewed_skip":
        rows[1].update(outcome="skipped", skip_reason="Skipped: generated missing data")
        marker["executed_tests"] = []
    elif mutation == "failure":
        rows[1]["outcome"] = "failed"
        marker["executed_tests"] = []
    elif mutation == "duplicate_call":
        rows.insert(1, dict(rows[1]))
    elif mutation == "unexpected_node":
        rows[1]["nodeid"] = "tests/test_unreviewed.py::test_unknown"
    elif mutation == "unexpected_phase":
        rows.append({"nodeid": node, "when": "invented", "outcome": "passed", "skip_reason": None})
    reports = {"exit_code": 0, "selected_tests": [node], "reports": rows}
    assert bool(public_stage.review_stage_reports(marker, reports, platform="darwin")) is (mutation != "healthy")


def test_existing_mac_platform_skip_needs_exact_node_reason_and_platform() -> None:
    node, (phase, reason) = next(iter(public_stage.PLATFORM_SKIPS.items()))
    marker = {"complete": True, "exit_code": 0, "selected_tests": [node], "executed_tests": []}
    rows = [{"nodeid": node, "when": name, "outcome": "skipped" if name == phase else "passed",
             "skip_reason": reason if name == phase else None} for name in ("setup", "call", "teardown")]
    reports = {"exit_code": 0, "selected_tests": [node], "reports": rows}
    assert public_stage.review_stage_reports(marker, reports, platform="linux") == []
    assert public_stage.review_stage_reports(marker, reports, platform="darwin")
    rows[1]["skip_reason"] = "Skipped: local data missing"
    assert public_stage.review_stage_reports(marker, reports, platform="linux")


@pytest.mark.parametrize("mode", ("owned_common", "token_only"))
def test_actual_common_bootstrap_relocation_preserves_guard_and_rejects_fake_shim(tmp_path: Path, mode: str) -> None:
    root = Path(__file__).resolve().parents[1]
    secret = tmp_path / "generated-private.txt"
    secret.write_text("generated sentinel")
    environment = configure_environment(root, dict(os.environ), bootstrap=root / "src/sciplot_core/verification/public_guard_bootstrap")
    environment[ENVIRONMENT_KEY] = json.dumps(json.loads(environment[ENVIRONMENT_KEY]) + [str(secret)])
    code = f"""
import os,sys,subprocess
from pathlib import Path
from sciplot_core.verification.private_observer import write_bootstrap
from sciplot_core.verification.public_input_guard import configure_environment
plugin=Path({str(tmp_path / 'common')!r});write_bootstrap(plugin)
if {mode!r} == 'token_only': (plugin/'sitecustomize.py').write_text('# public_input_guard is only a token\\n')
environment=configure_environment(Path({str(root)!r}),dict(os.environ),bootstrap=plugin)
try:
    process=subprocess.run([sys.executable,'-c',"from pathlib import Path;Path("+repr({str(secret)!r})+").read_bytes()"],env=environment,capture_output=True,text=True)
except PermissionError:
    assert {mode!r} == 'token_only'
    print('FAKE BLOCKED')
else:
    assert {mode!r} == 'owned_common'
    assert process.returncode != 0 and 'forbids private access' in process.stderr, process.stderr
    print('OWNED GUARDED')
"""
    result = subprocess.run([sys.executable, "-c", code], env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("OWNED GUARDED" if mode == "owned_common" else "FAKE BLOCKED")
    assert BOOTSTRAP_KEY in environment


@pytest.mark.parametrize("mode", ("owned_common", "token_only"))
def test_editable_source_common_bootstrap_preserves_guard_without_explicit_source_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    import venv

    root = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "generated-editable-runtime"
    venv.EnvBuilder(with_pip=False).create(runtime)
    site_packages = next((runtime / "lib").glob("python*/site-packages"))
    (site_packages / "generated-sciplot-source.pth").write_text(
        str(root / "src") + "\n" + str(Path(pytest.__file__).parents[1]) + "\n")
    # Match CI's editable import: the package is available through .pth while
    # the inherited startup path names only the owned guard bootstrap.
    monkeypatch.setenv("PYTHONPATH", str(root / "src/sciplot_core/verification/public_guard_bootstrap"))
    monkeypatch.setattr(sys, "executable", str(runtime / "bin/python"))
    test_actual_common_bootstrap_relocation_preserves_guard_and_rejects_fake_shim(tmp_path, mode)


def test_common_bootstrap_rebind_retains_exact_roots_and_earlier_import_owner(tmp_path: Path) -> None:
    from sciplot_core.verification.private_observer import write_bootstrap
    from sciplot_core.verification.public_input_guard import rebind_bootstrap

    plugin = tmp_path / "common"
    write_bootstrap(plugin)
    earlier = tmp_path / "earlier-explicit-source"
    environment = {ENVIRONMENT_KEY: json.dumps([str(tmp_path / "protected")]),
                   "SCIPLOT_REFERENCE_DATA": str(tmp_path / "generated-reference"), "PYTHONPATH": str(earlier)}
    actual = rebind_bootstrap(environment, plugin)
    assert actual[ENVIRONMENT_KEY] == environment[ENVIRONMENT_KEY]
    assert actual["SCIPLOT_REFERENCE_DATA"] == environment["SCIPLOT_REFERENCE_DATA"]
    assert actual["PYTHONPATH"].split(os.pathsep) == [str(plugin), str(earlier), str(Path(__file__).resolve().parents[1] / "src")]
