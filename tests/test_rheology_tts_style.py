"""Processed-plan drawing uses shared templates without altering supplied science."""

from copy import deepcopy

import pytest

from sciplot_core.policy import DEFAULT_PALETTE_COLORS, UNIFIED_LINE_WIDTH_PT, UNIFIED_MARKER_SIZE_PT
from sciplot_core.rheology_tts_spec import compile_tts_spec
from sciplot_core.rheology_tts_style import (
    POLICY, prepare_tts_presentation, resolve_tts_series, tts_presentation_capabilities, upgrade_tts_presentation,
)
from sciplot_core.studio_render.models import POINT_LINE_MARKERS, StudioSeries
from sciplot_core.studio_render.series_options import resolve_series_encodings


def _processed(roles=("measured_curve",) * 4):
    return {"version": 1, "source_binding": {"sources": [{"path": "/data/input.csv", "sha256": "source"}]},
        "transform_ledger": {"owner": "caller", "operation": "supplied_final_coordinates"},
        "figures": [{"id": "Caller_processed", "width_mm": 60, "height_mm": 55,
            "panels": [{"id": "graph1", "rect_mm": [0, 0, 60, 55], "x_label": "x", "y_label": "y",
                "x_min": .01, "x_max": 20, "xscale": "log", "y_min": 0, "y_max": 40,
                "reference_lines": [{"axis": "y", "value": 1, "style": "dash"}],
                "series": [{"label": "duplicate display label", "role": role, "color": color,
                            "x": [10, 1, .1], "y": [30, 20, 10]}
                           for role, color in zip(roles, DEFAULT_PALETTE_COLORS, strict=False)]}]}]}


def _entries(spec):
    return compile_tts_spec(spec)["figures"][0]["panels"][0]["series"]


def test_caller_processed_plan_uses_live_shared_point_line_owner_and_duplicate_legends():
    raw = _processed()
    original = deepcopy(raw)
    prepared = prepare_tts_presentation(raw)
    entries = _entries(prepared)
    assert raw == original
    assert [item["marker"] for item in entries] == list(POINT_LINE_MARKERS)
    assert len({item["series_id"] for item in entries}) == 4
    assert {item["legend_key"] for item in entries} == {"duplicate display label"}
    shared = resolve_series_encodings(
        [StudioSeries(label=f"series_{i + 1}", x_name="x", y_name="y", x_values=(1,), y_values=(1,),
                      color="red") for i in range(4)], render_options={}, request={"template": "point_line"})
    for entry, reference, supplied in zip(entries, shared, original["figures"][0]["panels"][0]["series"], strict=True):
        encoding = entry["encoding"]
        assert encoding["marker"]["shape"] == reference.marker
        assert encoding["line"]["style"] == reference.line_style
        assert encoding["line"]["width_pt"] == UNIFIED_LINE_WIDTH_PT
        assert encoding["marker"]["size_pt"] == UNIFIED_MARKER_SIZE_PT
        assert encoding["line"]["visible"] and encoding["marker"]["fill_visible"]
        assert entry["x_values"] == supplied["x"] and entry["y_values"] == supplied["y"]
        assert encoding["line"]["color"] == supplied["color"]
        assert "unresolved_series" not in encoding["sources"].values()
        assert encoding["request_bound_fields"] == []


def test_semantic_roles_keep_points_and_fits_distinct_at_the_same_policy_dimensions():
    entries = _entries(prepare_tts_presentation(_processed(("master_points", "observed_shift", "regression_fit"))))
    assert [(s["marker"], s["encoding"]["line"]["visible"]) for s in entries] == [
        ("circle", False), ("circle", False), ("none", True)]
    assert all(s["marker_size_pt"] == UNIFIED_MARKER_SIZE_PT for s in entries)
    assert all(s["encoding"]["sources"]["marker.shape"].startswith("tts_role:") for s in entries)
    assert entries[2]["template_id"] == "curve"
    assert not entries[2]["encoding"]["marker"]["fill_visible"]


