"""Trusted default policy checks with real tiny Git/pytest and fake runtime bytes."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.verification import evidence_scope as scope
from sciplot_core.verification.evidence import ARTIFACT_NAMES, check_reuse, make_receipt
from sciplot_core.verification.evidence_identity import capture_identity, discover_files


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.delenv("SCIPLOT_REFERENCE_DATA", raising=False)
    contents = {
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        ".gitignore": ".tmp_verify/\n__pycache__/\n.pytest_cache/\n",
        "README.md": "original prose\n", "docs/guide.md": "guide\n",
        "src/sciplot_core/implementation.py": "VALUE = 1\n",
        "skill/scripts/sciplot": "runtime wrapper\n", "skill/SKILL.md": "policy\n",
        "skill/references/development.md": "development policy\n",
        "tests/test_unit.py": "def test_ok(): assert True\n",
        "tests/fixtures/raw.csv": "time,value\n0,1\n",
        "tests/fixtures/rendering_profiles/golden.json": "{}\n",
        **{f"runtime/{domain}/bytes": domain for domain in ("python", "dependencies", "qt", "native", "fonts")},
    }
    inventory = {"kind": "sciplot_private_corpus_dependencies", "version": 1,
                 "gate": "private_corpus_preflight", "inventory_complete": False,
                 "collection_audit": {"static_review_complete": True,
                                      "candidate_nodeids": ["tests/test_private.py::test_known"]},
                 "cases": [{"nodeid": "tests/test_private.py::test_known", "dependencies": [{"path": "tests/fixtures/real_world/a.csv", "kind": "file"}], "evidence": "reviewed"}]}
    contents["src/sciplot_core/verification/private_corpus_inventory.json"] = json.dumps(inventory)
    for name, value in contents.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "baseline")
    def runtime_inputs(**kwargs):
        return {domain: [tmp_path / "runtime" / domain] for domain in ("python", "dependencies", "qt", "native", "fonts")}, {"system": "synthetic runtime"}
    monkeypatch.setattr(scope, "runtime_inputs", runtime_inputs)
    monkeypatch.setattr(scope, "native_dependencies", lambda *args, **kwargs: [])
    return tmp_path


def spec_for(root, *, module="pytest", nodes=None):
    checks = {"pytest": ("pytest_changed_owners", [sys.executable, "-m", "pytest", "-q", *(nodes or ["tests/test_unit.py"])]),
              "ruff": ("ruff_changed_python", [sys.executable, "-m", "ruff", "check", "src/sciplot_core/implementation.py"]),
              "git": ("diff_whitespace", ["git", "diff", "--check", "HEAD", "--"])}
    check_id, command = checks[module]
    check = {"check_id": check_id, "command": command}
    plan = {"status": "planned", "unowned_paths": [], "checks": [check], "changed_paths": ["src/sciplot_core/implementation.py"]}
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    return scope.build_check_spec(plan, check, root, environment=environment,
                                  finish_path=root / ".tmp_verify/run/finish.json")


def identity(spec):
    return capture_identity(**{**spec, "repo_root": Path(spec["repo_root"])})


def passed(before, after=None):
    finish = {"complete": True, "exit_code": 0, "selected_tests": before["selected_tests"]}
    if before["scope"]["kind"] == "pytest":
        finish["executed_tests"] = before["selected_tests"]
    return make_receipt(before=before, after=after or before, exit_code=0, session_finish=finish,
                        wall_seconds=1, artifacts={name: "a" * 64 for name in ARTIFACT_NAMES})


def test_default_collects_exact_nodes_and_disallows_domain_omissions(checkout):
    spec = spec_for(checkout)
    assert spec["selected_tests"] == ["tests/test_unit.py::test_ok"]
    assert spec["command"][3:5] == ["-p", "sciplot_core.verification.pytest_finish"]
    assert all("not_applicable" not in value for value in spec["inputs"].values())
    assert spec["corpus"]["mode"] == "declared"
    assert spec["corpus"]["scientific_acceptance"] is False
    assert spec["corpus"]["fresh_access_audit"] is False
    assert passed(identity(spec))["status"] == "PASS"


def test_unrelated_documentation_commit_reuses_executable_evidence(checkout):
    before = identity(spec_for(checkout))
    receipt = passed(before)
    (checkout / "README.md").write_text("revised prose\n")
    git(checkout, "add", "README.md")
    git(checkout, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "documentation only")
    after = identity(spec_for(checkout))
    result = check_reuse(receipt, after, artifacts=receipt["artifacts"])
    assert result["status"] == "PASS" and result["reused"] is True


@pytest.mark.parametrize("name", [
    "src/sciplot_core/implementation.py", "tests/test_unit.py", "pyproject.toml",
    "runtime/python/bytes", "runtime/dependencies/bytes", "runtime/qt/bytes",
    "runtime/native/bytes", "runtime/fonts/bytes", "tests/fixtures/raw.csv",
    "tests/fixtures/rendering_profiles/golden.json", "skill/references/development.md",
])
def test_default_rejects_each_real_input_drift(checkout, name):
    spec = spec_for(checkout, module="ruff")
    before = identity(spec)
    path = checkout / name
    path.write_text(path.read_text() + "\nchanged bytes\n")
    if path.suffix == ".py":
        with pytest.raises(ValueError, match="discovery"):
            identity(spec)
    else:
        after = identity(spec)
        assert passed(before, after)["reason"] == "input_drift"


def test_git_document_and_index_drift_block_original_receipt(checkout):
    spec = spec_for(checkout, module="git")
    before = identity(spec)
    assert subprocess.run(spec["command"], cwd=checkout).returncode == 0
    (checkout / "README.md").write_text("bad whitespace   \n")
    after = identity(spec)
    assert passed(before, after)["status"] == "BLOCKED"
    assert subprocess.run(spec["command"], cwd=checkout, capture_output=True).returncode != 0


def test_document_inspecting_scope_binds_prose(checkout):
    (checkout / "tests/test_unit.py").write_text("from pathlib import Path\ndef test_ok(): assert Path('README.md').read_text()\n")
    spec = spec_for(checkout)
    before = identity(spec)
    (checkout / "README.md").write_text("new contract prose\n")
    assert passed(before, identity(spec))["status"] == "BLOCKED"


def test_new_raw_member_and_symlink_target_are_rechecked_in_same_spec(checkout):
    alias = checkout / "tests/fixtures/alias.csv"
    alias.symlink_to(checkout / "tests/fixtures/raw.csv")
    spec = spec_for(checkout, module="ruff")
    identity(spec)
    (checkout / "tests/fixtures/new.csv").write_text("new input\n")
    with pytest.raises(ValueError, match="discovery"):
        identity(spec)
    alias.unlink()
    alias.symlink_to(checkout / "tests/fixtures/new.csv")
    with pytest.raises(ValueError, match="discovery"):
        identity(spec)


def test_missing_optional_root_creation_is_a_change(checkout):
    spec = spec_for(checkout, module="ruff")
    identity(spec)
    local = checkout / ".local/reference_data/new.csv"
    local.parent.mkdir(parents=True)
    local.write_text("new source")
    with pytest.raises(ValueError, match="discovery"):
        identity(spec)


def test_native_discovery_binding_cannot_be_paired_with_new_bytes(checkout):
    spec = spec_for(checkout)
    (checkout / "tests/test_unit.py").write_text("def test_ok(): assert False\n")
    with pytest.raises(ValueError, match="discovery"):
        identity(spec)


def test_command_conflict_unknown_owner_and_unknown_private_node_block(checkout):
    check = {"check_id": "pytest_changed_owners", "command": [sys.executable, "-m", "pytest", "tests/test_unit.py"]}
    plan = {"checks": [check], "unowned_paths": ["unknown.py"]}
    with pytest.raises(ValueError, match="unknown"):
        scope.build_check_spec(plan, check, checkout, environment=dict(os.environ), finish_path=checkout / ".tmp_verify/x/finish.json")
    plan["unowned_paths"] = []
    wrong = copy.deepcopy(check)
    wrong["command"] = [sys.executable, "-c", "print('forged gate')"]
    with pytest.raises(ValueError, match="current owner plan"):
        scope.build_check_spec(plan, wrong, checkout, environment=dict(os.environ), finish_path=checkout / ".tmp_verify/x/finish.json")
    (checkout / "tests/test_private.py").write_text("def test_unknown(): assert True\n")
    with pytest.raises(ValueError, match="disposition"):
        spec_for(checkout, nodes=["tests/test_private.py"])


def test_external_real_literal_is_not_silently_synthetic(checkout, tmp_path):
    external = checkout.parent / (checkout.name + "-private-source.csv")
    external.write_text("outside declared scientific namespaces")
    (checkout / "tests/test_unit.py").write_text(f"def test_ok():\n    source = {str(external)!r}\n    assert source\n")
    with pytest.raises(ValueError, match="unbound existing external"):
        spec_for(checkout)


def test_directory_cycle_and_broken_symlink_fail_closed(checkout):
    tree = checkout / "cycle"
    tree.mkdir()
    (tree / "loop").symlink_to(tree, target_is_directory=True)
    with pytest.raises(ValueError, match="cycle"):
        discover_files([tree])
    (tree / "loop").unlink()
    (tree / "broken").symlink_to(tree / "absent")
    with pytest.raises(FileNotFoundError):
        discover_files([tree], allow_missing=True)


@pytest.mark.parametrize("domain", ["dependencies", "fonts"])
def test_runtime_membership_is_rediscovered_after_command(checkout, domain):
    spec = spec_for(checkout, module="ruff")
    identity(spec)
    (checkout / "runtime" / domain / "new-file").write_text("new bytes")
    with pytest.raises(ValueError, match="discovery"):
        identity(spec)


@pytest.mark.parametrize("change", ["third_party", "index", "head"])
def test_git_binds_all_tracked_inputs_and_index_and_head(checkout, change):
    license = checkout / "third_party/tavotto-ui/LICENSE"
    license.parent.mkdir(parents=True)
    license.write_text("license\n")
    git(checkout, "add", str(license))
    spec = spec_for(checkout, module="git")
    before = identity(spec)
    if change == "third_party":
        license.write_text("bad whitespace   \n")
    elif change == "index":
        git(checkout, "rm", "--cached", str(license))
    else:
        git(checkout, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "new HEAD")
    assert passed(before, identity(spec))["status"] == "BLOCKED"


def test_new_source_after_graph_discovery_is_rejected(checkout):
    spec = spec_for(checkout, module="ruff")
    (checkout / "src/new_module.py").write_text("from PyQt6 import QtQuick\n")
    with pytest.raises(ValueError, match="discovery"):
        identity(spec)
    with pytest.raises(ValueError, match="Qt imports"):
        spec_for(checkout, module="ruff")


@pytest.mark.parametrize("tier", ["focused", "comprehensive", "full"])
def test_named_suite_profiles_are_exact_not_arbitrary_commands(checkout, monkeypatch, tier):
    monkeypatch.setattr(scope, "collect_check_tests", lambda *args, **kwargs: ["tests/test_unit.py::test_ok"])
    check = {"check_id": f"pytest_{tier}", "command": [sys.executable, "-m", "pytest", "-q", *(["-m", tier] if tier != "full" else [])]}
    plan = {"checks": [check], "unowned_paths": []}
    spec = scope.build_check_spec(plan, check, checkout, environment=dict(os.environ), finish_path=checkout / ".tmp_verify/suite/finish.json")
    assert spec["scope"]["check_id"] == f"pytest_{tier}"
    check["command"].append("--last-failed")
    with pytest.raises(ValueError, match="reviewed profile"):
        scope.build_check_spec(plan, check, checkout, environment=dict(os.environ), finish_path=checkout / ".tmp_verify/suite/finish.json")


def test_relative_private_namespace_uses_repo_root_preserving_alias(checkout, monkeypatch):
    actual = checkout / "private-data"
    actual.mkdir()
    (actual / "raw.csv").write_text("actual scientific input")
    alias = checkout / "private-current"
    alias.symlink_to(actual, target_is_directory=True)
    monkeypatch.chdir(checkout.parent)
    paths, _ = scope._corpus_paths(checkout, {"SCIPLOT_REFERENCE_DATA": "private-current"}, [])
    assert paths[-1] == alias
    before = discover_files(paths, allow_missing=True)
    replacement = checkout / "private-replacement"
    replacement.mkdir()
    (replacement / "raw.csv").write_text("changed scientific input")
    alias.unlink()
    alias.symlink_to(replacement, target_is_directory=True)
    assert before != discover_files(paths, allow_missing=True)


def test_fake_checkout_does_not_inherit_private_data_environment(checkout):
    assert "SCIPLOT_REFERENCE_DATA" not in os.environ
