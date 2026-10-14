"""Synthetic closure controls; real private/raw identity requirements remain."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from sciplot_core.verification import evidence_scope as scope
from sciplot_core.verification.evidence import check_reuse
from sciplot_core.verification.evidence_identity import (
    PUBLIC_GOLDEN_REASON, PUBLIC_INPUT_POLICY, PUBLIC_RAW_REASON,
    capture_identity, digest, identity_valid,
)
from test_verification_evidence_scope import checkout as _checkout, git, identity, passed

checkout = _checkout


@pytest.fixture
def public_checkout(checkout, monkeypatch):
    # The fixed-size responsibility schema is exercised with generated names,
    # never original private measurements, constants, provenance or test claims.
    private = [f"tests/test_generated_private.py::test_unused[{index}]" for index in range(111)]
    public = ["tests/test_unit.py::test_ok"]
    manifest = {"kind": "sciplot_test_input_scopes", "version": 1,
                "baseline_failure_nodeids_sha256": hashlib.sha256("\n".join(sorted(private)).encode()).hexdigest(),
                "scopes": {"public": public, "private": private},
                "tiers": {"focused": public + private, "comprehensive": []},
                "private_failure_responsibilities": [
                    {"private_nodeid": node, "public_counterparts": public, "disposition": "real_specific_only",
                     "behavior_responsibility": "Generated identity schema control only.",
                     "real_science_responsibility": "No scientific acceptance is authorized by this synthetic fixture."}
                    for node in private]}
    path = checkout / "src/sciplot_core/verification/input_scope_manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    git(checkout, "add", str(path))
    # Runtime and collection are explicit synthetic unit fixtures. Discovery,
    # real file hashing, build_check_spec and both identity validators are real.
    monkeypatch.setattr(scope, "collect_check_tests", lambda *args, **kwargs: public)
    return checkout


def public_spec(root, *, generated_only=True):
    if generated_only:
        git(root, "rm", "--", "tests/fixtures/raw.csv")
    check = {"check_id": "pytest_public-focused",
             "command": [sys.executable, "-m", "pytest", "-q", "--input-scope", "public-focused"]}
    plan = {"status": "planned", "unowned_paths": [], "checks": [check]}
    return scope.build_check_spec(plan, check, root, environment=dict(os.environ),
                                  finish_path=root / ".tmp_verify/run/finish.json")


def reseal(snapshot):
    for binding in snapshot["inputs"].values():
        if "files" in binding:
            payload = ({key: value for key, value in binding.items() if key != "sha256"}
                       if "layout_sha256" in binding else binding["files"])
            binding["sha256"] = digest(payload)
    snapshot["sha256"] = digest({key: value for key, value in snapshot.items() if key != "sha256"})


def test_generated_only_public_skips_empty_domains_before_discovery_and_binds_policy(public_checkout, monkeypatch):
    original = scope.discover_files

    def no_empty(paths, **kwargs):
        assert paths, "an empty excluded domain reached file discovery"
        return original(paths, **kwargs)

    monkeypatch.setattr(scope, "discover_files", no_empty)
    spec = public_spec(public_checkout)
    assert spec["corpus"] == {"mode": "synthetic", "complete": True, "policy": PUBLIC_INPUT_POLICY,
                               "fresh_access_audit": False, "scientific_acceptance": False}
    assert spec["inputs"]["raw"] == {"not_applicable": PUBLIC_RAW_REASON}
    assert spec["inputs"]["golden"] == {"not_applicable": PUBLIC_GOLDEN_REASON}
    assert set(spec["scope"]["excluded_domains"]) == {"raw", "golden"}
    before = identity(spec)
    assert identity_valid(before)
    assert passed(before)["status"] == "PASS"  # Synthetic unit receipt only.
    assert before["inputs"]["raw"] == spec["inputs"]["raw"]
    assert before["scope"]["public_inputs"]["manifest_sha256"] in {
        record["sha256"] for record in before["inputs"]["inventory"]["files"].values()}


def test_public_fixture_bytes_remain_declared_and_drift_blocks_reuse(public_checkout):
    spec = public_spec(public_checkout, generated_only=False)
    assert spec["corpus"]["mode"] == "declared"
    assert set(spec["scope"]["excluded_domains"]) == {"golden"}
    before = identity(spec)
    raw = public_checkout / "tests/fixtures/raw.csv"
    assert before["inputs"]["raw"]["files"][digest(str(raw.resolve()))]["sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()
    receipt = passed(before)
    raw.write_text("time,value\n0,17\n")
    after = identity(spec)
    assert check_reuse(receipt, after, artifacts=receipt["artifacts"])["status"] == "BLOCKED"


@pytest.mark.parametrize("mutation", (
    "missing_binding", "missing_labels", "wrong_profile", "wrong_closure_policy", "missing_inventory_manifest", "wrong_manifest_hash",
    "wrong_raw_reason", "wrong_golden_reason", "science_claim", "command_filter", "unbound_selection",
))
def test_public_exclusion_cannot_be_resealed_without_exact_scope_binding(public_checkout, mutation):
    snapshot = identity(public_spec(public_checkout))
    binding = snapshot["scope"]["public_inputs"]
    if mutation == "missing_binding":
        snapshot["scope"].pop("public_inputs")
    elif mutation == "missing_labels":
        for key in ("check_id", "input_scope", "public_inputs"):
            snapshot["scope"].pop(key)
    elif mutation == "wrong_profile":
        binding["profile"] = "public-all"
    elif mutation == "wrong_closure_policy":
        snapshot["scope"]["closure_policy"] = "unreviewed-exclusion-policy"
    elif mutation == "missing_inventory_manifest":
        snapshot["inputs"]["inventory"]["files"].pop(binding["manifest_path_sha256"])
    elif mutation == "wrong_manifest_hash":
        binding["manifest_sha256"] = "a" * 64
    elif mutation == "wrong_raw_reason":
        snapshot["inputs"]["raw"] = {"not_applicable": "skip private files"}
        snapshot["scope"]["excluded_domains"]["raw"] = "skip private files"
    elif mutation == "wrong_golden_reason":
        snapshot["inputs"]["golden"] = {"not_applicable": "skip golden"}
        snapshot["scope"]["excluded_domains"]["golden"] = "skip golden"
    elif mutation == "science_claim":
        snapshot["corpus"]["scientific_acceptance"] = True
    elif mutation == "command_filter":
        snapshot["command"].extend(["-k", "only_one"])
    else:
        snapshot["selected_tests"] = ["tests/test_unreviewed.py::test_unknown"]
    reseal(snapshot)
    assert not identity_valid(snapshot)
    assert passed(snapshot)["status"] == "BLOCKED"


def test_fresh_public_capture_checks_actual_manifest_membership_even_with_new_selection_hash(public_checkout):
    spec = public_spec(public_checkout)
    spec["selected_tests"] = ["tests/test_unreviewed.py::test_unknown"]
    spec["scope"]["public_inputs"]["selected_tests_sha256"] = digest(spec["selected_tests"])
    with pytest.raises(ValueError, match="actual source-owned manifest"):
        capture_identity(**{**spec, "repo_root": Path(spec["repo_root"])})


@pytest.mark.parametrize("mode", ("declared", "audited"))
def test_generated_public_exclusion_does_not_weaken_real_raw_modes(public_checkout, mode):
    spec = public_spec(public_checkout)
    spec["corpus"]["mode"] = mode
    with pytest.raises(ValueError, match="raw"):
        identity(spec)


def test_actual_manifest_drift_keeps_old_snapshot_historic_and_blocks_fresh_capture(public_checkout):
    spec = public_spec(public_checkout)
    before = identity(spec)
    path = public_checkout / "src/sciplot_core/verification/input_scope_manifest.json"
    path.write_text(path.read_text() + "\n")
    assert identity_valid(before)  # Offline historical validation reads no source.
    with pytest.raises(ValueError, match="manifest"):
        identity(spec)


@pytest.mark.parametrize("mutation", ("new_public", "new_helper", "delete_public", "same_byte_alias", "helper_alias"))
def test_public_membership_is_rechecked_without_reading_private_bytes(public_checkout, mutation):
    spec = public_spec(public_checkout, generated_only=mutation in {"new_public", "new_helper", "helper_alias"})
    before = identity(spec)
    receipt = passed(before)
    fixture = public_checkout / "tests/fixtures"
    if mutation == "new_public":
        (fixture / "new_public.csv").write_text("x,y\n0,3\n")
    elif mutation == "new_helper":
        (public_checkout / "tests/new_helper.py").write_text("value = 3\n")
    elif mutation == "helper_alias":
        (public_checkout / "tests/new_helper.py").symlink_to(public_checkout / "tests/test_unit.py")
    elif mutation == "delete_public":
        (fixture / "raw.csv").unlink()
    else:
        raw = fixture / "raw.csv"
        target = public_checkout / "generated-alias-target.csv"
        target.write_bytes(raw.read_bytes())
        raw.unlink()
        raw.symlink_to(target)
    with pytest.raises(ValueError, match="Public test/input|discovery|identity input domain"):
        identity(spec)
    assert identity_valid(before)
    assert receipt["status"] == "PASS"  # Historical unit result only, no new reuse.


def test_private_fixture_members_do_not_enter_public_namespace_binding(public_checkout):
    spec = public_spec(public_checkout)
    before = identity(spec)
    private = public_checkout / "tests/fixtures/real_world"
    private.mkdir()
    (private / "unreadable.csv").symlink_to(public_checkout / "missing-private-target")
    assert identity(spec) == before


@pytest.mark.parametrize("domain", ("python", "inventory", "corpus_policy"))
def test_public_policy_cannot_omit_required_real_identity_domains(public_checkout, domain):
    spec = public_spec(public_checkout)
    spec["inputs"][domain] = {"not_applicable": "generated behavior"}
    spec["scope"]["excluded_domains"][domain] = "generated behavior"
    with pytest.raises(ValueError, match="required domain|Public manifest"):
        identity(spec)
