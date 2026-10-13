"""Scoped reads construct only contracts that can appear in their response."""

import json
from pathlib import Path

import pytest
from test_managed_description_scopes import _service, _wire_size

from sciplot_core.plot_engine import figure_updates, managed_description
from sciplot_core.plot_engine import service as service_module
from sciplot_core.plot_ir.figure_document import figure_spec
from sciplot_core.verification import build_changed_verification_plan


def test_performance_regression_is_owned_by_plot_verification():
    path = "tests/test_managed_description_performance.py"
    plan = build_changed_verification_plan([path], repo_root=Path(__file__).resolve().parents[1])
    assert plan["unowned_paths"] == []
    assert [owner["owner_id"] for owner in plan["owners"]] == ["semantic_plot_engine"]
    checks = {check["check_id"]: check["command"] for check in plan["checks"]}
    assert path in checks["pytest_changed_owners"]


def test_selective_figure_contracts_share_the_full_owner(tmp_path, monkeypatch):
    service, root, document = _service(tmp_path, monkeypatch)
    spec = figure_spec(document)
    full = figure_updates.patch_capabilities(spec)
    names = figure_updates.figure_property_names(spec)
    assert names == {target: list(properties) for target, properties in full.items()}
    for target, properties in full.items():
        for name, descriptor in properties.items():
            assert figure_updates.figure_edit_descriptor(spec, target, name) == descriptor

    # The shared enumeration and factory preserve the existing full wire order.
    described = service.describe(root)
    assert json.dumps(described["figure_edit_contract"], separators=(",", ":")) == json.dumps(full, separators=(",", ":"))


@pytest.mark.parametrize("scope", ["summary", "edit"])
def test_scoped_figure_skips_discarded_contracts_and_keys(tmp_path, monkeypatch, scope):
    service, root, _ = _service(tmp_path, monkeypatch)
    selector = ({"scope": "summary"} if scope == "summary" else
                {"scope": "edit", "target": "scale:x", "property": "scale.domain"})
    full_before = service.describe(root)
    scoped_before = service.describe(root, description=selector)
    calls = {"all_contracts": 0, "early_dependencies": 0, "saved_build_keys": 0}

    def count(module, name, key):
        original = getattr(module, name)

        def wrapper(*args, **kwargs):
            calls[key] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, wrapper)

    count(figure_updates, "patch_capabilities", "all_contracts")
    count(service_module, "dependency_state", "early_dependencies")
    count(managed_description, "build_keys", "saved_build_keys")
    scoped_after = service.describe(root, description=selector)
    assert scoped_after == scoped_before
    assert calls == {"all_contracts": 0, "early_dependencies": 0, "saved_build_keys": 0}
    assert scoped_after["dependencies"]["invalidated"] == full_before["dependencies"]["invalidated"]
    assert _wire_size(scoped_after) == _wire_size(scoped_before)

    full_after = service.describe(root)
    assert full_after == full_before
    assert calls == {"all_contracts": 1, "early_dependencies": 1, "saved_build_keys": 1}
    assert _wire_size(full_after) == _wire_size(full_before)


def test_scoped_v1_still_advertises_object_capabilities(tmp_path, monkeypatch):
    service, root, _ = _service(tmp_path, monkeypatch, figure=False)
    full = service.describe(root)
    summary = service.describe(root, description={"scope": "summary"})
    for target, value in summary["edit_targets"].items():
        assert value["properties"] == list(full["objects"][target]["capabilities"])
