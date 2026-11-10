"""Recorded generated data is external, bound once, and never swept."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys

import pytest

from sciplot_core.verification import changed_evidence, recorded_workspace as workspace
from sciplot_core.verification.evidence_identity import DOMAINS, capture_identity


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    state, cache = tmp_path / "state", tmp_path / "cache"
    monkeypatch.setattr(workspace, "user_state_path", lambda _app: state)
    monkeypatch.setattr(workspace, "user_cache_path", lambda _app: cache)
    return tmp_path, state, cache


def prepare(root, environment, *, legacy=False):
    effective = environment if legacy else {"SCIPLOT_VERIFY_FINISH": str(root / ".tmp_verify/run/finish.json"), **environment}
    return workspace.prepare_recorded_environment(root, effective, legacy=legacy)


def test_session_host_injection_is_per_node_lazy_and_uses_the_production_allocator(request, _recorded_test_host):
    from platformdirs import user_state_path
    from sciplot_core.foundation import research_destination

    node = hashlib.sha256(request.node.nodeid.encode("utf-8")).hexdigest()
    state = workspace.user_state_path("SciPlot")
    cache = workspace.user_cache_path("SciPlot")
    assert state == _recorded_test_host / node / "state"
    assert cache == _recorded_test_host / node / "cache"
    assert research_destination.user_cache_path("SciPlot") == cache
    assert isinstance(state, Path) and isinstance(cache, Path)
    assert state != user_state_path("SciPlot")
    assert not state.exists() and not cache.exists()
    environment, binding = prepare(state.parent, {"PATH": os.defpath})
    assert Path(binding["path"]).parent == state / "verification-workspaces"
    assert workspace.validate_recorded_workspace(environment) == binding
    with pytest.raises(ValueError, match="SciPlot"):
        research_destination.require_data_destination(cache / "development/future")
    assert not cache.exists()


def test_session_host_injection_preserves_the_real_source_and_fake_cache_refusals():
    source = Path(__file__).resolve().parents[1]
    for refused in (source / "uncreated-recorded-data", workspace.user_cache_path("SciPlot") / "development/future"):
        with pytest.raises(ValueError, match="SciPlot"):
            prepare(source, {"PYTEST_DEBUG_TEMPROOT": str(refused)})
        assert not refused.exists()


def test_new_runs_use_exclusive_state_directories_and_preserve_prior_contents(isolated):
    root, state, _cache = isolated
    original = {"PATH": os.defpath}
    first, binding = prepare(root, original)
    assert original == {"PATH": os.defpath}
    directory = Path(binding["path"])
    assert directory.parent == state / "verification-workspaces"
    assert first["PYTEST_DEBUG_TEMPROOT"] == str(directory)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    marker = directory / "interrupted-input.csv"
    marker.write_text("original\n")
    second, second_binding = prepare(root, original)
    assert second_binding["path"] != binding["path"]
    assert marker.read_text() == "original\n"
    assert workspace.validate_recorded_workspace(first) == binding
    assert workspace.validate_recorded_workspace(second) == second_binding
    # Rebuilding a spec uses its existing binding instead of another allocation.
    assert prepare(root, first) == (first, binding)
    assert len(list((state / "verification-workspaces").iterdir())) == 2


def test_explicit_external_root_is_an_untouched_parent(isolated):
    root, _state, _cache = isolated
    parent = root / "operator-root"
    parent.mkdir()
    retained = parent / "unknown-old-evidence"
    retained.write_text("keep")
    environment, binding = prepare(root, {"PYTEST_DEBUG_TEMPROOT": str(parent)})
    assert Path(binding["path"]).parent == parent
    assert retained.read_text() == "keep"
    assert environment["PYTEST_DEBUG_TEMPROOT"] != str(parent)


@pytest.mark.parametrize("destination", ["source", "cache", "source-alias"])
def test_code_and_cache_overrides_fail_before_creating_generated_data(isolated, destination):
    root, state, cache = isolated
    source = root / "checkout"
    (source / "src/sciplot_core").mkdir(parents=True)
    (source / "pyproject.toml").write_text('[project]\nname = "sciplot-core"\n')
    target = source / "future-pytest" if destination != "cache" else cache / "development/future-pytest"
    if destination == "source-alias":
        alias = root / "source-link"
        alias.symlink_to(source, target_is_directory=True)
        target = alias / "future-pytest"
    with pytest.raises(ValueError, match="SciPlot"):
        prepare(root, {"PYTEST_DEBUG_TEMPROOT": str(target)})
    assert not target.exists() and not state.exists() and not cache.exists()


def test_owned_development_override_is_removed_before_record_allocation(isolated):
    from sciplot_core.verification.development_storage import DEVELOPMENT_ROOT_KEY

    root, state, cache = isolated
    disposable = str(cache / "development/run-previous/pytest")
    environment, binding = prepare(root, {
        DEVELOPMENT_ROOT_KEY: disposable, "PYTEST_DEBUG_TEMPROOT": disposable,
    })
    assert DEVELOPMENT_ROOT_KEY not in environment
    assert Path(binding["path"]).is_relative_to(state)
    assert not cache.exists()


@pytest.mark.parametrize("addopts", ["--basetemp /outside", "--basetemp=/outside", "-o tmp_path_retention_policy=failed"])
def test_new_record_refuses_conflicting_pytest_temp_owners(isolated, addopts):
    root, state, _cache = isolated
    with pytest.raises(ValueError, match="PYTEST_ADDOPTS"):
        prepare(root, {"PYTEST_ADDOPTS": addopts})
    assert not state.exists()


@pytest.mark.parametrize("change", ["replace", "mode", "alias", "environment", "malformed"])
def test_fresh_binding_observes_directory_identity_not_mutable_contents(isolated, change):
    root, _state, _cache = isolated
    environment, binding = prepare(root, {"PATH": os.defpath})
    directory = Path(binding["path"])
    (directory / "created.csv").write_text("generated")
    assert workspace.validate_recorded_workspace(environment) == binding
    if change in {"replace", "alias"}:
        moved = directory.with_name(directory.name + "-original")
        directory.rename(moved)
        if change == "replace":
            directory.mkdir(mode=0o700)
        else:
            directory.symlink_to(moved, target_is_directory=True)
    elif change == "mode":
        directory.chmod(0o750)
    elif change == "environment":
        environment["PYTEST_DEBUG_TEMPROOT"] = str(directory.parent)
    else:
        environment[workspace.BINDING_ENV] = "{}"
    with pytest.raises(ValueError, match="workspace"):
        workspace.validate_recorded_workspace(environment)


def test_legacy_environment_does_not_allocate_or_infer_a_workspace(isolated):
    root, state, _cache = isolated
    old = {"PATH": os.defpath, "PYTEST_DEBUG_TEMPROOT": str(root / "old-location")}
    assert prepare(root, old, legacy=True) == (old, None)
    assert workspace.validate_recorded_workspace(old) is None
    assert not state.exists() and not (root / "old-location").exists()


def test_capture_requires_matching_new_scope_and_rechecks_directory_identity(isolated):
    root, _state, _cache = isolated
    inputs = {}
    for domain in DOMAINS:
        path = root / domain
        path.write_text(domain)
        inputs[domain] = {"paths": [str(path)]}
    environment, binding = prepare(root, {"PATH": os.defpath})
    spec = {"repo_root": root, "command": [sys.executable, "-c", "pass"],
            "scope": {"kind": "process", "closure_policy": "synthetic workspace contract", "recorded_workspace": binding},
            "selected_tests": [], "inputs": inputs, "environment": environment,
            "corpus": {"mode": "synthetic", "complete": True, "policy": "synthetic"}}
    before = capture_identity(**spec)
    (Path(binding["path"]) / "new.csv").write_text("output")
    assert capture_identity(**spec) == before
    with pytest.raises(ValueError, match="scope and environment"):
        capture_identity(**{**spec, "scope": {**spec["scope"], "recorded_workspace": {**binding, "inode": -1}}})
    # A historical/handwritten helper may inherit an outer marker without a
    # new scope field; its actual environment is still sealed and checked.
    assert capture_identity(**{**spec, "scope": {"kind": "process", "closure_policy": "synthetic"}})
    Path(binding["path"]).chmod(0o750)
    with pytest.raises(ValueError, match="directory identity"):
        capture_identity(**spec)
    old_scope = {"kind": "process", "closure_policy": "historical synthetic"}
    assert capture_identity(**{**spec, "scope": old_scope, "environment": {"PATH": os.defpath}})


@pytest.mark.parametrize("bound", [False, True])
def test_changed_reuse_rebuilds_only_the_known_request_workspace(isolated, monkeypatch, bound):
    from sciplot_core.verification import evidence_scope

    root, state, _cache = isolated
    output = root / ".tmp_verify/recorded"
    check_dir = output / "pytest_changed_owners"
    check_dir.mkdir(parents=True)
    environment, binding = prepare(root, {"PATH": os.defpath,
                                         "SCIPLOT_VERIFY_FINISH": str(check_dir / "finish.json")}) if bound else ({}, None)
    scope = {"recorded_workspace": binding} if bound else {}
    (check_dir / "request.json").write_text(json.dumps({"scope": scope}))
    monkeypatch.delenv(workspace.BINDING_ENV, raising=False)
    monkeypatch.delenv("PYTEST_DEBUG_TEMPROOT", raising=False)
    observed = []
    def builder(plan, check, repo, **kwargs):
        assert kwargs["_legacy_workspace"] is True
        effective, current = workspace.prepare_recorded_environment(repo, kwargs["environment"], legacy=kwargs["_legacy_workspace"])
        observed.append(current)
        return {"environment": effective}
    monkeypatch.setattr(evidence_scope, "build_check_spec", builder)
    plan = {"checks": [{"check_id": "pytest_changed_owners", "command": []}]}
    specs = changed_evidence._prepare_specs(plan, root, output)
    assert observed == [binding]
    if bound:
        assert specs[0]["environment"][workspace.BINDING_ENV] == environment[workspace.BINDING_ENV]
        assert list((state / "verification-workspaces").iterdir()) == [Path(binding["path"])]
    else:
        assert workspace.BINDING_ENV not in specs[0]["environment"] and not state.exists()
