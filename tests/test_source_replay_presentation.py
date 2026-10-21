"""Generated source replay keeps science while current represented styles change."""

from copy import deepcopy
import math

import pytest

from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
from sciplot_core.source_coverage.spec_units import _spec_render_data_units, render_data_unit_signature
from sciplot_core.veusz_worker.style_projection import project_transferred_styles
from test_categorical_source_identity import snapshots, written
from test_registered_mapping_task_sources import mapped_spec as _mapped_spec_fixture

# Register the unchanged generated fixture without treating each parameter as
# a redefinition of an otherwise unused import.
mapped_spec = _mapped_spec_fixture


def transferred(spec, path, setting, value):
    return project_transferred_styles(spec, [{"current_widget": "/page1/graph1/" + path,
        "setting": setting, "after": value}])


def test_transferred_axis_size_does_not_replace_or_invalidate_original_science(mapped_spec):
    source, _, _, _, _, _, _, spec = mapped_spec
    original = source.read_bytes()
    captured = snapshots(spec)
    assert _verify_prepared_data(spec, captured)["status"] == "passed"
    changed = project_transferred_styles(spec, [
        {"current_widget": "/page1/graph1/x", "setting": "Label/size", "after": "9pt"},
        *({"current_widget": "/page1/graph1/" + item["name"], "setting": setting, "after": "#7B61A8"}
          for item in spec["series"] for setting in ("MarkerFill/color", "MarkerLine/color")),
    ])
    assert changed["axes"]["x"]["label_size_pt"] == 9.
    assert spec["axes"]["x"]["label_size_pt"] == 7.
    assert changed["source_request"] == spec["source_request"]
    assert all(item["marker_fill_color"] == "#7B61A8" for item in changed["series"])
    assert [item["y_values"] for item in changed["series"]] == [[1., 1., 3., 5.], [7., 8., 9.]]
    inventory = {str(item["path"]): item["sha256"] for item in captured}
    before = _spec_render_data_units(spec, artifact_inventory=inventory)
    after = _spec_render_data_units(changed, artifact_inventory=inventory)
    for old, new in zip(before, after, strict=True):
        restored = deepcopy(new)
        restored["axes"]["x"]["label_size_pt"] = 7.
        assert restored == old  # Exactly one represented presentation field differs.
        assert render_data_unit_signature(new) == render_data_unit_signature(old)
    assert _verify_prepared_data(changed, captured)["status"] == "passed"
    assert source.read_bytes() == original


@pytest.mark.parametrize("setting,value,field", [
    ("TickLabels/size", "8pt", "tick_label_size_pt"),
    ("Line/width", "1.2pt", "line_width_pt"),
    ("MajorTicks/width", "1.1pt", "major_tick_width_pt"),
    ("MinorTicks/width", "0.9pt", "minor_tick_width_pt"),
])
def test_other_existing_axis_style_slots_do_not_become_original_data_facts(mapped_spec, setting, value, field):
    spec = mapped_spec[-1]
    changed = transferred(spec, "y", setting, value)
    assert changed["axes"]["y"][field] != spec["axes"]["y"][field]
    assert _verify_prepared_data(changed, snapshots(spec))["status"] == "passed"


def test_transferred_direct_label_size_keeps_literal_source_identity(tmp_path, monkeypatch):
    source = tmp_path / "curve.csv"
    source.write_text("Time,Stress\ns,Pa\nA,A\n0,10\n1,12\n2,11\n")
    spec = written({"input": str(source), "template": "stacked_curve",
        "render_options": {"series_label_mode": "inline", "show_single_series_label": True}},
        tmp_path, monkeypatch, "curve")
    assert spec["direct_labels"][0]["label"] == "A"
    changed = transferred(spec, spec["direct_labels"][0]["name"], "Text/size", "10pt")
    assert changed["direct_labels"][0]["text_size_pt"] == 10.
    assert _verify_prepared_data(changed, snapshots(spec))["status"] == "passed"
    changed["direct_labels"][0]["label"] = "another original sample"
    with pytest.raises(ValueError, match="do not reproduce"):
        _verify_prepared_data(changed, snapshots(spec))


@pytest.mark.parametrize("template", ["curve", "point_line", "heatmap"])
def test_vector_and_scalar_source_replay_share_the_same_style_boundary(tmp_path, monkeypatch, template):
    from sciplot_core.source_coverage.file_snapshots import _stable_file_snapshot

    source = tmp_path / "original.csv"
    options = {}
    if template == "heatmap":
        source.write_text("x,y,z\n0,0,1\n1,0,2\n0,1,3\n1,1,4\n")
        options = {"data_variables": {"x": "x", "y": "y", "z": "z"}, "show_colorbar": True}
    else:
        source.write_text("Time,Stress\ns,Pa\nA,A\n0,10\n1,12\n2,11\n")
    original = source.read_bytes()
    spec = written({"input": str(source), "template": template, "render_options": options},
                   tmp_path, monkeypatch, template)
    captured = [_stable_file_snapshot(source, label="generated source")]
    changed = transferred(spec, "x", "Label/size", "9pt")
    assert _verify_prepared_data(changed, captured)["status"] == "passed"
    if template == "heatmap":
        assert changed["scalar_field"]["z_values"] == [[1., 2.], [3., 4.]]
        changed["scalar_field"]["z_values"][0][0] = 99.
    else:
        assert changed["series"][0]["y_values"] == [10., 12., 11.]
        changed["series"][0]["y_values"][0] = 99.
    with pytest.raises(ValueError, match="do not reproduce"):
        _verify_prepared_data(changed, captured)
    assert source.read_bytes() == original


