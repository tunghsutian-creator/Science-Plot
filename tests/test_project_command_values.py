"""Pure values preserve v1 evidence without introducing IO or mutable authority."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import (
    FigureReadWitness, PreparedFile, PreparedMutation, ProjectMutation,
    ResourceRole, is_native_save_as_excluded, resource_facts,
)
from sciplot_core.project_commands.prepared import prepared_mutation


def test_byte_prepared_detaches_every_public_container_and_preserves_v1_digest():
    writes = {"a": PreparedFile(b"original", 0o755)}
    result, review = {"nested": [1, {"value": "original"}]}, {"items": [2]}
    value = PreparedMutation.from_values(writes, result, review=review, artifacts={"view": b"pixels"})
    expected = canonical_json_sha256({"writes": {"a": writes["a"].descriptor()},
        "artifacts": {"view": PreparedFile(b"pixels", 0o600).descriptor()},
        "result": result, "review": review, "sources": []}, allow_nan=False)
    writes.clear()
    result["nested"][1]["value"] = "changed"
    review["items"].append(3)
    value.result["nested"][1]["value"] = "returned copy"
    value.review["items"].append(4)
    value.writes.clear()
    value.artifacts.clear()
    assert value.prepared_digest == expected
    assert value.result["nested"][1]["value"] == "original"
    assert value.review == {"items": [2]}
    assert value.writes["a"].mode == 0o755


def test_deferred_constructor_detaches_without_observing_paths(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("a value constructor cannot observe the filesystem")
    with monkeypatch.context() as no_io:
        no_io.setattr(Path, "open", forbidden)
        no_io.setattr(Path, "stat", forbidden)
        writes, result = {"a": Path("missing-private-candidate")}, {"nested": [1]}
        value = ProjectMutation(writes, result)
        writes.clear()
        result["nested"].append(2)
        assert value.writes == {"a": Path("missing-private-candidate")}
        assert value.result == {"nested": [1]}
        with pytest.raises(ValueError, match="byte values"):
            prepared_mutation(value)


def test_old_declaration_without_new_helper_uses_the_same_conversion():
    legacy = SimpleNamespace(writes={"a": b"bytes"}, result={"ok": True}, review=None,
                             artifacts={}, sources=None, prepared_sources=(), input_reads=())
    assert prepared_mutation(legacy).prepared_digest == ProjectMutation({"a": b"bytes"}, {"ok": True}).prepared_digest
    legacy.result["ok"] = False
    assert prepared_mutation(legacy).result == {"ok": False}


def test_source_roles_do_not_make_ordinary_references_immutable_or_grant_io():
    generation = {"project_id": "project", "generation": "generation", "locators": {"": "/old"},
        "files": {"source.vsz": {"sha256": "a" * 64, "mode": 0o644}},
        "sources": {"source": {"a" * 64: {"locator": "/old/source.vsz"}}}}
    facts = resource_facts(generation, "source.vsz")
    assert facts.roles == frozenset({ResourceRole.SOURCE_REFERENCE})
    assert is_native_save_as_excluded(facts)
    assert not hasattr(facts, "path") and not hasattr(facts, "grant")
    generation["retired_namespace_prefixes"] = ["history"]
    assert is_native_save_as_excluded(resource_facts(generation, "history/absent.vsz"))
    with pytest.raises((KeyError, ValueError)):
        resource_facts({"files": {}}, "new.vsz")  # no invented no-Store generation


def test_selected_witness_roundtrips_original_shapes_and_detaches():
    payload = {"project_files": {"studio/a.vsz": "a" * 64}, "source_files": {"/raw/a": "b" * 64}, "projected_reads": []}
    witness = FigureReadWitness.from_read_state(payload)
    payload["project_files"].clear()
    witness.to_read_state_payload()["project_files"].clear()
    assert witness.to_read_state_payload()["project_files"] == {"studio/a.vsz": "a" * 64}
    assert FigureReadWitness.from_binding(witness.to_binding_fields()) == witness


def test_binding_absence_is_preserved_but_not_an_observed_selected_file():
    binding = {"files": {"studio/new.vsz": None}}
    witness = FigureReadWitness.from_binding(binding)
    assert witness.to_binding_fields()["files"] == binding["files"]
    with pytest.raises(ValueError, match="mandatory"):
        FigureReadWitness.from_read_state({"project_files": binding["files"]})


@pytest.mark.parametrize("result", [None, [], "not an object", 7])
def test_factory_and_direct_prepared_constructor_still_reject_nonobject_results(result):
    import json

    with pytest.raises(ValueError):
        PreparedMutation.from_values({"a": b"bytes"}, result)
    with pytest.raises(ValueError):
        PreparedMutation((("a", b"bytes"),), json.dumps(result), "null", ())


def test_factory_and_direct_prepared_constructor_still_reject_uncaptured_sources():
    for construct in (
        lambda: PreparedMutation.from_values({"a": b"bytes"}, {}, prepared_sources=(object(),)),
        lambda: PreparedMutation((("a", b"bytes"),), "{}", "null", (), prepared_sources=(object(),)),
    ):
        with pytest.raises(ValueError, match="explicit captured"):
            construct()


def test_source_validation_belongs_once_to_the_public_prepared_constructor(monkeypatch):
    import hashlib
    from sciplot_core.project_commands import PreparedSource

    source = PreparedSource("a" * 32, "/raw/original", hashlib.sha256(b"original").hexdigest(), b"original")
    observed = []
    original = PreparedSource.__post_init__

    def check(value):
        observed.append(value)
        original(value)

    monkeypatch.setattr(PreparedSource, "__post_init__", check)
    value = PreparedMutation.from_values({"a": b"bytes"}, {}, prepared_sources=[source])
    assert observed == [source]
    observed.clear()
    direct = PreparedMutation(value._writes, value._result_json, value._review_json,
                              value._artifacts, prepared_sources=(source,))
    assert observed == [source] and direct.prepared_digest == value.prepared_digest


def test_resource_roles_are_only_consumed_generation_facts():
    assert {role.value for role in ResourceRole} == {
        "source_reference", "immutable_input", "history", "retired_namespace"}
    generation = {"project_id": "project", "generation": "generation", "files": {},
                  "roles": {"unregistered.vsz": ["native_authority"]}}
    assert resource_facts(generation, "unregistered.vsz").roles == frozenset()
    with pytest.raises(TypeError, match="declared_roles"):
        resource_facts(generation, "unregistered.vsz", declared_roles=(ResourceRole.IMMUTABLE_INPUT,))
