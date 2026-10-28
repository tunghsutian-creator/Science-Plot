"""New automatic inline labels own full physical footprints; legacy replay does not."""
from copy import deepcopy
from dataclasses import replace
import math

import pytest

from sciplot_core.foundation.rectangle_geometry import rectangle_distance, segment_box_distance
from sciplot_core.plot_layout.decorations import PT_MM
from sciplot_core.studio_core.current_direct_label_review import current_direct_label_issues
from sciplot_core.studio_render.axes_spec import _direct_label_contracts
from sciplot_core.studio_render.direct_label_layout import (
    DIRECT_LABEL_LAYOUT_KEY as KEY, DIRECT_LABEL_LAYOUT_VERSION as VERSION,
    DIRECT_LABEL_EDGE_PADDING_MM as GUARD, active_direct_label_layout, automatic_label_boxes, _text_width,
    freeze_new_direct_label_layout,
)
from sciplot_core.studio_render.models import StudioPreparationBlocked, StudioSeries, _VeuszAxisContract, _VeuszStyleContract

AXIS = _VeuszAxisContract(x_min=4180., x_max=220., y_min=66.9, y_max=98.1)
STYLE = _VeuszStyleContract()
OPTIONS = {"size": "120x55", "reverse_x": True, "series_label_side": "left",
    "series_label_offset_fraction": 0., "series_label_vertical_align": "top"}


def curve(label="a spectrum", ys=(97.5, 97.5, 67.5, 97.5, 80., 97.5)):
    return StudioSeries(label=label, x_name="x", y_name="y", x_values=(4000., 3800., 3300., 2800., 1800., 400.),
                        y_values=ys, color="#222222")


def rectangles(series, anchors):
    width = 120-STYLE.left_margin_mm-STYLE.right_margin_mm
    height = 55-STYLE.top_margin_mm-STYLE.bottom_margin_mm
    result = []
    for item, (x, y) in zip(series, anchors, strict=True):
        left = (x-AXIS.x_min)/(AXIS.x_max-AXIS.x_min)*width-GUARD
        top = (AXIS.y_max-y)/(AXIS.y_max-AXIS.y_min)*height-GUARD
        result.append([left, top, left+_text_width(item.label, STYLE.font_size_pt)+2*GUARD,
            top+STYLE.font_size_pt*PT_MM*1.8+2*GUARD])
    return result


@pytest.mark.parametrize("label", ["a spectrum", "a long arbitrary spectrum name", "WWWiii μ谱"])
def test_full_text_footprint_clears_every_complete_segment_and_fixed_frame(label):
    series = [curve(label)]
    before = deepcopy(series)
    anchors = automatic_label_boxes(series, render_options=OPTIONS, axis=AXIS, style=STYLE, side="left")
    boxes = rectangles(series, anchors)
    w, h = 101.5, 38.5
    for box in boxes:
        assert GUARD <= box[0] < box[2] <= w-GUARD+1e-10
        assert GUARD <= box[1] < box[3] <= h-GUARD+1e-10
        for item in series:
            points = [((4180-x)/3960*w, (98.1-y)/31.2*h) for x, y in zip(item.x_values, item.y_values, strict=True)]
            assert min(segment_box_distance(a, b, box) for a, b in zip(points, points[1:], strict=False)) >= 2+math.sqrt(2)*1.2*PT_MM/2
    assert series == before


def test_sparse_between_sample_segment_is_not_mistaken_for_empty_label_space():
    # Both endpoints are outside the box; the complete segment still intersects.
    assert segment_box_distance((0., 0.), (10., 10.), [4., 4., 6., 6.]) == 0.
    assert rectangle_distance([1., 1., 2., 2.], [0., 0., 3., 3.]) == 0.


def test_neighboring_spectra_and_labels_are_all_reserved_in_one_layout():
    series = [curve("upper", (97., 97., 85., 97., 88., 97.)), curve("lower", (80., 80., 69., 80., 71., 80.))]
    boxes = rectangles(series, automatic_label_boxes(series, render_options=OPTIONS, axis=AXIS, style=STYLE, side="left"))
    assert rectangle_distance(*boxes) >= 2.
    assert len(boxes) == len(series)


def test_new_auto_marker_curves_are_planned_not_categorically_rejected():
    item = replace(curve("marked"), marker="circle", marker_size=1.0)
    assert len(automatic_label_boxes([item], render_options=OPTIONS, axis=AXIS, style=STYLE, side="left")) == 1



@pytest.mark.parametrize("problem", ["long", "dense"])
def test_infeasible_footprint_fails_without_changing_data_axes_frame_or_font(problem):
    series = [curve("x"*200)] if problem == "long" else [curve(str(y), (y,)*6) for y in range(67, 99)]
    before = deepcopy((series, OPTIONS, AXIS, STYLE))
    with pytest.raises(StudioPreparationBlocked) as error:
        automatic_label_boxes(series, render_options=OPTIONS, axis=AXIS, style=STYLE, side="left")
    assert error.value.reason_code == "direct_label_layout_infeasible"
    assert (series, OPTIONS, AXIS, STYLE) == before


