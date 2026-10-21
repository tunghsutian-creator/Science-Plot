"""Discriminating scope, availability and inherited public guard controls."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.verification.input_scope import load_manifest, select_scope
from sciplot_core.verification.private_corpus import GATE, declared_input_availability, private_corpus_preflight
from sciplot_core.verification.public_input_guard import ENVIRONMENT_KEY


def _manifest() -> dict:
    private = [f"tests/test_real.py::test_science[{i}]" for i in range(111)]
    public = ["tests/test_public.py::test_generated", "tests/test_public.py::test_native"]
    return {"kind": "sciplot_test_input_scopes", "version": 1,
            "baseline_failure_nodeids_sha256": hashlib.sha256("\n".join(sorted(private)).encode()).hexdigest(),
            "scopes": {"public": public, "private": private},
            "tiers": {"focused": public[:1] + private, "comprehensive": public[1:]},
            "private_failure_responsibilities": [
                {"private_nodeid": node, "public_counterparts": public[:1], "disposition": "behavior_and_private_science",
                 "behavior_responsibility": "Generated software behavior control.",
                 "real_science_responsibility": "Original measured identities remain private."} for node in private]}


def test_named_input_scopes_partition_the_same_full_collection_and_keep_tiers(tmp_path: Path) -> None:
    value = _manifest()
    path = tmp_path / "scope.json"
    path.write_text(json.dumps(value))
    manifest = load_manifest(path)
    nodes = [*value["scopes"]["public"], *value["scopes"]["private"]]
    tiers = {node: tier for tier, members in value["tiers"].items() for node in members}
    private = set(value["scopes"]["private"])
    selected = {name: set(select_scope(name, manifest=manifest, collected=nodes, tiers=tiers, private_nodes=private))
                for name in ("public-focused", "public-comprehensive", "private-science")}
    assert not selected["public-focused"] & selected["public-comprehensive"]
    assert not (selected["public-focused"] | selected["public-comprehensive"]) & selected["private-science"]
    assert set.union(*selected.values()) == set(nodes)


@pytest.mark.parametrize("mutation", ("unknown", "stale", "duplicate", "private_classification", "tier"))
def test_scope_drift_blocks_before_any_selection(mutation: str) -> None:
    manifest = _manifest()
    nodes = [*manifest["scopes"]["public"], *manifest["scopes"]["private"]]
    tiers = {node: tier for tier, members in manifest["tiers"].items() for node in members}
    private = set(manifest["scopes"]["private"])
    if mutation == "unknown":
        nodes.append("tests/test_new.py::test_unreviewed")
    elif mutation == "stale":
        nodes.pop()
    elif mutation == "duplicate":
        nodes.append(nodes[0])
    elif mutation == "private_classification":
        private.remove(nodes[-1])
    else:
        tiers[nodes[0]] = "comprehensive"
    with pytest.raises(ValueError):
        select_scope("public-focused", manifest=manifest, collected=nodes, tiers=tiers, private_nodes=private)


@pytest.mark.parametrize("mutation", ("overlap", "missing_counterpart", "missing_failure", "tier_overlap"))
def test_malformed_scope_or_responsibility_manifest_fails_closed(tmp_path: Path, mutation: str) -> None:
    value = _manifest()
    if mutation == "overlap":
        value["scopes"]["public"].append(value["scopes"]["private"][0])
    elif mutation == "missing_counterpart":
        value["private_failure_responsibilities"][0]["public_counterparts"] = []
    elif mutation == "missing_failure":
        value["private_failure_responsibilities"].pop()
    else:
        value["tiers"]["comprehensive"].append(value["tiers"]["focused"][0])
    path = tmp_path / "scope.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load_manifest(path)


def test_private_presence_can_authorize_bodies_without_claiming_complete_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    node = "tests/test_real.py::test_science"
    fixture = tmp_path / "tests/fixtures/real_world/generated_control.csv"
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"kind": "sciplot_private_corpus_dependencies", "version": 1, "gate": GATE,
                                    "inventory_complete": False, "cases": [{"nodeid": node, "dependencies": [
                                        {"path": "tests/fixtures/real_world/generated_control.csv", "kind": "file"}], "evidence": "control"}]}))
    monkeypatch.setenv("SCIPLOT_REFERENCE_DATA", str(tmp_path / "absent"))
    missing = declared_input_availability(repo_root=tmp_path, inventory_path=inventory, collected_nodeids={node})
    assert missing["status"] == "BLOCKED" and missing["scientific_acceptance"] is False
    fixture.parent.mkdir(parents=True)
    fixture.write_text("generated structural bytes, not measured science\n")
    present = declared_input_availability(repo_root=tmp_path, inventory_path=inventory, collected_nodeids={node})
    assert present["status"] == "READY_FOR_SELECTED_TESTS"
    assert present["access_audit_complete"] is present["scientific_acceptance"] is False
    conservative = private_corpus_preflight(repo_root=tmp_path, inventory_path=inventory, collected_nodeids={node})
    assert conservative["status"] == "BLOCKED"
    assert [row["code"] for row in conservative["issues"]] == ["inventory_incomplete"]


@pytest.mark.parametrize("attempt", ("read", "list", "child", "drop_env", "drop_bootstrap", "no_site", "isolated", "ignore_env", "shadow_bootstrap", "token_only", "warning_no_site", "option_no_site"))
def test_public_guard_rejects_private_access_and_child_bypass(tmp_path: Path, attempt: str) -> None:
    secret = tmp_path / "private_control"
    secret.mkdir()
    (secret / "sentinel.txt").write_text("generated sentinel")
    roots = json.loads(os.environ.get(ENVIRONMENT_KEY, "[]")) + [str(secret)]
    code = """
