"""Adversarial checks for local receipt scope, input drift and completion."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sciplot_core.verification.evidence import ARTIFACT_NAMES, check_reuse, load_receipt, make_receipt
from sciplot_core.verification.evidence_identity import DOMAINS, capture_identity, digest


@pytest.fixture
def spec(tmp_path):
    inputs = {}
    for domain in DOMAINS:
        path = tmp_path / domain
        path.write_text(domain)
        inputs[domain] = {"paths": [str(path)]}
    return dict(repo_root=tmp_path, command=["python", "-m", "pytest", "tests/test_unit.py"],
                scope={"kind": "pytest", "closure_policy": "explicit synthetic unit closure v1"},
                selected_tests=["tests/test_unit.py::test_example"], inputs=inputs,
                environment={"PATH": "/reviewed/runtime", "QT_QPA_PLATFORM": "offscreen"},
                corpus={"mode": "synthetic", "complete": True, "policy": "reviewed synthetic input"})


def receipt_for(identity, **overrides):
    kwargs = dict(before=identity, after=copy.deepcopy(identity), exit_code=0,
                  session_finish={"complete": True, "exit_code": 0,
                                  "selected_tests": identity["selected_tests"],
                                  "executed_tests": identity["selected_tests"]},
                  wall_seconds=0.125, artifacts={name: "a" * 64 for name in ARTIFACT_NAMES})
    return make_receipt(**{**kwargs, **overrides})


def test_exact_receipt_reuses_and_documentation_commit_does_not_invalidate(spec):
    identity = capture_identity(**spec)
    receipt = receipt_for(identity, provenance={"head": "old", "base": "base"})
    (spec["repo_root"] / "README.md").write_text("documentation-only change")
    current = capture_identity(**spec)
    result = check_reuse(receipt, current, artifacts=receipt["artifacts"])
    assert result["status"] == "PASS" and result["reused"] is True
    assert result["scope"] == spec["scope"]
    assert result["selected_tests"] == spec["selected_tests"]


@pytest.mark.parametrize("domain", sorted(DOMAINS))
def test_each_input_domain_byte_drift_invalidates(spec, domain):
    identity = capture_identity(**spec)
    receipt = receipt_for(identity)
    Path(spec["inputs"][domain]["paths"][0]).write_text("changed same-day bytes")
    current = capture_identity(**spec)
    assert check_reuse(receipt, current, artifacts=receipt["artifacts"])["reason"] == "identity_mismatch"
    assert receipt_for(identity, after=current)["reason"] == "input_drift"


@pytest.mark.parametrize("field,value", [
    ("command", ["python", "-m", "pytest"]),
    ("scope", {"kind": "pytest", "closure_policy": "wider release scope"}),
    ("selected_tests", ["tests/test_other.py::test_new"]),
    ("environment", {"QT_QPA_PLATFORM": "xcb"}),
])
def test_command_scope_selection_and_environment_must_match(spec, field, value):
    identity = capture_identity(**spec)
    receipt = receipt_for(identity)
    spec[field] = value
    assert check_reuse(receipt, capture_identity(**spec), artifacts=receipt["artifacts"])["status"] == "BLOCKED"


@pytest.mark.parametrize("finish,code,status,reason", [
    (None, 0, "BLOCKED", "session_finish_missing"),
    ({"complete": False}, 0, "BLOCKED", "session_finish_missing"),
    ({"complete": True, "exit_code": 1}, 0, "BLOCKED", "exit_mismatch"),
    ({"complete": True, "exit_code": 1}, 1, "FAIL", "command_failed"),
    ({"complete": True, "exit_code": 2}, 2, "BLOCKED", "execution_interrupted_or_unavailable"),
    ({"complete": True, "exit_code": -9}, -9, "BLOCKED", "execution_interrupted_or_unavailable"),
    ({"complete": True, "exit_code": 5, "selected_tests": []}, 5, "NO_TESTS", "empty_selection"),
    ({"complete": True, "exit_code": 0, "selected_tests": []}, 0, "BLOCKED", "selection_mismatch"),
])
def test_exit_and_finish_fail_closed(spec, finish, code, status, reason):
    receipt = receipt_for(capture_identity(**spec), session_finish=finish, exit_code=code)
    assert (receipt["status"], receipt["reason"]) == (status, reason)
    assert check_reuse(receipt, receipt["before"], artifacts=receipt["artifacts"])["reused"] is False


def test_skipped_body_cannot_supply_execution_proof(spec):
    identity = capture_identity(**spec)
    finish = {"complete": True, "exit_code": 0, "selected_tests": identity["selected_tests"], "executed_tests": []}
    assert receipt_for(identity, session_finish=finish)["reason"] == "execution_incomplete"


@pytest.mark.parametrize("malformed", [None, [], "execute /bin/sh", {}, {"before": None}, {"status": "PASS"}])
def test_malformed_untrusted_receipt_is_never_executed(spec, malformed):
    assert check_reuse(malformed, capture_identity(**spec), artifacts={})["status"] == "BLOCKED"


def test_receipt_and_log_tampering_rejected(spec):
    identity = capture_identity(**spec)
    receipt = receipt_for(identity)
    assert check_reuse(receipt, identity, artifacts={"command.log": "b" * 64})["reason"] == "artifact_drift"
    receipt["wall_seconds"] = 100
    assert check_reuse(receipt, identity, artifacts=receipt["artifacts"])["reason"] == "invalid_receipt"


def test_incomplete_identity_and_preliminary_corpus_rejected(spec):
    for domain in DOMAINS:
        incomplete = copy.deepcopy(spec)
        incomplete["inputs"].pop(domain)
        with pytest.raises(ValueError, match="domains"):
            capture_identity(**incomplete)
    spec["corpus"]["mode"] = "preliminary"
    with pytest.raises(ValueError, match="corpus"):
        capture_identity(**spec)


def test_audited_corpus_requires_inventory_access_and_actual_raw_bytes(spec):
    spec["corpus"]["mode"] = "audited"
    with pytest.raises(ValueError, match="actual raw"):
        capture_identity(**spec)
    for domain in ("inventory", "access_receipt"):
        path = spec["repo_root"] / domain
        path.write_text("audited source")
        spec["inputs"][domain] = {"paths": [str(path)]}
    before = capture_identity(**spec)
    Path(spec["inputs"]["inventory"]["paths"][0]).write_text("new closure inventory")
    after = capture_identity(**spec)
    assert before != after
    spec["inputs"]["raw"] = {"not_applicable": "cannot silently drop corpus bytes"}
    with pytest.raises(ValueError, match="actual raw"):
        capture_identity(**spec)


def test_tree_membership_and_symlinks_fail_closed(spec):
    tree = spec["repo_root"] / "sources"
    tree.mkdir()
    (tree / "source.py").write_text("x = 1")
    spec["inputs"]["implementation"] = {"paths": [str(tree)]}
    before = capture_identity(**spec)
    (tree / "new.py").write_text("x = 2")
    assert capture_identity(**spec) != before
    (tree / "alias").symlink_to(tree / "source.py")
    with pytest.raises(ValueError, match="symlinks"):
        capture_identity(**spec)


def test_snapshot_does_not_expose_private_names_or_values(spec):
    private = spec["repo_root"] / "private-sensitive-name.csv"
    private.write_text("secret scientific values")
    spec["inputs"]["raw"] = {"paths": [str(private)]}
    encoded = json.dumps(capture_identity(**spec))
    assert str(private) not in encoded and "secret scientific values" not in encoded
    assert digest(str(private)) in encoded


def test_loading_malformed_receipt_is_data_only(tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text("not JSON: __import__('os').system('false')")
    assert load_receipt(path) is None
    path.write_text('{"status":"FAIL","status":"PASS"}')
    assert load_receipt(path) is None
    for number in ("NaN", "Infinity", "1e999"):
        path.write_text('{"wall_seconds":' + number + '}')
        assert load_receipt(path) is None


def test_scope_exclusion_needs_bound_policy(spec):
    spec["inputs"]["qt"] = {"not_applicable": "pure standard library test"}
    with pytest.raises(ValueError, match="scope policy"):
        capture_identity(**spec)
    spec["scope"]["excluded_domains"] = {"qt": "pure standard library test"}
    assert capture_identity(**spec)["inputs"]["qt"] == spec["inputs"]["qt"]


def test_resealed_incomplete_identity_does_not_mint_pass(spec):
    identity = capture_identity(**spec)
    identity["inputs"]["python"] = {"files": {}, "sha256": digest({})}
    identity["sha256"] = digest({key: value for key, value in identity.items() if key != "sha256"})
    assert receipt_for(identity)["status"] == "BLOCKED"


def test_empty_selection_and_unknown_finish_fields(spec):
    spec["selected_tests"] = []
    assert receipt_for(capture_identity(**spec))["status"] == "NO_TESTS"
    spec["selected_tests"] = ["tests/test_unit.py::test_example"]
    identity = capture_identity(**spec)
    finish = receipt_for(identity)["session_finish"]
    finish["unknown_proof"] = True
    assert receipt_for(identity, session_finish=finish)["reason"] == "invalid_session_finish"


def test_missing_execution_artifact_cannot_be_sealed(spec):
    with pytest.raises(ValueError, match="artifact"):
        receipt_for(capture_identity(**spec), artifacts={"command.log": "a" * 64})


def test_declared_closure_cannot_claim_fresh_private_acceptance(spec):
    spec["corpus"] = {"mode": "declared", "complete": True, "policy": "reviewed scoped static closure"}
    with pytest.raises(ValueError, match="exclusions"):
        capture_identity(**spec)
    spec["corpus"].update(fresh_access_audit=False, scientific_acceptance=False)
    spec["inputs"]["inventory"] = spec["inputs"]["corpus_policy"]
    identity = capture_identity(**spec)
    assert receipt_for(identity)["status"] == "PASS"
    spec["corpus"]["scientific_acceptance"] = True
    with pytest.raises(ValueError, match="exclusions"):
        capture_identity(**spec)