@pytest.mark.parametrize("key,value", [("series_label_side", "right"), ("series_label_offset_fraction", 0.),
    ("series_label_vertical_align", "top"), ("series_label_mode", "legend"), ("series_label_mode", "none")])
def test_new_creation_preserves_declared_placement_or_non_inline_choice(key, value):
    request = {"render_options": {key: value}, "explicit_render_option_keys": [key]}
    assert freeze_new_direct_label_layout(request, template="stacked_curve") == request


@pytest.mark.parametrize("template,intent", [("curve", False), ("stacked_curve", True)])
def test_unrelated_templates_and_managed_authority_do_not_acquire_new_defaults(template, intent):
    request = {"render_options": {}}
    if intent:
        request["intent"] = {"kind": "managed"}
    assert freeze_new_direct_label_layout(request, template=template) == request


def test_version_is_persistent_and_replay_never_selects_a_current_default():
    original = {"render_options": {"show_single_series_label": False}, "explicit_render_option_keys": []}
    current = freeze_new_direct_label_layout(original, template="stacked_curve")
    assert KEY not in original and current[KEY] == VERSION
    assert current["render_options"] == original["render_options"]
    assert freeze_new_direct_label_layout(current, template="stacked_curve") == current
    assert active_direct_label_layout(original) is None
    assert active_direct_label_layout(current) == VERSION
    explicit = {**current, "render_options": {"series_label_offset_fraction": .12}, "explicit_render_option_keys": ["series_label_offset_fraction"]}
    assert active_direct_label_layout(explicit) is None
    assert current_direct_label_issues([], {"source_request": explicit}, None, None) == []


def test_missing_version_replays_exact_legacy_anchor_while_new_version_uses_whole_footprint():
    args = dict(render_options=OPTIONS, axis_contract=AXIS, style=STYLE, show_direct_labels=True)
    old = _direct_label_contracts([curve()], **args)
    new = _direct_label_contracts([curve()], **args, automatic_layout_version=VERSION)
    assert (old[0]["x"], old[0]["y"], old[0]["valign"], old[0]["margin_pt"]) == (3800., 97.5, "top", 0.)
    assert new[0]["x"] != old[0]["x"] or new[0]["y"] != old[0]["y"]
    assert {k: v for k, v in new[0].items() if k not in {"x", "y"}} == {k: v for k, v in old[0].items() if k not in {"x", "y"}}
    assert _direct_label_contracts([curve()], **{**args, "show_direct_labels": False}, automatic_layout_version=VERSION) == []


@pytest.mark.parametrize("version", [None, "future-v2", "", False])
def test_unknown_version_is_never_silently_interpreted_as_old_or_current(version):
    with pytest.raises(ValueError, match="Unknown persisted"):
        active_direct_label_layout({KEY: version})
    with pytest.raises(ValueError, match="Unknown persisted"):
        _direct_label_contracts([], render_options={}, axis_contract=AXIS, style=STYLE,
            show_direct_labels=False, automatic_layout_version="future-v2")


@pytest.mark.parametrize("x_start,x_end,xscale", [(220., 4180., "linear"), (4180., 220., "linear"),
    (220., 4180., "log"), (4180., 220., "log")])
def test_directed_axis_bounds_project_once_including_reversed_log_axes(x_start, x_end, xscale):
    axis = _VeuszAxisContract(x_min=x_start, x_max=x_end, y_min=66.9, y_max=98.1)
    options = {**OPTIONS, "xscale": xscale, "reverse_x": x_start > x_end}
    anchor = automatic_label_boxes([curve()], render_options=options, axis=axis, style=STYLE, side="left")[0]
    assert min(x_start, x_end) <= anchor[0] <= max(x_start, x_end)
    assert axis.y_min <= anchor[1] <= axis.y_max


def test_source_reconstruction_consumes_recorded_layout_version_without_changing_scientific_values(tmp_path, monkeypatch):
    from sciplot_core.smoke.data_mapping import _write_synthetic_ftir
    from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
    from test_categorical_source_identity import snapshots, written
    source = tmp_path / "spectrum.csv"
    _write_synthetic_ftir(source)
    before = source.read_bytes()
    request = {"input": str(source), "rule_id": "ftir_spectrum", "template": "stacked_curve",
        "explicit_render_option_keys": [], "render_options": {"series_label_mode": "inline"}, KEY: VERSION}
    spec = written(request, tmp_path, monkeypatch, "current")
    assert spec["source_request"][KEY] == VERSION
    assert spec["axes"]["x"]["min"] > spec["axes"]["x"]["max"]
    assert _verify_prepared_data(spec, snapshots(spec))["status"] == "passed"
    assert source.read_bytes() == before


