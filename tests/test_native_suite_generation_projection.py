"""Selected NativeSuite manifest writes cannot roll back another figure."""

from copy import deepcopy

import pytest

from sciplot_core.project_commands.native_suite_projections import (
    merge_native_suite_figure,
    native_suite_figure,
)


def manifest():
    return {"kind": "sciplot_rheology_tts_suite", "version": 1,
        "workspace": "/project/work", "delivery": "/project/figures",
        "sources": [{"path": "/source.csv", "sha256": "1" * 64}],
        "prepared_input": {"path": "/plan.json", "sha256": "2" * 64},
        "figure_layout": "prepared", "contract_sha256": "3" * 64,
        "documents": [{"id": key, "path": f"/project/figures/editable/{key}.vsz",
                       "sha256": ("4" if key == "A" else "5") * 64,
                       "exports": [f"/project/figures/{key}.pdf"]} for key in ["A", "B"]],
        "native_result": {"figures": [{"id": key, "spec_path": f"/project/work/{key}.spec.json",
                                       "spec_sha256": "6" * 64} for key in ["A", "B"]]},
        "last_export": [{"document": f"/project/figures/editable/{key}.vsz",
                         "document_sha256": ("4" if key == "A" else "5") * 64,
                         "exports": [{"path": f"/project/figures/{key}.pdf", "sha256": "7" * 64}]}
                        for key in ["A", "B"]]}


def test_unrelated_publication_and_overlay_do_not_invalidate_selected_figure():
    original = manifest()
    changed = deepcopy(original)
    changed["documents"][1]["sha256"] = "8" * 64
    changed["last_export"][1]["exports"][0]["sha256"] = "9" * 64
    changed["presentation_revision"] = {"version": 1, "preview": "/B/review.json",
        "figures": [{"id": "B", "spec_path": "/B/new.spec.json", "spec_sha256": "a" * 64}]}
    assert native_suite_figure(original, "A") == native_suite_figure(changed, "A")
    assert native_suite_figure(original, "B") != native_suite_figure(changed, "B")


def test_stale_A_candidate_merge_retains_current_B_and_all_other_global_fields():
    base = manifest()
    candidate = deepcopy(base)
    candidate["documents"][0]["sha256"] = "b" * 64
    candidate["last_export"][0]["exports"][0]["sha256"] = "c" * 64
    candidate["presentation_revision"] = {"version": 1, "preview": "/A/review.json",
        "figures": [{"id": "A", "spec_path": "/A/new.spec.json", "spec_sha256": "d" * 64}]}
    current = deepcopy(base)
    current["documents"][1]["sha256"] = "e" * 64
    current["last_export"][1]["exports"][0]["sha256"] = "f" * 64
    current["presentation_revision"] = {"version": 1, "preview": "/B/review.json",
        "scope": "B's publication", "figures": [{"id": "B", "spec_path": "/B/new.spec.json",
                                                   "spec_sha256": "a" * 64}]}
    before_current, before_candidate = deepcopy(current), deepcopy(candidate)
    merged = merge_native_suite_figure(current, candidate, "A")
    assert merged["documents"][0] == candidate["documents"][0]
    assert merged["documents"][1] == current["documents"][1]
    assert merged["last_export"][1] == current["last_export"][1]
    assert merged["presentation_revision"]["preview"] == "/B/review.json"
    assert merged["presentation_revision"]["scope"] == "B's publication"
    assert native_suite_figure(merged, "A") == native_suite_figure(candidate, "A")
    assert native_suite_figure(merged, "B") == native_suite_figure(current, "B")
    assert current == before_current and candidate == before_candidate


@pytest.mark.parametrize("field,value", [("workspace", "/other"), ("delivery", "/other"),
    ("sources", []), ("prepared_input", {}), ("figure_layout", "other"), ("contract_sha256", "f" * 64)])
def test_selected_merge_refuses_changed_global_bindings(field, value):
    old, candidate = manifest(), manifest()
    candidate[field] = value
    with pytest.raises(ValueError, match="whole-set"):
        merge_native_suite_figure(old, candidate, "A")


@pytest.mark.parametrize("field,value", [("path", "/elsewhere/A.vsz"), ("exports", ["/elsewhere/A.pdf"])])
def test_selected_merge_refuses_publication_path_remapping(field, value):
    old, candidate = manifest(), manifest()
    candidate["documents"][0][field] = value
    with pytest.raises(ValueError, match="paths"):
        merge_native_suite_figure(old, candidate, "A")


def test_publication_clocks_are_not_binding_but_native_and_export_bytes_are():
    old, current = manifest(), manifest()
    current["last_export"][0]["finished_utc"] = "later"
    current["last_export"][0]["exports"][0]["elapsed_seconds"] = 22
    assert native_suite_figure(old, "A") == native_suite_figure(current, "A")
    current["last_export"][0]["exports"][0]["sha256"] = "a" * 64
    assert native_suite_figure(old, "A") != native_suite_figure(current, "A")


@pytest.mark.parametrize("change", ["duplicate", "missing", "invalid_spec"])
def test_malformed_selected_authority_refuses_projection(change):
    value = manifest()
    if change == "duplicate":
        value["documents"].append(deepcopy(value["documents"][0]))
    elif change == "missing":
        value["documents"].pop(0)
    else:
        value["native_result"]["figures"][0]["spec_sha256"] = "not a digest"
    with pytest.raises(ValueError):
        native_suite_figure(value, "A")
