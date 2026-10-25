"""Exact native read scopes preserve independence without hiding real conflicts."""

from copy import deepcopy
import json

import pytest

from sciplot_core.project_commands.read_projections import merge_projection, projection_digest


def registry():
    tasks = [{"figure_id": name, "source": {"sha256": name * 64}, "metric": name}
             for name in ("a", "b")]
    return {"kind": "sciplot_studio_figure_set", "version": 2,
            "primary_figure_id": "a", "status": "ready",
            "figures": [{"figure_id": task["figure_id"], "status": "ready",
                         "document": f"studio/{task['figure_id']}.vsz",
                         "spec": f"studio/{task['figure_id']}.spec.json",
                         "resolved_figure_task": task,
                         "document_state": {"current_hash": "old"}, "document_authority": "generated"}
                        for task in tasks],
            "resolved_figure_plan": {"tasks": tasks, "source_sha256": "c" * 64,
                                    "outcomes": [{"figure_id": name, "status": "editable", "artifacts": []}
                                                 for name in ("a", "b")]}}


def digest(value):
    return projection_digest(json.dumps(value).encode(), kind="studio_figure_v1", key="a")


def test_other_figure_publication_and_selected_export_do_not_invalidate_business_read():
    value = registry()
    before = digest(value)
    value["figures"][1].update(document_state={"current_hash": "new"}, exports=["b.pdf"])
    value["figures"][0].update(document_state={"current_hash": "new"}, document_authority="saved")
    value["resolved_figure_plan"]["outcomes"][1]["artifacts"] = ["new-b.pdf"]
    value["status"] = "partially_available"
    assert digest(value) == before


@pytest.mark.parametrize("change", ["member", "path", "spec", "source", "task", "status", "primary", "unknown"])
def test_selected_membership_paths_sources_tasks_and_unknown_business_fields_conflict(change):
    value = registry()
    before = digest(value)
    entry = value["figures"][0]
    if change == "member":
        value["figures"] = value["figures"][1:]
        with pytest.raises(ValueError, match="absent"):
            digest(value)
        return
    if change in {"path", "spec"}:
        entry["document" if change == "path" else "spec"] = "studio/remapped"
    elif change == "source":
        value["resolved_figure_plan"]["source_sha256"] = "d" * 64
    elif change == "task":
        entry["resolved_figure_task"]["metric"] = "remapped scientific metric"
    elif change == "status":
        entry["status"] = "unavailable"
    elif change == "primary":
        value["primary_figure_id"] = "b"
    else:
        entry["future_scientific_binding"] = {"source": "changed"}
    assert digest(value) != before


@pytest.mark.parametrize("bad", [b"[]", b"null", b"{", b'{"kind":"x","kind":"y"}', b'{"value":NaN}'])
def test_projection_rejects_malformed_or_ambiguous_json(bad):
    with pytest.raises(ValueError):
        projection_digest(bad, kind="studio_figure_v1", key="a")


def test_duplicate_members_and_unknown_projection_kind_fail_closed():
    value = registry()
    value["figures"].append(deepcopy(value["figures"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        digest(value)
    with pytest.raises(ValueError, match="Unsupported"):
        projection_digest(json.dumps(registry()).encode(), kind="json_pointer", key="a")


def suite():
    return {"kind": "sciplot_rheology_tts_suite", "version": 1,
            "workspace": "/workspace", "delivery": "/delivery",
            "sources": [{"path": "/source.csv", "sha256": "c" * 64}],
            "documents": [{"id": name, "path": f"/delivery/editable/{name}.vsz", "sha256": name * 64,
                           "exports": [f"/delivery/figures/{name}.pdf"]} for name in ("a", "b")],
            "native_result": {"figures": [{"id": name, "spec_path": f"/workspace/{name}.json",
                                           "spec_sha256": name * 64} for name in ("a", "b")]}}


def native_digest(value):
    return projection_digest(json.dumps(value).encode(), kind="native_suite_figure_v1", key="a")


def test_native_other_figure_exports_and_partial_spec_overlay_preserve_selected_read():
    value = suite()
    before = native_digest(value)
    value["documents"][1]["exports"] = ["/delivery/figures/new-b.pdf"]
    value["presentation_revision"] = {"figures": [{"id": "b", "spec_path": "/workspace/new-b.json",
                                                  "spec_sha256": "d" * 64}], "preview": "new-preview"}
    value["last_export"] = [{"document": "/delivery/editable/b.vsz", "exports": ["new-b.pdf"]}]
    assert native_digest(value) == before


@pytest.mark.parametrize("field", ["path", "sha256", "source", "spec_path", "spec_sha256", "export"])
def test_native_selected_bindings_remain_conflicts(field):
    value = suite()
    before = native_digest(value)
    if field in {"path", "sha256"}:
        value["documents"][0][field] = "remapped"
    elif field == "source":
        value["sources"][0]["sha256"] = "d" * 64
    elif field in {"spec_path", "spec_sha256"}:
        value["native_result"]["figures"][0][field] = "d" * 64 if field == "spec_sha256" else "remapped"
    else:
        value["last_export"] = [{"document": "/delivery/editable/a.vsz", "audit": "new-a-audit"}]
    assert native_digest(value) != before


def test_selected_studio_publish_merges_without_overwriting_concurrent_other_figure():
    base = registry()
    candidate = deepcopy(base)
    candidate["figures"][0]["document_state"] = {"current_hash": "new-a"}
    candidate["resolved_figure_plan"]["outcomes"][0]["artifacts"] = ["new-a.pdf"]
    current = deepcopy(base)
    current["figures"][1]["document_state"] = {"current_hash": "new-b"}
    current["resolved_figure_plan"]["outcomes"][1]["artifacts"] = ["new-b.pdf"]
    current["status"] = "changed aggregate publication status"
    merged = json.loads(merge_projection(json.dumps(current).encode(), json.dumps(candidate).encode(),
                                         kind="studio_figure_v1", key="a"))
    assert merged["figures"][0]["document_state"] == {"current_hash": "new-a"}
    assert merged["figures"][1] == current["figures"][1]
    assert merged["resolved_figure_plan"]["outcomes"][1] == current["resolved_figure_plan"]["outcomes"][1]
    assert merged["resolved_figure_plan"]["outcomes"][0]["artifacts"] == ["new-a.pdf"]
    assert merged["status"] == current["status"]


def test_selected_publication_cannot_write_a_scientific_binding():
    base, candidate = registry(), registry()
    candidate["figures"][0]["spec"] = "foreign-spec.json"
    with pytest.raises(ValueError, match="cannot change scientific"):
        merge_projection(json.dumps(base).encode(), json.dumps(candidate).encode(), kind="studio_figure_v1", key="a")
