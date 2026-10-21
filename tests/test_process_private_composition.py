"""Literal same-launch composition and finite socket fact controls."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import subprocess

import pytest

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from process_private_descriptor_support import descriptor_boundary


@pytest.fixture
def boundary(tmp_path):
    with descriptor_boundary(tmp_path) as module:
        yield module


@pytest.fixture
def domains(tmp_path, boundary):
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


def test_active_source_is_exact_and_caller_target_facts_are_separate(domains, boundary):
    outer, inner = domains
    target = (str(boundary.DESCRIPTOR_TARGET), "literal-target")
    environment = {"INNER_ROUTING": "inner", "OUTER_ROUTING": "old", "KEEP": "literal"}
    with boundary.wrap_private_exclusion(inner, target, environment=environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, drop_environment=["INNER_ROUTING"]) as source:
        changed = dict(environment, OUTER_ROUTING="new")
        inputs = dict(stdio=source.stdio, drop_environment=["OUTER_ROUTING"])
        reference = boundary.source_private_exclusion(source.argv, changed, **inputs)
        assert reference is not None and reference[1] == ("INNER_ROUTING",)
        assert boundary.source_private_exclusion((str(boundary.DESCRIPTOR_TARGET),), changed, **inputs) is None
        caller = boundary.actual_launch_facts(reference[0], source.argv, changed, stdio=source.stdio,
            drop_environment=reference[1])
        with boundary.wrap_private_exclusion(outer, source.argv, environment=changed, stdin=source.stdio[0],
                stdout=source.stdio[1], stderr=source.stdio[2], drop_environment=["OUTER_ROUTING"]) as combined:
            descriptor = boundary.invocation_snapshot(combined)
            actual = boundary.actual_launch_facts(descriptor, combined.argv, combined.environment,
                stdio=combined.stdio, drop_environment=["INNER_ROUTING", "OUTER_ROUTING"])
            assert combined.argv.count(str(boundary.SANDBOX)) == 1
            assert combined.argv[-2:] == target
            assert actual["suffix_sha256"] != canonical_json_sha256(list(source.argv))
            assert set(descriptor.to_dict()["roots"]) == set(outer.to_dict()["roots"]) | set(inner.to_dict()["roots"])
            arguments = dict(expected_snapshot=outer, original_argv_sha256=canonical_json_sha256(list(source.argv)),
                original_environment_sha256=canonical_json_sha256(changed), original_cwd=str(Path.cwd()),
                original_executable_sha256=hashlib.sha256(boundary.SANDBOX.read_bytes()).hexdigest(),
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
def test_matching_source_argv_cannot_hide_changed_inputs(domains, change, boundary):
    with boundary.wrap_private_exclusion(domains[1], [str(boundary.DESCRIPTOR_TARGET)], environment={"KEEP": "one"},
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


def test_inactive_prefix_is_not_a_source_owned_launch(domains, boundary):
    with boundary.wrap_private_exclusion(domains[1], [str(boundary.DESCRIPTOR_TARGET)], environment={},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as source:
        saved = source.argv
    assert boundary.source_private_exclusion(saved, {}, stdio=source.stdio) is None


def test_finite_socket_literals_and_mutation_rule_match_the_actual_probed_contract(tmp_path, boundary):
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


@pytest.mark.parametrize("case,expected", [("subset", ["cold-engine.sock", "engine.sock"]),
    ("partial", ["engine.sock"]), ("disjoint", []), ("other_directory", [])])
def test_finite_permissions_intersect_within_the_same_attested_namespace(tmp_path, boundary, case, expected):
    left = finite_socket_scope(tmp_path)
    directory = Path(left["sockets"][0]).parent
    right = copy.deepcopy(left)
    if case == "subset":
        left["sockets"].append(str(directory / "extra-engine.sock"))
    elif case == "partial":
        right["sockets"] = [str(directory / "engine.sock"), str(directory / "extra-engine.sock")]
    elif case == "disjoint":
        left["sockets"], right["sockets"] = [str(directory / "cold-engine.sock")], [str(directory / "engine.sock")]
    else:
        (tmp_path / "other").mkdir()
        right = finite_socket_scope(tmp_path / "other")
    outer = boundary.prepare_private_exclusion(tmp_path / "outer", {}, socket_scope=left)
    inner = boundary.prepare_private_exclusion(tmp_path / "inner", {}, socket_scope=right)
    for first, second in ((outer, inner), (inner, outer)):
        composed = boundary.compose_private_exclusion(first, second)
        boundary.validate_private_exclusion(composed)
        actual = composed.to_dict()["socket_scope"]
        if not expected:
            assert actual is None
        else:
            assert actual == {"sockets": [str(directory / name) for name in expected],
                "directory": left["directory"], "initial_absent": True}


@pytest.mark.parametrize("change", ["newness", "mode", "inode", "uid", "outside", "duplicate", "symlink", "ordinary_file"])
def test_unknown_existing_or_replaced_socket_scope_fails_closed(tmp_path, change, boundary):
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
