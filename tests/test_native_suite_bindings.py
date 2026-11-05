"""Pure retained role parsing is separate from host IO and editable candidates."""
from copy import deepcopy

import pytest

from sciplot_core.workflow.native_suite_bindings import parse_suite_bindings, parse_suite_catalog
from sciplot_core.workflow.rheology_tts_saved_state import _selected_documents


def manifest():
    return {"kind": "sciplot_rheology_tts_suite", "workspace": "/old/work", "delivery": "/old/out",
            "sources": [{"path": "/raw/original", "sha256": "a" * 64}],
            "documents": [{"id": "A", "path": "/old/out/editable/A.vsz", "sha256": "b" * 64, "exports": []}],
            "native_result": {"figures": [{"id": "A", "document": "/old/out/editable/A.vsz", "exports": []}]}}


def test_retained_no_version_and_opaque_metadata_never_create_resource_roles():
    value = manifest()
    value["opaque_future_metadata"] = {"path": "/foreign/must-not-be-a-grant"}
    before = deepcopy(value)
    parsed = parse_suite_bindings(value)
    assert parsed.workspace_locator == "/old/work" and parsed.sources[0].locator == "/raw/original"
    assert parsed.native_locator(parsed.documents()[0]) == "/old/out/editable/A.vsz"
    with pytest.raises(ValueError, match="exact bound"):
        parsed.native_locator({"id": "A", "path": value["opaque_future_metadata"]["path"]})
    assert value == before


@pytest.mark.parametrize("version", [True, 2, "1"])
def test_unknown_explicit_version_is_not_legacy_missing_version(version):
    value = manifest()
    value["version"] = version
    with pytest.raises(ValueError, match="supported"):
        parse_suite_bindings(value)


def test_partial_catalog_projection_never_manufactures_a_manifest_or_roots():
    value = {"documents": manifest()["documents"], "native_result": manifest()["native_result"]}
    assert parse_suite_catalog(value).export_receipts()["A"]["exports"] == []
    with pytest.raises(ValueError):
        parse_suite_bindings(value)
    assert "workspace" not in value and "kind" not in value


def test_selected_candidate_rows_remain_editable_until_mutation_freeze():
    value = manifest()
    selected = _selected_documents(value, ("A",))
    selected[0]["sha256"] = "c" * 64
    assert value["documents"][0]["sha256"] == "c" * 64
    with pytest.raises(ValueError, match="Select exact"):
        _selected_documents(value, ("foreign",))
