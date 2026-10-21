"""Scoped reads construct only contracts that can appear in their response."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_managed_description_scopes import _service, _wire_size

from sciplot_core.plot_engine import figure_updates, managed_description
from sciplot_core.plot_engine import service as service_module
from sciplot_core.plot_engine.managed_source_revision import source_descriptor, source_value
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

    # Figure and virtual-source fields retain their own one descriptor owner.
    described = service.describe(root)
    expected = deepcopy(full)
    for source in document["scientific"]["data_sources"]:
        target = "source:" + source["source_id"]
        expected[target] = {"source.sha256": source_descriptor(document, target, root=root)}
        edit = service.describe(root, description={"scope": "edit", "target": target, "property": "source.sha256"})
        assert edit["figure_edit_contract"] == {target: expected[target]}
        assert edit["current_value"] == source_value(document, target, root=root)
        assert edit["current_value"]["sha256"] == source["sha256"]
        assert list(edit["current_value"]["bindings"]) == [source["source_id"]]
        assert target not in described["objects"]
    assert json.dumps(described["figure_edit_contract"], separators=(",", ":")) == json.dumps(expected, separators=(",", ":"))


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
    service, root, document = _service(tmp_path, monkeypatch, figure=False)
    full = service.describe(root)
    summary = service.describe(root, description={"scope": "summary"})
    for target, obj in full["objects"].items():
        assert summary["edit_targets"][target]["properties"] == list(obj["capabilities"])
    source_targets = {"source:" + source["source_id"] for source in document["scientific"]["data_sources"]}
    assert set(summary["edit_targets"]) == set(full["objects"]) | source_targets
    for target in source_targets:
        assert target not in full["objects"]
        assert summary["edit_targets"][target] == {"kind": "source", "label": target.removeprefix("source:"),
                                                    "properties": ["source.sha256"]}
        edit = service.describe(root, description={"scope": "edit", "target": target, "property": "source.sha256"})
        assert edit["object_edit_contract"] == {target: full["object_edit_contract"][target]}
        assert edit["object_edit_contract"][target]["source.sha256"] == source_descriptor(document, target, root=root)


@pytest.mark.parametrize("figure", [True, False])
def test_stale_source_edit_has_an_actionable_scientific_step_without_parsing(tmp_path, monkeypatch, figure):
    from sciplot_core.plot_engine import content_store, managed_sources
    from sciplot_core.plot_engine.managed_updates import prepare_update
    from sciplot_core.plot_document import validate_patch

    service, root, document = _service(tmp_path, monkeypatch, figure=figure)
    source = document["scientific"]["data_sources"][0]
    target = "source:" + source["source_id"]
    graph = service_module.load_head(root)["binding"]["graph"]
    graph["nodes"][0]["dependencies"] = [target]
    graph["nodes"].insert(0, {"id": target, "kind": "source", "dependencies": [], "parameters": {},
                              "version": "1", "content_hash": source["sha256"]})
    Path(source["path"]).write_bytes(b"changed bytes; no measurement parse is authorized by a read")
    monkeypatch.setattr(service_module, "changed_inputs", lambda *_: [source["path"]])

    def forbidden(*_a, **_k):
        raise AssertionError("A descriptor read parsed raw data or unrelated CAS payloads")

    monkeypatch.setattr(managed_sources, "load_sources", forbidden)
    monkeypatch.setattr(content_store, "resolve_document_content", forbidden)
    before = deepcopy(document)
    files = {path: path.read_bytes() for path in (Path(source["path"]), root / "head.json")}
    summary = service.describe(root, description={"scope": "summary"})
    hint = summary["next_step"]
    edit = service.describe(root, description={"scope": hint["description_scope"], "target": hint["targets"][0],
                                               "property": hint["property"]})
    step = edit["next_step"]
    assert step["action"] == "plot.patch"
    assert step["plot"] == str(root) and step["target"] == target and step["property"] == "source.sha256"
    assert step["intent_class"] == "scientific" and step["base_revision"] == document["revision"]
    request = validate_patch({"plot_id": step["plot_id"], "base_revision": step["base_revision"],
        "intent_class": step["intent_class"], "idempotency_key": "explicit-noop-only",
        "changes": [{"op": "set", "target": [step["target"]], "property": step["property"],
                     "value": edit["current_value"]}]})
    updated, diff, _, _ = prepare_update(document, request, root=root)
    assert diff == [] and updated == document == before
    assert {path: path.read_bytes() for path in files} == files


@pytest.mark.parametrize("figure", [True, False])
@pytest.mark.parametrize("stored_binding", [True, False])
def test_source_contract_reads_only_its_frozen_binding_not_unrelated_cas_or_raw_tables(
        tmp_path, monkeypatch, figure, stored_binding):
    from sciplot_core.plot_document import seal_document
    from sciplot_core.plot_engine import content_store, managed_sources

    service, root, document = _service(tmp_path, monkeypatch, figure=figure)
    source = document["scientific"]["data_sources"][0]
    target = "source:" + source["source_id"]
    expected_value = source_value(document, target)
    expected_descriptor = source_descriptor(document, target)
    document["scientific"]["provenance"]["datasets"] = {"unrelated_payload": "data" * 25000}
    compact = content_store.intern_document(root, seal_document(document), minimum_bytes=2 if stored_binding else 8000)
    provenance = compact["scientific"]["provenance"]
    assert provenance["datasets"]["kind"] == content_store.REFERENCE_KIND
    binding_reference = provenance["binding"]
    assert (binding_reference.get("kind") == content_store.REFERENCE_KIND) == stored_binding
    service_module.load_head(root)["document"] = compact
    before_document = deepcopy(compact)
    files = {path: path.read_bytes() for path in (root / "head.json", Path(source["path"]),
                                                  *sorted((root / "content").iterdir()))}
    reads = []
    verified_bytes = content_store._verified_bytes

    def binding_only(plot_root, reference):
        assert stored_binding and reference == binding_reference
        reads.append(reference["sha256"])
        return verified_bytes(plot_root, reference)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Description loaded raw tables or expanded unrelated scientific payloads")

    monkeypatch.setattr(content_store, "_verified_bytes", binding_only)
    monkeypatch.setattr(content_store, "resolve_document_content", forbidden)
    monkeypatch.setattr(managed_sources, "load_sources", forbidden)
    # These generated documents have no append rule: summary and ordinary edit
    # need no frozen binding, whereas the source contract may read that one blob.
    for selector in ({"scope": "summary"}, {"scope": "edit", "target": "scale:x", "property": "scale.domain"}
                     if figure else {"scope": "edit", "target": "series:A", "property": "style.line.width"}):
        service.describe(root, description=selector)
        assert reads == []
    contract_key = "figure_edit_contract" if figure else "object_edit_contract"
    edit = service.describe(root, description={"scope": "edit", "target": target, "property": "source.sha256"})
    assert edit[contract_key] == {target: {"source.sha256": expected_descriptor}}
    assert edit["current_value"] == expected_value
    assert bool(reads) == stored_binding
    reads.clear()
    assert service.describe(root)[contract_key][target]["source.sha256"] == expected_descriptor
    assert bool(reads) == stored_binding
    assert compact == before_document
    assert {path: path.read_bytes() for path in files} == files
