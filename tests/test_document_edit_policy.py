from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.studio_core.document_edit_policy import (
    filter_editable_fields,
    validate_edit_science_policy,
)


CURVE = "/page1/graph1/series_1"


def _spec(tmp_path: Path, **overrides) -> Path:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({
        "template": "curve", "scalar_field": None, "categorical": None,
        "series": [{"name": "series_1", "presentation_kind": "curve"}],
        **overrides,
    }))
    return path


def _objects() -> dict:
    return {
        CURVE: {"type": "xy", "target": {"document_sha256": "bound"},
                "editable_fields": [
                    {"setting_path": f"{CURVE}/PlotLine/color", "current_value": "red"},
                    {"setting_path": f"{CURVE}/PlotLine/width", "current_value": "1pt"},
                ]},
        "/page1/graph1/x": {"type": "axis", "editable_fields": [
            {"setting_path": "/page1/graph1/x/Label/size", "current_value": "8pt"},
        ]},
    }


@pytest.mark.parametrize("template", ["curve", "point_line", "stacked_curve"])
def test_ordinary_curve_color_is_advertised_and_accepted(tmp_path, template) -> None:
    spec = _spec(tmp_path, template=template)
    objects = _objects()
    filtered = filter_editable_fields(objects, spec)
    assert filtered == objects and filtered is not objects
    validate_edit_science_policy(
        [{"object_path": CURVE, "setting_path": f"{CURVE}/PlotLine/color"}], spec,
    )


@pytest.mark.parametrize("contract", [
    {"scalar_field": {"z_label": "Intensity", "show_colorbar": True}},
    {"performance_comparison": {"kind": "sciplot_performance_comparison"}},
    {"categorical": {"presentation_kind": "grouped_bar_error", "condition_labels": ["2 mm", "4 mm"]}},
    {"categorical": {"presentation_kind": "stacked_components"}},
    {"categorical": {"presentation_kind": "point_line_raw_overlay", "condition_labels": ["2 mm", "4 mm"]}},
    {"categorical": {}},
    {"legend": {"native_key": False}},
    {"template": "future_curve"},
    {"series": [{"name": "series_1", "presentation_kind": "performance_radar_material"}]},
    {"series": [{"name": "series_1", "presentation_kind": "impact_point_line_summary"}]},
    {"series": [{"name": "series_1"}]},
    {"series": [{"name": "series_1", "presentation_kind": "curve"}] * 2},
])
def test_semantic_or_unproven_color_is_removed_and_rejected(tmp_path, contract) -> None:
    spec = _spec(tmp_path, **contract)
    objects = _objects()
    before = deepcopy(objects)
    filtered = filter_editable_fields(objects, spec)
    assert objects == before
    assert filtered[CURVE]["editable_fields"] == objects[CURVE]["editable_fields"][1:]
    assert filtered[CURVE]["target"] == objects[CURVE]["target"]
    assert filtered["/page1/graph1/x"] == objects["/page1/graph1/x"]
    with pytest.raises(ValueError, match="uniquely bound ordinary curve"):
        validate_edit_science_policy(
            [{"object_path": CURVE, "setting_path": f"{CURVE}/PlotLine/color"}], spec,
        )
    validate_edit_science_policy([
        {"object_path": CURVE, "setting_path": f"{CURVE}/PlotLine/width"},
        {"object_path": "/page1/graph1/x", "setting_path": "/page1/graph1/x/Label/size"},
    ], spec)


def test_color_must_target_the_exact_series_named_by_the_spec(tmp_path) -> None:
    spec = _spec(tmp_path)
    wrong = {"object_path": "/page1/graph1/auxiliary", "setting_path": f"{CURVE}/PlotLine/color"}
    with pytest.raises(ValueError, match="uniquely bound ordinary curve"):
        validate_edit_science_policy([wrong], spec)
    objects = _objects()
    objects["/page1/graph1/auxiliary"] = objects.pop(CURVE)
    assert len(filter_editable_fields(objects, spec)["/page1/graph1/auxiliary"]["editable_fields"]) == 1