@pytest.mark.parametrize("change", ["x_values", "y_one_bit", "point_order", "duplicate_count", "axis_unit", "axis_scale",
    "axis_min", "axis_max", "axis_mode", "category_positions", "category_labels", "raw_distribution",
    "source_identity", "source_hash", "unknown_axis_field"])
def test_preserved_styles_cannot_hide_changed_science_or_unknown_source_claims(mapped_spec, change):
    source, _, _, _, _, _, _, spec = mapped_spec
    original = source.read_bytes()
    changed = transferred(spec, "x", "Label/size", "9pt")
    item = changed["series"][0]
    if change == "x_values":
        item["x_values"][0] += .1
    elif change == "y_one_bit":
        item["y_values"][0] = math.nextafter(1., 2.)
    elif change == "point_order":
        item["y_values"] = [5., 3., 1., 1.]
    elif change == "duplicate_count":
        item["x_values"].pop(0)
        item["y_values"].pop(0)
    elif change == "axis_unit":
        changed["axes"]["y"]["label"] = "Impact strength (J/m^{2})"
    elif change == "axis_scale":
        changed["axes"]["y"]["scale"] = "log"
    elif change in {"axis_min", "axis_max"}:
        changed["axes"]["y"][change.removeprefix("axis_")] = 4.
    elif change == "axis_mode":
        changed["axes"]["x"]["mode"] = "numeric"
    elif change == "category_positions":
        changed["axes"]["x"]["category_positions"] = [2., 1.]
    elif change == "category_labels":
        changed["axes"]["x"]["category_labels"] = ["Blue", "Amber"]
    elif change == "raw_distribution":
        changed["categorical"]["groups"][0]["raw_values"][0] = 42.
    elif change == "source_identity":
        item["source_binding"]["source_id"] = changed["series"][1]["source_binding"]["source_id"]
    elif change == "source_hash":
        item["source_artifacts"][0]["sha256"] = "0" * 64
    else:
        changed["axes"]["x"]["future_unit_factor"] = 1000
    with pytest.raises(ValueError):
        _verify_prepared_data(changed, snapshots(spec))
    assert source.read_bytes() == original


def test_source_projection_never_mutates_or_erases_saved_style_fields(mapped_spec):
    changed = transferred(mapped_spec[-1], "x", "Label/size", "9pt")
    captured = snapshots(changed)
    inventory = {str(item["path"]): item["sha256"] for item in captured}
    units = _spec_render_data_units(changed, artifact_inventory=inventory)
    original = deepcopy(units)
    first = [render_data_unit_signature(unit) for unit in units]
    assert first == [render_data_unit_signature(unit) for unit in units]
    assert units == original
    assert units[0]["axes"]["x"]["label_size_pt"] == 9.


def test_native_exact_axis_matcher_still_rejects_stale_transferred_typography():
    from sciplot_core.veusz_worker.axis_matchers import _axis_record_matches_spec

    axis = {"label": "Time (s)", "scale": "linear", "min": 0., "max": 2., "ticks": [0., 1., 2.],
        "foreground_color": "#111111", "label_size_pt": 9., "tick_label_size_pt": 7., "line_width_pt": .8,
        "major_tick_width_pt": .8, "major_tick_length_pt": 2.8, "minor_tick_width_pt": .8, "minor_tick_length_pt": 1.5}
    bindings = {"label": "Time (s)", "direction": "horizontal", "mode": "numeric", "log": False,
        "min": 0., "max": 2., "TickLabels/format": "Auto", "MajorTicks/manualTicks": [0., 1., 2.],
        "MinorTicks/number": 20, "MinorTicks/manualTicks": [], "Label/size": "9pt", "TickLabels/size": "7pt",
        "Line/width": "0.8pt", "MajorTicks/width": "0.8pt", "MajorTicks/length": "2.8pt",
        "MinorTicks/width": "0.8pt", "MinorTicks/length": "1.5pt"}
    for key in ("MajorTicks/hide", "MinorTicks/hide", "TickLabels/hide", "Label/hide", "Line/hide"):
        bindings[key] = False
    for key in ("Line/transparency", "MajorTicks/transparency", "MinorTicks/transparency"):
        bindings[key] = 0
    for key in ("Line/color", "Label/color", "TickLabels/color"):
        bindings[key] = "#111111"
    record = {"name": "x", "bindings": bindings}
    assert _axis_record_matches_spec(record, axis, axis_name="x")
    bindings["Label/size"] = "7pt"
    assert not _axis_record_matches_spec(record, axis, axis_name="x")
    bindings["Label/size"] = "9pt"
    bindings["Line/width"] = "1.2pt"
    assert not _axis_record_matches_spec(record, axis, axis_name="x")