def test_fitting_window_overlay_uses_shared_group_shapes_and_preserves_supplied_coordinates():
    spec = _processed(("context_curve", "context_curve", "fitting_region_points", "fitting_region_points"))
    rows = spec["figures"][0]["panels"][0]["series"]
    for index, row in enumerate(rows):
        row.pop("color")
        row["color_index"] = index % 2
        row["label"] = f"{220 - 20 * (index % 2)} °C" if index < 2 else ""
    rows[2].update(x=[10, .1], y=[30, 10])
    rows[3].update(x=[1], y=[20])
    original = deepcopy(spec)
    prepared = prepare_tts_presentation(spec)
    entries = _entries(prepared)
    assert spec == original and prepare_tts_presentation(prepared) == prepared
    for index, entry in enumerate(entries):
        line, marker = entry["encoding"]["line"], entry["encoding"]["marker"]
        assert entry["x_values"] == rows[index]["x"] and entry["y_values"] == rows[index]["y"]
        assert marker["shape"] == POINT_LINE_MARKERS[index % 2]
        assert line["visible"] is (index < 2)
        assert marker["fill_color"] == ("white" if index < 2 else DEFAULT_PALETTE_COLORS[index % 2])
        assert marker["line_color"] == DEFAULT_PALETTE_COLORS[index % 2]
        assert marker["size_pt"] == UNIFIED_MARKER_SIZE_PT and line["width_pt"] == UNIFIED_LINE_WIDTH_PT
        assert entry["encoding"]["sources"]["marker.shape"] == "tts_shared_marker_cycle_by_color_index"
    assert [entry["legend_key"] for entry in entries] == ["220 °C", "200 °C", "", ""]
    advertised = tts_presentation_capabilities()
    assert advertised["roles"]["context_curve"]["marker_fill_mode"] == "open"
    assert "no point selection or fitting" in advertised["processed_plan"]["fitting_region_overlay"]


def test_new_roles_retain_shared_size_guard_and_supplied_error_values():
    spec = _processed(("context_curve", "fitting_region_points"))
    series = spec["figures"][0]["panels"][0]["series"]
    for row in series:
        row["error_values"] = [0, .3, .4]
    prepared = prepare_tts_presentation(spec)
    panel = prepared["figures"][0]["panels"][0]
    typed = [StudioSeries(label=row["series_id"], x_name=f"x{i}", y_name=f"y{i}",
        x_values=tuple(row["x"]), y_values=tuple(row["y"]), error_values=tuple(row["error_values"]),
        color=row["color"]) for i, row in enumerate(panel["series"])]
    assert [s.error_values for s in resolve_tts_series(panel, typed)] == [s.error_values for s in typed]
    for row in series:
        row["marker_size"] = 5
        with pytest.raises(ValueError, match="raw fields are rejected"):
            prepare_tts_presentation(spec)
        row.pop("marker_size")


@pytest.mark.parametrize("override", [
    {"marker": "none"}, {"marker_size": 9}, {"line_width": 5}, {"line_style": "none"},
    {"template_id": "curve"}, {"role": "invented"}, {"semantic_id": "invented"},
])
def test_governed_overrides_and_unknown_roles_fail_closed(override):
    spec = _processed()
    spec["figures"][0]["panels"][0]["series"][0].update(override)
    with pytest.raises(ValueError):
        prepare_tts_presentation(spec)


def test_compile_cannot_bypass_policy_by_reintroducing_marker_none():
    spec = prepare_tts_presentation(_processed())
    spec["figures"][0]["panels"][0]["series"][0]["marker"] = "none"
    with pytest.raises(ValueError, match="raw fields are rejected"):
        compile_tts_spec(spec)


