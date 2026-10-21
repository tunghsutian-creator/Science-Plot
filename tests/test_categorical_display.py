"""Closed late presentation retains categorical scientific identities."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from sciplot_core.studio_core.annotation_batch import compile_annotation_operations
from sciplot_core.studio_core.annotation_schema import validate_operation_batch
from sciplot_core.studio_core.categorical_display import (
    KEY,
    compile_display,
    context,
    display_axes,
    effective_presentation,
    overlay,
)
from sciplot_core.studio_core.series_encoding_contract import series_encoding_from_spec
from sciplot_core.task_capabilities import edit_context_capabilities


@pytest.fixture
def categorical():
    binding = {
        "mode": "given_values",
        "source_sha256": "a" * 64,
        "sample_column": 0,
        "condition_column": 1,
        "value_columns": [{"column_index": 2}],
        "category_aliases": {"P": "Initial"},
        "table_selection": {
            "sheet": None,
            "header_rows": [0],
            "data_start_row": 1,
            "data_end_row": 5,
        },
    }
    return {
        "template": "point_line",
        "source_request": {"rule_id": None, "categorical_binding": binding},
        "axes": {
            "x": {"category_labels": ["Initial", "Q"], "category_positions": [1.0, 2.0]}
        },
        "style": {},
        "legend": {"native_key": True},
        "categorical": {"groups": []},
        "series": [
            {
                "name": f"series_{index}",
                "label": label,
                "color": color,
                "marker": "circle",
                "x_values": [1.0, 2.0],
                "y_values": values,
                "source_artifacts": [["original", "a" * 64]],
            }
            for index, label, color, values in [
                (1, "dry", "#123456", [1.0, 3.0]),
                (2, "wet", "#654321", [2.0, 4.0]),
            ]
        ],
    }


def alias(source="P", expected="Initial", label="Control"):
    return {
        "op": "set_category_display_labels",
        "changes": [
            {"category_id": source, "expected_label": expected, "label": label}
        ],
    }


def style(spec, **patch):
    target = context(spec)["style_targets"][0]
    return {
        "op": "set_categorical_display_style",
        "changes": [
            {
                "series_id": target["series_id"],
                "expected_style": target["current_style"],
                "style": patch,
            }
        ],
    }


def test_public_schema_and_context_close_selectors_and_supported_fields(categorical):
    capabilities = edit_context_capabilities(
        ["set_category_display_labels", "set_categorical_display_style"]
    )
    Draft202012Validator.check_schema(capabilities["request_schema"])
    validate_operation_batch(
        [alias(), style(categorical, marker="square", marker_fill_mode="open")]
    )
    state = context(
        categorical,
        {
            "/page1/graph1/key1": {
                "settings": {"columns": 1, "horzPosn": "right", "vertPosn": "top"}
            }
        },
    )
    assert state["categories"] == [
        {"category_id": "P", "label": "Initial"},
        {"category_id": "Q", "label": "Q"},
    ]
    assert state["style_targets"][0]["source_selector"] == {
        "source_label": "dry",
        "value_column_index": 2,
        "condition_label": "dry",
    }
    assert state["legend"]["current"]["columns"] == 1
    assert set(state["style_targets"][0]["editable_fields"]) == {
        "color",
        "marker",
        "marker_fill_mode",
    }


def test_continuous_labels_styles_and_projection_leave_science_unchanged(categorical):
    original = deepcopy(categorical)
    operations = [
        alias(),
        style(categorical, color="#226699", marker="square", marker_fill_mode="open"),
    ]
    native, updated, actual = compile_annotation_operations(
        categorical, operations, document_sha256="d" * 64, figure_id="primary"
    )
    assert categorical == original and not native
    assert {key: value for key, value in updated.items() if key != KEY} == original
    assert all(item["source_identity_preserved"] for item in actual)
    assert display_axes(updated)["x"]["category_labels"] == ["Control", "Q"]
    effective = effective_presentation(updated)
    encoding = series_encoding_from_spec(
        effective["series"][0], style=effective["style"]
    )
    assert (
        encoding["marker"]["shape"] == "square"
        and encoding["marker"]["fill_color"] == "white"
    )
    assert encoding["marker"]["line_color"] == encoding["line"]["color"] == "#226699"
    assert effective["series"][0]["y_values"] == original["series"][0]["y_values"]
    again, _ = compile_display(updated, alias("Q", "Q", "Treatment"))
    assert context(again)["categories"][-1] == {
        "category_id": "Q",
        "label": "Treatment",
    }
    assert (
        context(again)["style_targets"][0]["current_style"]["marker_fill_mode"]
        == "open"
    )
    restored, _ = compile_display(again, alias("P", "Control", "Initial"))
    assert (
        restored["axes"] == original["axes"]
        and display_axes(restored)["x"]["category_labels"][0] == "Initial"
    )


@pytest.mark.parametrize(
    "change", ["unknown", "stale", "collision", "duplicate", "control", "extra"]
)
def test_label_negative_controls_are_atomic(categorical, change):
    operation = alias()
    if change == "unknown":
        operation["changes"][0]["category_id"] = "invented"
    elif change == "stale":
        operation["changes"][0]["expected_label"] = "old"
    elif change == "collision":
        operation["changes"][0]["label"] = "Q"
    elif change == "duplicate":
        operation["changes"].append(deepcopy(operation["changes"][0]))
    elif change == "control":
        operation["changes"][0]["label"] = "Control\nInjected"
    else:
        operation["values"] = [7, 8]
    original = deepcopy(categorical)
    with pytest.raises(ValueError):
        compile_display(categorical, operation)
    assert categorical == original


@pytest.mark.parametrize(
    "change", ["unknown", "stale", "partial", "field", "duplicate", "legend"]
)
def test_style_negative_controls_never_silently_ignore_intent(categorical, change):
    operation = style(categorical, color="#225599")
    target = operation["changes"][0]
    if change == "unknown":
        target["series_id"] = "not_bound"
    elif change == "stale":
        target["expected_style"]["color"] = "#112233"
    elif change == "partial":
        target["expected_style"].pop("marker")
    elif change == "field":
        target["style"]["width"] = 2
    elif change == "duplicate":
        operation["changes"].append(deepcopy(target))
    else:
        operation["legend"] = {
            "columns": 13,
            "position": "upper_left",
            "expected": {"columns": 1, "horzPosn": "right", "vertPosn": "top"},
        }
    original = deepcopy(categorical)
    with pytest.raises(ValueError):
        compile_display(categorical, operation)
    assert categorical == original


def test_bar_only_color_and_bound_group_selectors_with_unchanged_raw_n(categorical):
    categorical["template"] = "bar"
    categorical["source_request"]["categorical_binding"]["mode"] = "mean_sample_sd_n"
    categorical["categorical"] = {
        "presentation_kind": "grouped_bar_error",
        "groups": [
            {
                "label": item["label"],
                "sample_label": "P",
                "condition_label": item["label"],
                "fill_color": item["color"],
                "keyline_color": item["color"],
                "raw_values": [2.0, 3.0, 3.0],
                "replicate_count": 3,
            }
            for item in categorical["series"]
        ],
    }
    original = deepcopy(categorical)
    target = context(categorical)["style_targets"][0]
    assert target["source_selector"] == {
        "source_label": "dry",
        "sample_label": "P",
        "condition_label": "dry",
    }
    assert (
        target["editable_fields"] == ["color"]
        and context(categorical)["legend"] is None
    )
    for field, value in [("marker", "square"), ("marker_fill_mode", "open")]:
        with pytest.raises(ValueError):
            compile_display(categorical, style(categorical, **{field: value}))
    updated, _ = compile_display(categorical, style(categorical, color="#225599"))
    projected = effective_presentation(updated)
    assert projected["categorical"]["groups"][0]["fill_color"] == "#225599"
    assert updated["categorical"] == original["categorical"]
    assert projected["categorical"]["groups"][0]["raw_values"] == [2.0, 3.0, 3.0]
    assert projected["categorical"]["groups"][0]["replicate_count"] == 3
    with pytest.raises(ValueError):
        compile_display(
            categorical,
            {
                "op": "set_categorical_display_style",
                "legend": {
                    "columns": 2,
                    "position": "lower_left",
                    "expected": {"columns": 1, "horzPosn": "left", "vertPosn": "top"},
                },
            },
        )
    assert categorical == original


@pytest.mark.parametrize(
    "change",
    ["rule", "binding", "mode", "unknown_overlay", "unknown_alias", "unknown_series"],
)
def test_overlay_cannot_widen_scientific_scope_or_identity(categorical, change):
    updated, _ = compile_display(categorical, alias())
    if change == "rule":
        updated["source_request"]["rule_id"] = "impact_metric"
    elif change == "binding":
        updated["source_request"].pop("categorical_binding")
    elif change == "mode":
        updated["source_request"]["categorical_binding"]["mode"] = "unknown"
    elif change == "unknown_overlay":
        updated[KEY]["native_settings"] = {}
    elif change == "unknown_alias":
        updated[KEY]["aliases"]["ghost"] = "Extra"
    else:
        updated[KEY]["styles"]["ghost"] = {"color": "#123456"}
    with pytest.raises(ValueError):
        overlay(updated)


def test_none_marker_can_be_explicitly_shown_without_data_decimation(categorical):
    categorical["series"][0]["marker"] = "none"
    updated, _ = compile_display(
        categorical, style(categorical, marker="circle", marker_fill_mode="filled")
    )
    item = effective_presentation(updated)["series"][0]
    assert (
        item["encoding"]["marker"]["fill_visible"]
        and item["encoding"]["marker"]["line_visible"]
    )
    assert item["x_values"] == categorical["series"][0]["x_values"]
