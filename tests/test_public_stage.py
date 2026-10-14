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
    stage, child, receipt = public_stage.create_stage(root, root / ".tmp_verify/stage", environment)
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