def test_diagnostics_preserve_declared_method_identity_and_native_bars_are_separate():
    spec = _processed(("diagnostic_points", "diagnostic_curve"))
    series = spec["figures"][0]["panels"][0]["series"]
    series[0]["semantic_id"], series[1]["semantic_id"] = "storage_only", "loss_only"
    entries = _entries(prepare_tts_presentation(spec))
    assert [(s["marker"], s["encoding"]["line"]["visible"]) for s in entries] == [("square", False), ("triangle", True)]
    assert entries[0]["encoding"]["sources"]["marker.shape"] == "tts_method:storage_only"
    bar = _processed(("summary_bar",))
    panel = bar["figures"][0]["panels"][0]
    panel["xscale"] = "linear"
    panel["series"][0]["kind"] = "bar"
    assert _entries(prepare_tts_presentation(bar))[0]["kind"] == "bar"
    series[0].update(role="summary_bar", kind="bar", semantic_id=None)
    with pytest.raises(ValueError, match="cannot mix"):
        prepare_tts_presentation(spec)


def test_policy_capabilities_are_projected_from_live_owners():
    payload = tts_presentation_capabilities()
    assert payload["policy"] == POLICY
    assert payload["shared_defaults"]["marker_cycle"] == list(POINT_LINE_MARKERS)
    assert payload["shared_defaults"]["marker_size_pt"] == UNIFIED_MARKER_SIZE_PT
    assert payload["frequency_rule"]["template_id"] == "point_line"
    assert set(payload["templates"]) == {"point_line", "curve", "bar"}
    assert payload["processed_plan"]["series_required"] == ["role", "label", "x", "y"]


def test_shared_palette_defaults_and_semantic_indexes_replace_free_color_selection():
    spec = _processed()
    series = spec["figures"][0]["panels"][0]["series"]
    for item in series:
        item.pop("color")
    prepared = prepare_tts_presentation(spec)
    assert [s["color"] for s in prepared["figures"][0]["panels"][0]["series"]] == list(DEFAULT_PALETTE_COLORS[:4])
    assert prepare_tts_presentation(prepared) == prepared
    series[1]["color_index"] = 0
    assert _entries(prepare_tts_presentation(spec))[1]["color"] == DEFAULT_PALETTE_COLORS[0]
    series[1]["color"] = DEFAULT_PALETTE_COLORS[2]
    with pytest.raises(ValueError, match="conflicts"):
        prepare_tts_presentation(spec)
    series[1]["color"] = "#FF00FE"
    with pytest.raises(ValueError, match="live shared palette"):
        prepare_tts_presentation(spec)


def test_missing_layout_uses_shared_frame_and_caller_cannot_bypass_it():
    spec = _processed()
    figure = spec["figures"][0]
    figure.pop("width_mm")
    figure.pop("height_mm")
    figure["panels"][0].pop("rect_mm")
    result = prepare_tts_presentation(spec)["figures"][0]
    default = tts_presentation_capabilities()["layout"]["default_size_mm"]
    assert [result["width_mm"], result["height_mm"]] == default
    assert result["panels"][0]["standard_frame"] is True
    assert result["panels"][0]["rect_mm"] == [0, 0, *default]
    figure["panels"][0]["standard_frame"] = False
    with pytest.raises(ValueError, match="standard frame"):
        prepare_tts_presentation(spec)
    figure["panels"][0].pop("standard_frame")
    figure.update(width_mm=80, height_mm=80)
    with pytest.raises(ValueError, match="size preset"):
        prepare_tts_presentation(spec)


def test_legacy_explicit_spec_remains_reproducible_and_is_not_silently_upgraded():
    legacy = _processed(("measured_curve",))
    raw = legacy["figures"][0]["panels"][0]["series"][0]
    raw.pop("role")
    raw.update(marker="none", marker_size=3.7, line_style="dash")
    entry = _entries(legacy)[0]
    assert entry["marker"] == "none" and entry["marker_size_pt"] == 3.7
    assert entry["line_style"] == "dashed"
    with pytest.raises(ValueError, match="known separated"):
        upgrade_tts_presentation(legacy)
