"""Literal same-launch composition and finite socket fact controls."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import subprocess

import pytest

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.verification import process_private_exclusion as boundary


@pytest.fixture
def domains(tmp_path):
    result = []
    for name in ("outer", "inner"):
        root = tmp_path / name
        private = root / "tests/fixtures/real_world"
        private.mkdir(parents=True)
        (private / "literal.txt").write_bytes(name.encode())
        result.append(boundary.prepare_private_exclusion(root, {}))
    return result


def finite_socket_scope(tmp_path):
    directory = tmp_path / "fresh-node-sockets"
    directory.mkdir(mode=0o700)
    directory = directory.resolve()
    assert not list(directory.iterdir())
    value = directory.stat()
    return {"sockets": [str(directory / "cold-engine.sock"), str(directory / "engine.sock")],
        "directory": {"device": value.st_dev, "inode": value.st_ino, "uid": value.st_uid, "mode": 0o700},
        "initial_absent": True}


def test_active_source_is_exact_and_caller_target_facts_are_separate(domains):
    outer, inner = domains
    target = ("/usr/bin/true", "literal-target")
    environment = {"INNER_ROUTING": "inner", "OUTER_ROUTING": "old", "KEEP": "literal"}
    with boundary.wrap_private_exclusion(inner, target, environment=environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, drop_environment=["INNER_ROUTING"]) as source:
        changed = dict(environment, OUTER_ROUTING="new")
        inputs = dict(stdio=source.stdio, drop_environment=["OUTER_ROUTING"])
        reference = boundary.source_private_exclusion(source.argv, changed, **inputs)
        assert reference is not None and reference[1] == ("INNER_ROUTING",)
        assert boundary.source_private_exclusion(("/usr/bin/true",), changed, **inputs) is None
        caller = boundary.actual_launch_facts(reference[0], source.argv, changed, stdio=source.stdio,
            drop_environment=reference[1])
        with boundary.wrap_private_exclusion(outer, source.argv, environment=changed, stdin=source.stdio[0],
                stdout=source.stdio[1], stderr=source.stdio[2], drop_environment=["OUTER_ROUTING"]) as combined:
            descriptor = boundary.invocation_snapshot(combined)
            actual = boundary.actual_launch_facts(descriptor, combined.argv, combined.environment,
                stdio=combined.stdio, drop_environment=["INNER_ROUTING", "OUTER_ROUTING"])
            assert combined.argv.count("/usr/bin/sandbox-exec") == 1
            assert combined.argv[-2:] == target
            assert actual["suffix_sha256"] != canonical_json_sha256(list(source.argv))
            assert set(descriptor.to_dict()["roots"]) == set(outer.to_dict()["roots"]) | set(inner.to_dict()["roots"])
            arguments = dict(expected_snapshot=outer, original_argv_sha256=canonical_json_sha256(list(source.argv)),
                original_environment_sha256=canonical_json_sha256(changed), original_cwd=str(Path.cwd()),
                original_executable_sha256=hashlib.sha256(Path("/usr/bin/sandbox-exec").read_bytes()).hexdigest(),
                original_stdio=boundary.original_stdio_facts(*source.stdio), actual_launch=actual,
                caller_launch=caller, drop_environment=["OUTER_ROUTING"])
            boundary.validate_excluded_proof(combined.proof, **arguments)
            for field in ("argv_sha256", "prefix_sha256", "suffix_sha256", "launch_environment_sha256", "stdio", "flags"):
                corrupted = copy.deepcopy(caller)
                corrupted[field] = "changed"
                with pytest.raises(ValueError):
                    boundary.validate_excluded_proof(combined.proof, **dict(arguments, caller_launch=corrupted))
            with pytest.raises(ValueError):
                boundary.validate_excluded_proof(combined.proof, **dict(arguments, caller_launch=None))


@pytest.mark.parametrize("change", ["environment", "stdio", "cwd"])
def test_matching_source_argv_cannot_hide_changed_inputs(domains, change):
    with boundary.wrap_private_exclusion(domains[1], ["/usr/bin/true"], environment={"KEEP": "one"},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as source:
        environment, stdio, cwd = source.environment, source.stdio, None
        if change == "environment":
            environment = {"KEEP": "two"}
        elif change == "stdio":
            stdio = (subprocess.PIPE, *source.stdio[1:])
        else:
            cwd = Path("/")
        with pytest.raises(ValueError, match="no longer matches"):
            boundary.source_private_exclusion(source.argv, environment, stdio=stdio, cwd=cwd)


def test_inactive_prefix_is_not_a_source_owned_launch(domains):
    with boundary.wrap_private_exclusion(domains[1], ["/usr/bin/true"], environment={},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as source:
        saved = source.argv
    assert boundary.source_private_exclusion(saved, {}, stdio=source.stdio) is None


def test_finite_socket_literals_and_mutation_rule_match_the_actual_probed_contract(tmp_path):
    scope = finite_socket_scope(tmp_path)
    descriptor = boundary.prepare_private_exclusion(tmp_path / "origin", {}, socket_scope=scope)
    value = descriptor.to_dict()
    assert value["socket_scope"] == scope
    assert "(deny network-outbound)" in value["profile"]
    for name in scope["sockets"]:
        assert f'(allow network-outbound (literal "{name}"))' in value["profile"]
        assert f'(require-not (literal "{name}"))' in value["profile"]
    assert "(deny file-write* file-link (require-all (vnode-type SOCKET)" in value["profile"]
    assert str(Path(scope["sockets"][0]).parent) in value["ancestors"]
    boundary.validate_private_exclusion(descriptor)
    without = boundary.prepare_private_exclusion(tmp_path / "second", {})
    assert "(allow network-outbound" not in without.to_dict()["profile"]
    assert boundary.compose_private_exclusion(descriptor, without).to_dict()["socket_scope"] is None


@pytest.mark.parametrize("change", ["newness", "mode", "inode", "uid", "outside", "duplicate", "symlink", "ordinary_file"])
def test_unknown_existing_or_replaced_socket_scope_fails_closed(tmp_path, change):
    scope = finite_socket_scope(tmp_path)
    directory = Path(scope["sockets"][0]).parent
    if change == "newness":
        scope["initial_absent"] = False
    elif change == "mode":
        directory.chmod(0o755)
    elif change == "inode":
        scope["directory"]["inode"] += 1
    elif change == "uid":
        scope["directory"]["uid"] += 1
    elif change == "outside":
        scope["sockets"].append(str(tmp_path / "borrowed.sock"))
        scope["sockets"].sort()
    elif change == "duplicate":
        scope["sockets"].append(scope["sockets"][-1])
    elif change == "symlink":
        Path(scope["sockets"][0]).symlink_to(tmp_path / "outside.sock")
    else:
        Path(scope["sockets"][0]).write_bytes(b"not a socket")
    with pytest.raises(ValueError):
        boundary.prepare_private_exclusion(tmp_path / "origin", {}, socket_scope=scope)