def test_exact_current_qa_is_new_auto_only_and_missing_measurement_fails_closed():
    assert current_direct_label_issues([], {"source_request": {}, "direct_labels": [{"name": "label_1"}]}, None, None) == []
    issue = current_direct_label_issues([], {"source_request": {KEY: VERSION}, "direct_labels": [{"name": "label_1"}]}, None, None)
    assert issue[0]["severity"] == "critical" and issue[0]["measurement_scope"] == "unverified_current_native"


@pytest.mark.parametrize("defect", ["none", "stale", "unsupported", "missing_curve", "outside", "collision", "label_collision", "old_control_box_measurement", "old_glyph_metric_measurement"])
def test_actual_qa_requires_complete_bound_text_frame_and_all_visible_curves(tmp_path, defect):
    from sciplot_core.foundation.file_hashing import file_sha256
    document = tmp_path / "plot.vsz"
    document.write_text("native bytes")
    spec = {"source_request": {KEY: VERSION}, "direct_labels": [{"name": "label_1"}, {"name": "label_2"}], "series": [{"name": "curve_1"}]}
    geometry = {"kind": "sciplot_native_direct_label_geometry", "version": 2, "coverage_complete": True,
        "coordinate_dpi": 72, "pdf_origin_quantization_device_pixel": 1/64, "glyph_metric_max_error_device_pixel": 2/64,
        "labels": [{"path": "/page1/graph1/label_"+str(i), "graph_path": "/page1/graph1",
                    "minimum_curve_clearance_mm": 2.1, "minimum_label_clearance_mm": 2.1} for i in (1, 2)],
        "hidden_labels": [], "data_paths": ["/page1/graph1/curve_1"], "hidden_data_paths": [], "outside_plot_paths": []}
    audit = {"path": str(document), "sha256": file_sha256(document), "direct_label_geometry": geometry}
    if defect == "old_glyph_metric_measurement":
        geometry.pop("glyph_metric_max_error_device_pixel")
    if defect == "old_control_box_measurement":
        geometry["version"] = 1
    if defect == "stale":
        audit["sha256"] = "0"*64
    if defect == "unsupported":
        geometry["coverage_complete"] = False
    if defect == "missing_curve":
        geometry["data_paths"] = []
    if defect == "outside":
        geometry["outside_plot_paths"] = ["/page1/graph1/label_1"]
    if defect == "collision":
        geometry["labels"][0]["minimum_curve_clearance_mm"] = 0.
    if defect == "label_collision":
        geometry["labels"][0]["minimum_label_clearance_mm"] = 0.
    result = current_direct_label_issues([], spec, document, audit)
    assert result[0]["severity"] == ("info" if defect == "none" else "critical")


@pytest.mark.parametrize("value", [0., .001, -.001, 1.02, -1.02, 3.15625])
def test_pdf_origin_quantization_has_a_derived_one_grid_unit_bound(value):
    from sciplot_core.veusz_audit.direct_label_ink import PDF_FIXED_SCALE, qt_pdf_origin
    actual = qt_pdf_origin(value)
    assert actual*PDF_FIXED_SCALE == math.trunc(value*PDF_FIXED_SCALE)
    assert abs(actual-value) < 1/PDF_FIXED_SCALE


def test_terminal_projection_and_normalization_preserve_the_recorded_layout_selector():
    from sciplot_core.terminal_request import authoritative_terminal_render_request, normalize_terminal_render_request
    request = {"template": "stacked_curve", "render_options": {"series_label_mode": "inline"}, KEY: VERSION}
    projected = authoritative_terminal_render_request(request)
    assert projected[KEY] == VERSION
    assert normalize_terminal_render_request(projected, label="layout replay") == projected
    historical = {key: value for key, value in request.items() if key != KEY}
    assert KEY not in authoritative_terminal_render_request(historical)
    with pytest.raises(ValueError, match="Unknown persisted"):
        authoritative_terminal_render_request({**request, KEY: None})


@pytest.mark.parametrize("x,y,width,height", [(0.01, .001, .031, .046),
    (-.01, -.001, .031, .046), (7.1, -3.2, 4.8, 2.3), (-7.1, 3.2, 4.8, 2.3)])
def test_two_scalar_metric_reconstruction_is_enclosed_without_relaxing_clearance(x, y, width, height):
    from sciplot_core.veusz_audit.direct_label_ink import GLYPH_METRIC_MAX_ERROR_PX, qt_pdf_origin
    rx, ry, rw, rh = map(qt_pdf_origin, (x, y, width, height))
    # Qt CoreText glyph metric construction, compared to original CT rectangle.
    metric = [rx, -ry-rh, rx+rw, -ry]
    actual = [x, -y-height, x+width, -y]
    error = GLYPH_METRIC_MAX_ERROR_PX
    assert metric[0]-error <= actual[0] and metric[1]-error <= actual[1]
    assert metric[2]+error >= actual[2] and metric[3]+error >= actual[3]
    assert error == 2/64  # Representation error in device pixels, not QA tolerance.