import json, os, pathlib, subprocess, sys
from sciplot_core.verification.public_input_guard import ENVIRONMENT_KEY, install
os.environ[ENVIRONMENT_KEY] = json.dumps(ROOTS)
install()
try:
    if ATTEMPT == 'read': pathlib.Path(SECRET, 'sentinel.txt').read_bytes()
    elif ATTEMPT == 'list': list(pathlib.Path(SECRET).iterdir())
    else:
        env = dict(os.environ)
        command = [sys.executable, '-c', "from pathlib import Path; Path(" + repr(str(pathlib.Path(SECRET, 'sentinel.txt'))) + ").read_bytes()"]
        if ATTEMPT == 'child': command += [str(pathlib.Path(SECRET, 'sentinel.txt'))]
        elif ATTEMPT == 'drop_env': env.pop(ENVIRONMENT_KEY)
        elif ATTEMPT == 'drop_bootstrap': env.pop('PYTHONPATH', None)
        elif ATTEMPT == 'warning_no_site': command[1:1] = ['-W', 'ignore', '-S']
        elif ATTEMPT == 'option_no_site': command[1:1] = ['-X', 'dev', '-S']
        elif ATTEMPT in {'shadow_bootstrap', 'token_only'}:
            shadow = pathlib.Path(SECRET).parent / 'shadow'; shadow.mkdir()
            (shadow / 'sitecustomize.py').write_text('# public_input_guard token is not enforcement' + chr(10))
            env['PYTHONPATH'] = str(shadow) + os.pathsep + env.get('PYTHONPATH', '')
        else: command.insert(1, {'no_site':'-S', 'isolated':'-I', 'ignore_env':'-E'}[ATTEMPT])
        subprocess.run(command, env=env, check=True)
except PermissionError:
    print('BLOCKED before private read or child launch')
else:
    raise AssertionError('private scope escaped')
""".replace("ROOTS", repr(roots)).replace("ATTEMPT", repr(attempt)).replace("SECRET", repr(str(secret)))
    result = subprocess.run([sys.executable, "-c", code], env=dict(os.environ), capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "BLOCKED before private read or child launch"


@pytest.mark.parametrize("clear_source_path", (False, True))
def test_owned_bootstrap_installs_guard_before_actual_child_read_without_package_import(tmp_path: Path, clear_source_path: bool) -> None:
    from sciplot_core.verification.public_input_guard import configure_environment
    root = Path(__file__).parents[1]
    secret = tmp_path / "controlled_private.csv"
    secret.write_text("generated sentinel")
    environment = configure_environment(root, dict(os.environ), bootstrap=root / "src/sciplot_core/verification/public_guard_bootstrap")
    environment[ENVIRONMENT_KEY] = json.dumps(json.loads(environment[ENVIRONMENT_KEY]) + [str(secret)])
    if clear_source_path:
        environment["PYTHONPATH"] = str(root / "src/sciplot_core/verification/public_guard_bootstrap")
    result = subprocess.run([sys.executable, "-c", f"from pathlib import Path; Path({str(secret)!r}).read_bytes()"],
                            env=environment, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "Public input scope forbids private access" in result.stderr


@pytest.mark.parametrize("profile", ("public-focused", "public-comprehensive", "public-all", "private-science"))
def test_named_suite_argv_is_exact_and_cannot_add_an_unreviewed_filter(tmp_path: Path, profile: str) -> None:
    from sciplot_core.verification.evidence_scope import _validate_check
    command = [sys.executable, "-m", "pytest", "-q", "--input-scope", profile]
    check = {"check_id": f"pytest_{profile}", "command": command}
    plan = {"checks": [check]}
    assert _validate_check(plan, check, tmp_path) == "pytest"
    check["command"] = [*command, "-m", "focused"]
    with pytest.raises(ValueError, match="reviewed profile"):
        _validate_check(plan, check, tmp_path)
