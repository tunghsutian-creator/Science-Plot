"""Literal generated admission/descriptor controls; no corpus inputs."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.verification import process_private_exclusion as boundary


@pytest.fixture
def resources(tmp_path):
    origin = tmp_path / "origin"
    private = origin / "tests/fixtures/real_world"
    private.mkdir(parents=True)
    canary = private / "generated.txt"
    canary.write_bytes(b"literal generated protected bytes\n")
    audit = tmp_path / "outer-audit"
    audit.mkdir()
    evidence = audit / "outer.jsonl"
    evidence.write_bytes(b"literal generated outer evidence\n")
    return origin, canary, audit, evidence


def snapshot(resources):
    origin, _, audit, _ = resources
    return boundary.prepare_private_exclusion(origin, {}, audit_directory=audit)


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def validate(invocation, frozen, *, drop=(), stdio=(subprocess.DEVNULL, subprocess.PIPE, subprocess.PIPE), actual=None):
    descriptor = frozen if isinstance(frozen, boundary.ExclusionSnapshot) else boundary.ExclusionSnapshot(json.dumps(frozen))
    launch = boundary.actual_launch_facts(descriptor, invocation.argv if actual is None else actual,
        invocation.environment, stdio=invocation.stdio, drop_environment=drop)
    boundary.validate_excluded_proof(invocation.proof, expected_snapshot=frozen,
        original_argv_sha256=sha(["/usr/bin/true"]), original_environment_sha256=sha({}),
        original_stdio=boundary.original_stdio_facts(*stdio), actual_launch=launch,
        original_executable_sha256=hashlib.sha256(Path("/usr/bin/true").read_bytes()).hexdigest(), original_cwd=str(Path.cwd()),
        drop_environment=drop)


def test_exact_origin_stage_domains_missing_roots_and_metadata_only(resources, tmp_path, monkeypatch):
    origin, canary, audit, _ = resources
    stage = tmp_path / "stage"
    stage.mkdir()
    original = Path.read_bytes
    def read(path):
        if path == canary:
            pytest.fail("Protected measurement bytes must not be opened by admission")
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", read)
    frozen = boundary.prepare_private_exclusion(origin, {}, stage_root=stage, audit_directory=audit)
    literal = {str(root / relative) for root in (origin, stage) for relative in (
        "tests/fixtures/real_world", "tests/fixtures/polymer_corpus", "tests/fixtures/archived_output_raw_data",
        "tests/fixtures/rendering_profiles", ".local/reference_data/real_world", ".local/reference_data/polymer_corpus",
        ".local/reference_data/archived_sources")}
    data = frozen.to_dict()
    assert set(data["roots"]) == literal
    assert data["members"][str(stage / "tests/fixtures/real_world")] is None
    assert data["members"][str(canary)]["st_nlink"] == 1
    boundary.validate_private_exclusion(json.loads(json.dumps(data)))


@pytest.mark.parametrize("change", ["same_bytes", "new_member", "new_root", "inode", "hardlink"])
def test_complete_membership_and_same_byte_identity_drift_refused(resources, tmp_path, change):
    origin, canary, _, _ = resources
    frozen = snapshot(resources)
    content = canary.read_bytes()
    if change == "same_bytes":
        canary.write_bytes(content)
    elif change == "new_member":
        (canary.parent / "new.txt").write_bytes(b"generated")
    elif change == "new_root":
        (origin / "tests/fixtures/polymer_corpus").mkdir()
    elif change == "inode":
        replacement = tmp_path / "replacement"
        replacement.write_bytes(content)
        replacement.replace(canary)
    else:
        os.link(canary, tmp_path / "outside-hardlink")
    assert canary.read_bytes() == content
    with pytest.raises(ValueError, match="drift|single-link"):
        boundary.validate_private_exclusion(frozen)


def test_preexisting_hardlink_is_admission_failure(resources, tmp_path):
    _, canary, _, _ = resources
    os.link(canary, tmp_path / "outside-readable-alias")
    assert canary.stat().st_nlink == 2
    with pytest.raises(ValueError, match="single-link"):
        snapshot(resources)


@pytest.mark.parametrize("location", ["member", "ancestor"])
def test_internal_and_ancestor_symlinks_fail_closed(resources, tmp_path, location):
    origin, canary, audit, _ = resources
    if location == "member":
        (canary.parent / "escape").symlink_to(tmp_path)
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(origin, target_is_directory=True)
        origin = alias
    with pytest.raises(ValueError, match="symlink"):
        boundary.prepare_private_exclusion(origin, {}, audit_directory=audit)


@pytest.mark.parametrize("options", [
    {"shell": True}, {"executable": "/usr/bin/false"}, {"close_fds": False},
    {"pass_fds": (7,)}, {"preexec_fn": lambda: None}, {"stdin": subprocess.STDOUT},
])
def test_unsafe_or_nonpreserved_popen_forms_rejected(resources, options):
    frozen = snapshot(resources)
    with pytest.raises(ValueError, match="Unsupported|unsafe"):
        boundary.wrap_private_exclusion(frozen, ["/usr/bin/true"], environment={}, **options)


@pytest.mark.parametrize("target", ["raw", "audit"])
@pytest.mark.parametrize("endpoint", ["stdin", "stdout", "stderr"])
def test_every_bound_endpoint_refuses_raw_or_outer_evidence_inode(resources, target, endpoint):
    _, canary, _, evidence = resources
    frozen = snapshot(resources)
    with (canary if target == "raw" else evidence).open("rb") as stream:
        with pytest.raises(ValueError, match="protected"):
            boundary.wrap_private_exclusion(frozen, ["/usr/bin/true"], environment={}, **{endpoint: stream})


def test_duplicate_is_the_actual_checked_endpoint_and_is_closed(resources, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    with first.open("ab") as original, second.open("ab") as replacement:
        expected = os.fstat(original.fileno()).st_ino
        with boundary.wrap_private_exclusion(snapshot(resources), ["/usr/bin/true"], environment={},
                stdin=subprocess.DEVNULL, stdout=original, stderr=subprocess.PIPE) as invocation:
            actual_fd = invocation.stdio[1]
            os.dup2(replacement.fileno(), original.fileno())
            assert os.fstat(actual_fd).st_ino == expected
            assert os.fstat(original.fileno()).st_ino == second.stat().st_ino
            validate(invocation, invocation.proof["snapshot"], stdio=(subprocess.DEVNULL, original, subprocess.PIPE))
        with pytest.raises(OSError):
            os.fstat(actual_fd)


def test_none_inheritance_is_held_and_pipe_sentinels_preserve_semantics(resources):
    with boundary.wrap_private_exclusion(snapshot(resources), ["/usr/bin/true"], environment={}) as invocation:
        assert all(row["kind"] == "inherit" for row in invocation.proof["original"]["stdio"])
        assert all(row["kind"] == "bound_fd" for row in invocation.proof["actual"]["stdio"])
        assert all(os.fstat(fd) for fd in invocation.stdio)
    with boundary.wrap_private_exclusion(snapshot(resources), ["/usr/bin/true"], environment={},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as invocation:
        assert invocation.stdio == (subprocess.PIPE, subprocess.PIPE, subprocess.STDOUT)


def test_closed_proof_serialization_and_independent_literal_bindings(resources):
    frozen = snapshot(resources)
    with boundary.wrap_private_exclusion(frozen, ["/usr/bin/true"], environment={},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as invocation:
        validate(invocation, frozen)
        assert invocation.argv[0] == "/usr/bin/sandbox-exec"
        assert invocation.argv[-2:] == ("--", "/usr/bin/true")
        for change in ("extra", "profile", "original", "actual", "fd", "drop", "executable", "cwd"):
            corrupt = copy.deepcopy(invocation.proof)
            if change == "extra":
                corrupt["unknown"] = True
            elif change == "profile":
                corrupt["snapshot"]["profile"] = "(allow default)"
            elif change in {"original", "actual"}:
                corrupt[change]["argv_sha256"] = "0" * 64
            elif change == "drop":
                corrupt["drop_environment"] = ["PATH"]
            elif change == "executable":
                corrupt["original"]["executable"]["sha256"] = "0" * 64
            elif change == "cwd":
                corrupt["original"]["cwd"] = "/unknown"
            else:
                raw = frozen.to_dict()["members"][str(resources[1])]
                corrupt["original"]["stdio"][0] = {"kind": "fd"}
                corrupt["actual"]["stdio"][0] = {"kind": "bound_fd", "device": raw["st_dev"], "inode": raw["st_ino"], "mode": raw["st_mode"]}
            original = invocation.proof
            invocation.proof = corrupt
            with pytest.raises(ValueError):
                validate(invocation, frozen)
            invocation.proof = original


def test_plaintext_argument_and_environment_values_not_in_proof(resources):
    secret = "GENERATED_SECRET_VALUE_NEVER_PERSIST_THIS"
    with boundary.wrap_private_exclusion(snapshot(resources), ["/usr/bin/true", secret], environment={"TOKEN": secret},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as invocation:
        assert secret not in json.dumps(invocation.proof)


def test_synchronized_total_hash_cannot_replace_the_kernel_prefix(resources):
    frozen = snapshot(resources)
    with boundary.wrap_private_exclusion(frozen, ["/usr/bin/true"], environment={},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as invocation:
        invocation.proof["actual"]["argv_sha256"] = sha(["/usr/bin/true"])
        with pytest.raises(ValueError):
            validate(invocation, frozen, actual=("/usr/bin/true",))


@pytest.mark.parametrize("corruption", ["sentinel", "inode", "flags", "target_environment", "prefix", "suffix"])
def test_actual_bound_facts_are_independent_of_synchronized_proof_fields(resources, corruption):
    frozen = snapshot(resources)
    with boundary.wrap_private_exclusion(frozen, ["/usr/bin/true"], environment={},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as invocation:
        actual = invocation.proof["actual"]
        if corruption == "sentinel":
            invocation.proof["original"]["stdio"][1] = {"kind": "sentinel", "value": subprocess.DEVNULL}
            actual["stdio"][1] = {"kind": "sentinel", "value": subprocess.DEVNULL}
        elif corruption == "inode":
            actual["stdio"][1] = {"kind": "bound_fd", "device": 123, "inode": 456, "mode": 789}
        elif corruption == "flags":
            actual["flags"]["close_fds"] = False
        else:
            actual[corruption + "_sha256"] = "0" * 64
        with pytest.raises(ValueError):
            validate(invocation, frozen)


@pytest.mark.parametrize("options", [{"close_fds": False}, {"pass_fds": (1,)}, {"shell": True},
    {"executable": "/usr/bin/true"}, {"preexec_fn": lambda: None}])
def test_actual_launch_facts_refuse_unsafe_final_flags(resources, options):
    with pytest.raises(ValueError, match="Unsafe actual"):
        boundary.actual_launch_facts(snapshot(resources), ("/usr/bin/true",), {},
            stdio=(subprocess.DEVNULL, subprocess.PIPE, subprocess.PIPE), **options)


def test_reviewed_runtime_loader_owner_is_shared_and_unknown_overrides_refused(resources):
    from sciplot_core.verification.evidence_runtime import runtime_loader_environment
    assert runtime_loader_environment({"DYLD_FRAMEWORK_PATH": "literal/frameworks", "KEEP": "value"}) == {"DYLD_FRAMEWORK_PATH": "literal/frameworks"}
    for key in ("DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
        with pytest.raises(ValueError, match="loader overrides"):
            runtime_loader_environment({key: "unreviewed"})
        with pytest.raises(ValueError, match="loader projection"):
            boundary.actual_launch_facts(snapshot(resources), ("/usr/bin/true",), {key: ""},
                stdio=(subprocess.DEVNULL, subprocess.PIPE, subprocess.PIPE))


def test_launch_and_target_environment_bind_drops_and_restoration_separately(resources):
    environment = {"DYLD_FRAMEWORK_PATH": "literal/frameworks", "ROUTING": "outer", "KEEP": "yes"}
    frozen = snapshot(resources)
    with boundary.wrap_private_exclusion(frozen, ["/usr/bin/true"], environment=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, drop_environment=["ROUTING"]) as invocation:
        actual = boundary.actual_launch_facts(frozen, invocation.argv, invocation.environment,
            stdio=invocation.stdio, drop_environment=["ROUTING"])
        assert actual["launch_environment_sha256"] == sha(environment)
        assert actual["target_environment_sha256"] == sha({"DYLD_FRAMEWORK_PATH": "literal/frameworks", "KEEP": "yes"})
        assert invocation.argv[-2:] == ("DYLD_FRAMEWORK_PATH=literal/frameworks", "/usr/bin/true")
        assert actual["suffix_sha256"] == sha(["/usr/bin/true"])


def test_protected_executable_rejected_without_opening_data(resources, monkeypatch):
    frozen = snapshot(resources)
    canary = resources[1]
    original = Path.read_bytes
    def read(path):
        if path == canary:
            pytest.fail("Admission opened a protected program as data")
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", read)
    with pytest.raises(ValueError, match="before reading"):
        boundary.wrap_private_exclusion(frozen, [str(canary)], environment={})


def test_unknown_platform_and_missing_capability_are_refused(resources, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "unproved-platform")
        with pytest.raises(ValueError, match="actual Mac"):
            snapshot(resources)
    monkeypatch.setattr(boundary, "SANDBOX", resources[0] / "absent-sandbox")
    with pytest.raises((OSError, ValueError)):
        snapshot(resources)
