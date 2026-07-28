from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.performance_comparison import (
    PERFORMANCE_RADAR_TEMPLATE_ID,
    PERFORMANCE_SCATTER_TEMPLATE_ID,
    PerformanceComparisonError,
    build_performance_radar_payload,
    build_performance_scatter_payload,
    is_performance_comparison_source,
    load_performance_comparison,
)
from sciplot_core.performance_veusz import build_performance_veusz_spec
from sciplot_core.materials_rules import get_rule
from sciplot_core.policy import (
    PERFORMANCE_REFERENCE_COLOR,
    PERFORMANCE_REFERENCE_ENVELOPE_FILL_TRANSPARENCY,
    PERFORMANCE_SAMPLE_FILL_TRANSPARENCY,
)
from sciplot_core.render import render_to_dir
from sciplot_core.semantic import classify_source


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "performance_comparison"
    / "material_performance_long.csv"
)


def _fixture_frame() -> pd.DataFrame:
    return pd.read_csv(FIXTURE)


def _write_frame(tmp_path: Path, frame: pd.DataFrame) -> Path:
    target = tmp_path / "performance.csv"
    frame.to_csv(target, index=False)
    return target


def _dense_scatter_frame() -> pd.DataFrame:
    sample_markers = (
        "circle",
        "square",
        "triangle",
        "triangledown",
        "plus",
        "cross",
        "diamond",
        "pentagon",
    )
    reference_markers = (
        "hexagon",
        "star",
        "triangleleft",
        "triangleright",
        "octogon",
        "ellipsehorz",
        "ellipsevert",
        "star4",
    )
    materials = [
        *[
            (f"E{sample_index} - 2 mm", "sample", "2 mm", marker)
            for sample_index, marker in zip(
                (0, 2, 3, 4), sample_markers[:4], strict=True
            )
        ],
        *[
            (f"E{sample_index} - 4 mm", "sample", "4 mm", marker)
            for sample_index, marker in zip(
                (0, 2, 3, 4), sample_markers[4:], strict=True
            )
        ],
        *[
            (f"Reference {index}", "reference", "Literature", marker)
            for index, marker in enumerate(reference_markers, start=1)
        ],
    ]
    rows: list[dict[str, object]] = []
    for material_order, (material, role, group, marker) in enumerate(
        materials, start=1
    ):
        density = (
            0.764
            if role == "sample" and group == "2 mm"
            else 0.570
            if role == "sample"
            else 0.80 + 0.05 * (material_order - 9)
        )
        specific_impact = 25.0 + 9.0 * material_order
        journal = "Example Journal" if role == "reference" else ""
        year = "2026" if role == "reference" else ""
        for metric, value, unit, display_label, scatter_axis in (
            ("density", density, "g cm^-3", "Density", "x"),
            (
                "specific_impact_strength",
                specific_impact,
                "kJ m^-2 cm^3 g^-1",
                "Specific impact strength",
                "y",
            ),
        ):
            rows.append(
                {
                    "Material": material,
                    "Role": role,
                    "Group": group,
                    "Metric": metric,
                    "Value": value,
                    "Unit": unit,
                    "DisplayLabel": display_label,
                    "ScatterAxis": scatter_axis,
                    "Journal": journal,
                    "Year": year,
                    "MaterialOrder": material_order,
                    "Marker": marker,
                }
            )
    return pd.DataFrame(rows)


def _summary_scatter_frame() -> pd.DataFrame:
    frame = _dense_scatter_frame()
    sample = frame["Role"] == "sample"
    retained_sample = frame["Material"].str.startswith(("E3 ", "E4 "))
    frame = frame.loc[~sample | retained_sample].copy()
    for column in (
        "EnvelopeInclude",
        "MarkerFillColor",
        "LegendLabel",
        "LegendGroup",
        "LegendIdentity",
        "LegendColumn",
        "LegendItemsPerRow",
        "ScatterMin",
    ):
        frame[column] = ""

    sample = frame["Role"] == "sample"
    frame.loc[sample, "Group"] = "Modified samples"
    frame.loc[sample, "EnvelopeInclude"] = "true"
    frame.loc[sample, "Marker"] = "circle"
    frame.loc[sample, "LegendLabel"] = "This work"
    frame.loc[sample, "LegendGroup"] = "This work"
    frame.loc[sample, "LegendIdentity"] = "This work"

    reference_groups = {
        **{f"Reference {index}": "Sandwich foam" for index in range(1, 6)},
        "Reference 6": "Bulk polymer",
        "Reference 7": "Laminate",
        "Reference 8": "Laminate",
    }
    group_markers = {
        "Sandwich foam": "triangledown",
        "Bulk polymer": "plus",
        "Laminate": "cross",
    }
    group_fills = {
        "Sandwich foam": "#EED59F",
        "Bulk polymer": "#A7D9D2",
        "Laminate": "#D0C5E0",
    }
    for material, group in reference_groups.items():
        mask = frame["Material"] == material
        frame.loc[mask, "EnvelopeInclude"] = "true"
        frame.loc[mask, "Marker"] = group_markers[group]
        frame.loc[mask, "MarkerFillColor"] = group_fills[group]
        frame.loc[mask, "LegendLabel"] = group
        frame.loc[mask, "LegendGroup"] = group
        frame.loc[mask, "LegendIdentity"] = group

    frame["LegendColumn"] = 1
    frame["LegendItemsPerRow"] = 1
    frame.loc[frame["Metric"] == "density", "ScatterMin"] = "0.4"
    return frame


def test_performance_source_contract_and_identity() -> None:
    assert is_performance_comparison_source(FIXTURE) is True
    comparison = load_performance_comparison(FIXTURE)
    assert [item.material_id for item in comparison.samples] == [
        "Own A",
        "Own B",
        "Own C",
    ]
    assert [item.material_id for item in comparison.references] == [
        "PA6",
        "ABS",
        "CFRP",
    ]
    assert [item.metric_id for item in comparison.radar_metrics] == [
        "density",
        "specific_impact_strength",
        "tensile_strength",
        "elongation_at_break",
    ]


def test_performance_rule_waits_for_authorized_real_data_promotion() -> None:
    rule = get_rule("performance_comparison")
    assert rule.fixture_status == "pending"

    automatic = classify_source(FIXTURE)
    assert automatic.get("rule_id") != "performance_comparison"

    explicit = classify_source(
        FIXTURE,
        requested_rule_id="performance_comparison",
    )
    assert explicit["rule_id"] == "performance_comparison"
    assert explicit["rule_readiness"] == "pending"
    assert explicit["confidence"] == 0.0


def test_scatter_payload_reserves_a_second_60mm_reference_panel() -> None:
    payload = build_performance_scatter_payload(load_performance_comparison(FIXTURE))
    assert payload["template"] == PERFORMANCE_SCATTER_TEMPLATE_ID
    assert payload["x_metric"]["metric_id"] == "density"
    assert payload["y_metric"]["metric_id"] == "specific_impact_strength"
    assert payload["layout"]["page_size_mm"] == [120.0, 55.0]
    assert payload["layout"]["plot_panel_size_mm"] == [60.0, 55.0]
    assert payload["layout"]["plot_region_mm"] == [41.5, 38.5]
    assert payload["layout"]["outside_legend"] is False
    assert len(payload["envelopes"]) == 1
    assert payload["envelopes"][0]["members"] == ["Own A", "Own B", "Own C"]
    assert len(payload["envelopes"][0]["x_values"]) >= 3
    references = [
        item for item in payload["legend_items"] if item["role"] == "reference"
    ]
    assert references[0]["citation"] == "Polymer (2024)"
    ref_series = [item for item in payload["series"] if item["role"] == "reference"]
    assert all(item["marker_fill_color"] == "white" for item in ref_series)


def test_dense_scatter_uses_sixteen_marker_identities_and_fits_index(
    tmp_path: Path,
) -> None:
    source = _write_frame(tmp_path, _dense_scatter_frame())
    payload = build_performance_scatter_payload(load_performance_comparison(source))
    assert payload["material_count"] == 16
    assert payload["sample_count"] == 8
    assert payload["reference_count"] == 8
    assert len({item["marker"] for item in payload["series"]}) == 16
    assert payload["series"][0]["color"] == payload["series"][4]["color"]

    spec = build_performance_veusz_spec(
        payload=payload,
        request={
            "input": str(source),
            "rule_id": "performance_comparison",
            "template": "scatter",
        },
        transform_steps=[],
    )
    labels = spec["performance_comparison"]["labels"]
    legend_rows = [
        item
        for item in labels
        if str(item["name"]).startswith("performance_legend_text_")
    ]
    assert len(legend_rows) == 16
    assert min(float(item["y"]) for item in legend_rows) >= 0.14 - 1e-12
    marker_polygons = [
        item
        for item in spec["performance_comparison"]["polygons"]
        if item["role"] == "material_index_marker"
    ]
    assert len(marker_polygons) == 16
    assert (
        min(min(float(value) for value in item["yPos"]) for item in marker_polygons)
        > 0.12
    )


def test_scatter_groups_shared_marker_identities_in_compact_120mm_index(
    tmp_path: Path,
) -> None:
    frame = _dense_scatter_frame()
    sandwich_fill = "#EED59F"
    bulk_fill = "#A7D9D2"
    laminate_fill = "#D0C5E0"
    sample_markers = {
        "E4": "circle",
        "E3": "square",
        "E2": "triangle",
        "E0": "diamond",
    }
    sample_order = {"E4": 0, "E3": 1, "E2": 2, "E0": 3}
    reference_contract = {
        "Reference 1": (
            "PA66 composites",
            "PA66 composites [ref x]",
            "Sandwich foam",
            1,
            "triangledown",
            sandwich_fill,
        ),
        "Reference 2": (
            "PA66 composites",
            "PA66 composites [ref x]",
            "Sandwich foam",
            1,
            "triangledown",
            sandwich_fill,
        ),
        "Reference 3": (
            "PLA/PBAT/ADR blends",
            "PLA/PBAT/ADR blends [ref x]",
            "Sandwich foam",
            1,
            "pentagon",
            sandwich_fill,
        ),
        "Reference 4": (
            "PP/PTFE blends",
            "PP/PTFE blends [ref x]",
            "Sandwich foam",
            1,
            "hexagon",
            sandwich_fill,
        ),
        "Reference 5": (
            "PP/GnP/GF composite",
            "PP/GnP/GF composite [ref x]",
            "Sandwich foam",
            1,
            "star",
            sandwich_fill,
        ),
        "Reference 6": (
            "PET copolymer",
            "PET copolymer [ref x]",
            "Bulk polymer",
            1,
            "plus",
            bulk_fill,
        ),
        "Reference 7": (
            "Continuous basalt-fiber/epoxy laminate",
            "Continuous basalt-fiber/epoxy laminate [ref x]",
            "Laminate",
            1,
            "cross",
            laminate_fill,
        ),
        "Reference 8": (
            "Continuous carbon fiber laminate",
            "Continuous carbon fiber laminate [ref x]",
            "Laminate",
            1,
            "triangleleft",
            laminate_fill,
        ),
    }
    for material in frame["Material"].unique():
        if str(material).startswith("E"):
            identity = str(material).split()[0]
            mask = frame["Material"] == material
            frame.loc[mask, "LegendIdentity"] = identity
            frame.loc[mask, "LegendLabel"] = identity
            frame.loc[mask, "LegendGroup"] = "This work"
            frame.loc[mask, "LegendColumn"] = 1
            frame.loc[mask, "LegendItemsPerRow"] = 2
            frame.loc[mask, "Group"] = (
                "Control" if identity == "E0" else "Modified samples"
            )
            frame.loc[mask, "EnvelopeInclude"] = identity != "E0"
            condition_offset = 0 if "2 mm" in str(material) else 1
            frame.loc[mask, "MaterialOrder"] = (
                sample_order[identity] * 2 + condition_offset + 1
            )
            frame.loc[mask, "Marker"] = sample_markers[identity]
            continue
        identity, label, group, column, marker, marker_fill_color = reference_contract[
            str(material)
        ]
        mask = frame["Material"] == material
        frame.loc[mask, "LegendIdentity"] = identity
        frame.loc[mask, "LegendLabel"] = label
        frame.loc[mask, "LegendGroup"] = group
        frame.loc[mask, "LegendColumn"] = column
        frame.loc[mask, "LegendItemsPerRow"] = 1
        frame.loc[mask, "Marker"] = marker
        frame.loc[mask, "MarkerFillColor"] = marker_fill_color
        frame.loc[mask, "EnvelopeInclude"] = True

    frame.loc[frame["Metric"] == "density", "ScatterMin"] = 0.4
    source = _write_frame(tmp_path, frame)
    comparison = load_performance_comparison(source)
    payload = build_performance_scatter_payload(comparison)
    repeated = build_performance_scatter_payload(comparison)

    assert payload == repeated
    assert payload["material_count"] == 16
    assert payload["series_count"] == 11
    assert payload["legend_item_count"] == 11
    assert payload["layout"]["page_size_mm"] == [120.0, 55.0]
    assert payload["layout"]["legend_column_count"] == 1
    assert math.isclose(float(payload["x_bounds"][0]), 0.4)
    assert len(payload["visual_data_transforms"]) == 1
    jitter_records = payload["visual_data_transforms"][0]["records"]
    assert len(jitter_records) == 8
    for source_x in {float(item["source_x"]) for item in jitter_records}:
        offsets = [
            float(item["offset"])
            for item in jitter_records
            if math.isclose(float(item["source_x"]), source_x)
        ]
        assert len(offsets) == 4
        assert math.isclose(sum(offsets), 0.0, abs_tol=1e-12)
        assert all(not math.isclose(offset, 0.0) for offset in offsets)
    assert len(payload["envelopes"]) == 4
    envelopes_by_group = {str(item["group"]): item for item in payload["envelopes"]}
    sample_envelope = envelopes_by_group["Modified samples"]
    assert sample_envelope["role"] == "observed_sample_extent"
    assert sample_envelope["line_hide"] is True
    assert len(sample_envelope["members"]) == 6
    assert all(
        not str(member).startswith("E0") for member in sample_envelope["members"]
    )
    assert len(sample_envelope["x_values"]) >= 16
    expected_reference_envelopes = {
        "Sandwich foam": (sandwich_fill, 5),
        "Bulk polymer": (bulk_fill, 1),
        "Laminate": (laminate_fill, 2),
    }
    for group, (fill_color, member_count) in expected_reference_envelopes.items():
        envelope = envelopes_by_group[group]
        assert envelope["role"] == "observed_reference_group_extent"
        assert envelope["fill_color"] == fill_color
        assert (
            envelope["fill_transparency"]
            == PERFORMANCE_REFERENCE_ENVELOPE_FILL_TRANSPARENCY
        )
        assert envelope["line_hide"] is True
        assert len(envelope["members"]) == member_count
        assert len(envelope["x_values"]) >= 16
    series_by_identity = {
        str(item["legend_identity"]): item for item in payload["series"]
    }
    assert {
        str(item["marker_fill_color"])
        for identity, item in series_by_identity.items()
        if identity
        in {
            "PA66 composites",
            "PLA/PBAT/ADR blends",
            "PP/PTFE blends",
            "PP/GnP/GF composite",
        }
    } == {sandwich_fill}
    assert series_by_identity["PET copolymer"]["marker_fill_color"] == bulk_fill
    assert {
        series_by_identity[identity]["marker_fill_color"]
        for identity in {
            "Continuous basalt-fiber/epoxy laminate",
            "Continuous carbon fiber laminate",
        }
    } == {laminate_fill}
    assert all(
        item["color"] == PERFORMANCE_REFERENCE_COLOR
        for item in payload["series"]
        if item["role"] == "reference"
    )
    assert {
        str(item["marker_fill_color"])
        for item in payload["series"]
        if item["role"] == "sample"
    } == {"#3568C0"}

    spec = build_performance_veusz_spec(
        payload=payload,
        request={
            "input": str(source),
            "rule_id": "performance_comparison",
            "template": "scatter",
        },
        transform_steps=[],
    )
    labels = spec["performance_comparison"]["labels"]
    visible_text = [str(item["label"]) for item in labels]
    assert "Material index" not in visible_text
    assert "Envelope: observed sample extent (not CI)" not in visible_text
    assert visible_text[:4] == [
        "This work",
        "Sandwich foam",
        "Bulk polymer",
        "Laminate",
    ]
    by_label = {str(item["label"]): item for item in labels}
    assert math.isclose(
        float(by_label["E4"]["y"]),
        float(by_label["E3"]["y"]),
    )
    assert math.isclose(
        float(by_label["E2"]["y"]),
        float(by_label["E0"]["y"]),
    )
    assert float(by_label["E4"]["x"]) < float(by_label["E3"]["x"])
    assert float(by_label["E2"]["x"]) < float(by_label["E0"]["x"])
    assert float(by_label["E4"]["y"]) > float(by_label["E2"]["y"])
    legend_markers = {
        str(item["material"]): item
        for item in spec["performance_comparison"]["polygons"]
        if item["role"] == "material_index_marker"
    }
    assert {
        legend_markers[identity]["fill_color"]
        for identity in {
            "PA66 composites",
            "PLA/PBAT/ADR blends",
            "PP/PTFE blends",
            "PP/GnP/GF composite",
        }
    } == {sandwich_fill}
    assert legend_markers["PET copolymer"]["fill_color"] == bulk_fill
    assert {
        legend_markers[identity]["fill_color"]
        for identity in {
            "Continuous basalt-fiber/epoxy laminate",
            "Continuous carbon fiber laminate",
        }
    } == {laminate_fill}
    assert {
        legend_markers[identity]["fill_color"] for identity in {"E4", "E3", "E2", "E0"}
    } == {"#3568C0"}
    extent_polygons = [
        item
        for item in spec["performance_comparison"]["polygons"]
        if item["role"]
        in {
            "observed_sample_extent",
            "observed_reference_group_extent",
        }
    ]
    assert len(extent_polygons) == 4
    assert {
        str(item["group"])
        for item in extent_polygons
        if item["role"] == "observed_reference_group_extent"
    } == {"Sandwich foam", "Bulk polymer", "Laminate"}


def test_scatter_group_summary_uses_60mm_inside_legend_contract(
    tmp_path: Path,
) -> None:
    source = _write_frame(tmp_path, _summary_scatter_frame())
    payload = build_performance_scatter_payload(load_performance_comparison(source))

    assert payload["series_count"] == 4
    assert payload["legend_item_count"] == 4
    assert [item["label"] for item in payload["series"]] == [
        "This work",
        "Sandwich foam",
        "Bulk polymer",
        "Laminate",
    ]
    assert [item["marker"] for item in payload["series"]] == [
        "circle",
        "triangledown",
        "plus",
        "cross",
    ]
    assert payload["layout"]["kind"] == "performance_60mm_inside_legend"
    assert payload["layout"]["page_size_mm"] == [60.0, 55.0]
    assert payload["layout"]["legend_panel_size_mm"] is None
    assert payload["layout"]["legend_uses_reserved_panel"] is False
    assert {
        str(item["group"]): int(item["fill_transparency"])
        for item in payload["envelopes"]
    } == {
        "Modified samples": 35,
        "Sandwich foam": PERFORMANCE_REFERENCE_ENVELOPE_FILL_TRANSPARENCY,
        "Bulk polymer": PERFORMANCE_REFERENCE_ENVELOPE_FILL_TRANSPARENCY,
        "Laminate": PERFORMANCE_REFERENCE_ENVELOPE_FILL_TRANSPARENCY,
    }

    spec = build_performance_veusz_spec(
        payload=payload,
        request={
            "input": str(source),
            "rule_id": "performance_comparison",
            "template": "scatter",
            "render_options": {
                "legend_position": "lower_right",
            },
        },
        transform_steps=[],
    )
    assert spec["size_mm"] == [60.0, 55.0]
    assert spec["frame_alignment"]["reference_panel_size_mm"] is None
    assert spec["legend"]["show"] is True
    assert spec["legend"]["mode"] == "lower_right"
    assert spec["legend"]["presentation_kind"] == ("performance_group_summary")
    assert spec["performance_comparison"]["labels"] == []
    assert not [
        item
        for item in spec["performance_comparison"]["polygons"]
        if item["role"] == "material_index_marker"
    ]


@pytest.mark.comprehensive
def test_scatter_group_summary_materializes_auto_inside_native_key(
    tmp_path: Path,
) -> None:
    source = _write_frame(tmp_path, _summary_scatter_frame())
    result = render_to_dir(
        source,
        template="scatter",
        output_dir=tmp_path / "rendered",
        export_formats=("pdf",),
        request_context={"rule_id": "performance_comparison"},
    )
    spec = json.loads(Path(result["veusz_specs"][0]).read_text(encoding="utf-8"))
    document_text = Path(result["veusz_documents"][0]).read_text(encoding="utf-8")

    assert result["qa_reports"][0]["issues"] == []
    assert spec["size_mm"] == [60.0, 55.0]
    assert spec["legend"]["show"] is True
    assert (
        spec["legend"]["placement_diagnostics"]["method"]
        == "final_size_physical_clearance_v1"
    )
    assert spec["legend"]["placement_diagnostics"]["position"] in {
        "upper_right",
        "lower_right",
        "upper_left",
        "lower_left",
    }
    assert "Add('key', name='key1'" in document_text
    assert "performance_legend_heading_" not in document_text
    assert "performance_legend_text_" not in document_text
    assert "Set('width', '60mm')" in document_text
    assert "Set('height', '55mm')" in document_text


def test_dense_scatter_rejects_duplicate_marker_in_one_figure(
    tmp_path: Path,
) -> None:
    frame = _dense_scatter_frame()
    frame.loc[frame["Material"] == "Reference 2", "Marker"] = "circle"
    source = _write_frame(tmp_path, frame)
    with pytest.raises(PerformanceComparisonError) as exc_info:
        build_performance_scatter_payload(load_performance_comparison(source))
    assert exc_info.value.reason_code == "performance_marker_identity_duplicate"


def test_performance_rejects_more_than_two_legend_items_per_row(
    tmp_path: Path,
) -> None:
    frame = _fixture_frame()
    frame["LegendItemsPerRow"] = 3
    source = _write_frame(tmp_path, frame)
    with pytest.raises(PerformanceComparisonError) as exc_info:
        load_performance_comparison(source)
    assert exc_info.value.reason_code == "performance_legend_items_per_row_invalid"


def test_performance_rejects_invalid_envelope_include_value(
    tmp_path: Path,
) -> None:
    frame = _fixture_frame()
    frame["EnvelopeInclude"] = "maybe"
    source = _write_frame(tmp_path, frame)
    with pytest.raises(PerformanceComparisonError) as exc_info:
        load_performance_comparison(source)
    assert exc_info.value.reason_code == "performance_envelope_include_invalid"


def test_performance_rejects_invalid_marker_fill_color(
    tmp_path: Path,
) -> None:
    frame = _fixture_frame()
    frame["MarkerFillColor"] = ""
    frame.loc[frame["Material"] == "PA6", "MarkerFillColor"] = "pale gold"
    source = _write_frame(tmp_path, frame)
    with pytest.raises(PerformanceComparisonError) as exc_info:
        load_performance_comparison(source)
    assert exc_info.value.reason_code == "performance_marker_fill_color_invalid"


def test_reference_envelope_requires_one_shared_explicit_fill(
    tmp_path: Path,
) -> None:
    frame = _fixture_frame()
    reference_mask = frame["Role"] == "reference"
    frame.loc[reference_mask, "EnvelopeInclude"] = True
    frame.loc[reference_mask, "LegendGroup"] = "Reference materials"
    frame.loc[reference_mask, "MarkerFillColor"] = "#EED59F"
    frame.loc[frame["Material"] == "CFRP", "MarkerFillColor"] = "#D0C5E0"
    source = _write_frame(tmp_path, frame)

    with pytest.raises(PerformanceComparisonError) as exc_info:
        build_performance_scatter_payload(load_performance_comparison(source))

    assert exc_info.value.reason_code == "performance_reference_envelope_fill_conflict"


def test_performance_rejects_reversed_scatter_bounds(
    tmp_path: Path,
) -> None:
    frame = _fixture_frame()
    density = frame["Metric"] == "density"
    frame.loc[density, "ScatterMin"] = 2.0
    frame.loc[density, "ScatterMax"] = 1.0
    source = _write_frame(tmp_path, frame)
    with pytest.raises(PerformanceComparisonError) as exc_info:
        load_performance_comparison(source)
    assert exc_info.value.reason_code == "performance_scatter_scale_invalid"


def test_performance_rejects_scatter_bound_that_excludes_data(
    tmp_path: Path,
) -> None:
    frame = _fixture_frame()
    frame.loc[frame["Metric"] == "density", "ScatterMin"] = 1.2
    source = _write_frame(tmp_path, frame)
    with pytest.raises(PerformanceComparisonError) as exc_info:
        build_performance_scatter_payload(load_performance_comparison(source))
    assert exc_info.value.reason_code == "performance_scatter_bound_excludes_data"


def test_radar_payload_uses_declared_directional_bounds() -> None:
    payload = build_performance_radar_payload(load_performance_comparison(FIXTURE))
    assert payload["template"] == PERFORMANCE_RADAR_TEMPLATE_ID
    assert payload["layout"]["page_size_mm"] == [120.0, 55.0]
    assert payload["normalization"]["outer_is_better"] is True
    assert payload["angles_degrees"] == [90.0, 180.0, 270.0, 0.0]
    assert payload["axis_endpoint_labels"] == ["0.8", "120", "180", "120"]
    assert payload["layout"]["graph_margins_mm"] == {
        "left": 8.0,
        "right": 70.5,
        "bottom": 9.5,
        "top": 7.0,
    }
    own_a = next(item for item in payload["series"] if item["label"] == "Own A")
    pa6 = next(item for item in payload["series"] if item["label"] == "PA6")
    assert own_a["filled_polygon"] is True
    assert own_a["color"] == "#3568C0"
    assert own_a["polygon_fill_color"] == "#AFC6ED"
    assert own_a["fill_transparency"] == PERFORMANCE_SAMPLE_FILL_TRANSPARENCY == 35
    assert own_a["radii"][0] == pytest.approx((1.6 - 1.05) / 0.8)
    assert own_a["radii"][-1] == own_a["radii"][0]
    assert pa6["filled_polygon"] is False
    assert len(pa6["radii"]) == 4
    assert payload["axis_labels"] == [
        "Density",
        "Specific impact strength",
        "Tensile strength",
        "Elongation at break",
    ]
    spec = build_performance_veusz_spec(
        payload=payload,
        request={
            "input": str(FIXTURE),
            "rule_id": "performance_comparison",
            "template": "polar_curve",
        },
        transform_steps=[],
    )
    sample_fill = next(
        item
        for item in spec["performance_comparison"]["polygons"]
        if item["name"] == "performance_radar_sample_fill_1"
    )
    assert sample_fill["line_color"] == "#3568C0"
    assert sample_fill["fill_color"] == "#AFC6ED"
    assert sample_fill["fill_transparency"] == 35


def test_radar_multiline_axis_label_uses_separate_6pt_native_labels(
    tmp_path: Path,
) -> None:
    frame = _fixture_frame()
    metric_mask = frame["Metric"] == "specific_impact_strength"
    frame.loc[
        metric_mask,
        "DisplayLabel",
    ] = "Specific impact strength\n(kJ m⁻² kg⁻¹)"
    source = _write_frame(tmp_path, frame)
    payload = build_performance_radar_payload(load_performance_comparison(source))
    spec = build_performance_veusz_spec(
        payload=payload,
        request={
            "input": str(source),
            "rule_id": "performance_comparison",
            "template": "polar_curve",
        },
        transform_steps=[],
    )
    labels = [
        item
        for item in spec["performance_comparison"]["labels"]
        if str(item["name"]).startswith("performance_radar_axis_label_2_line_")
    ]
    assert [item["label"] for item in labels] == [
        "Specific impact strength",
        "(kJ m⁻² kg⁻¹)",
    ]
    assert all(item["text_size_pt"] == 6.0 for item in labels)
    assert labels[0]["y"] > labels[1]["y"]
    assert spec["size_mm"] == [120.0, 55.0]
    assert spec["frame_alignment"]["plot_panel_size_mm"] == [60.0, 55.0]
    assert spec["frame_alignment"]["reference_panel_size_mm"] == [60.0, 55.0]
    assert spec["frame_alignment"]["plot_region_mm"] == [41.5, 38.5]
    heading = next(
        item
        for item in spec["performance_comparison"]["labels"]
        if str(item["name"]).startswith("performance_legend_heading_")
    )
    assert heading["x"] == pytest.approx((60.0 + 4.5) / 120.0)


def test_radar_reference_uses_explicit_category_outline_and_stays_hollow(
    tmp_path: Path,
) -> None:
    frame = _fixture_frame()
    frame["MarkerLineColor"] = ""
    frame["MarkerFillColor"] = ""
    frame.loc[frame["Role"] == "reference", "MarkerLineColor"] = "#D99A24"
    frame.loc[frame["Role"] == "reference", "MarkerFillColor"] = "#EED59F"
    comparison = load_performance_comparison(_write_frame(tmp_path, frame))

    scatter = build_performance_scatter_payload(comparison)
    radar = build_performance_radar_payload(comparison)

    assert all(
        item["color"] == "#D99A24"
        for item in scatter["series"]
        if item["role"] == "reference"
    )
    assert all(
        item["marker_fill_color"] == "#EED59F"
        for item in scatter["series"]
        if item["role"] == "reference"
    )
    assert all(
        item["color"] == "#D99A24"
        for item in radar["series"]
        if item["role"] == "reference"
    )
    assert all(
        item["marker_fill_color"] == "white"
        for item in radar["series"]
        if item["role"] == "reference"
    )
    spec = build_performance_veusz_spec(
        payload=radar,
        request={
            "input": str(comparison.source),
            "rule_id": "performance_comparison",
            "template": "polar_curve",
        },
        transform_steps=[],
    )
    reference_series = [
        item for item in spec["series"] if item["label"] in {"PA6", "ABS", "CFRP"}
    ]
    assert all(item["color"] == "#D99A24" for item in reference_series)
    assert all(item["marker_fill_color"] == "white" for item in reference_series)


def test_performance_rejects_invalid_marker_line_color(
    tmp_path: Path,
) -> None:
    frame = _fixture_frame()
    frame["MarkerLineColor"] = ""
    frame.loc[frame["Material"] == "PA6", "MarkerLineColor"] = "pale gold"
    source = _write_frame(tmp_path, frame)
    with pytest.raises(PerformanceComparisonError) as exc_info:
        load_performance_comparison(source)
    assert exc_info.value.reason_code == "performance_marker_line_color_invalid"


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        ("duplicate", "performance_material_metric_duplicate"),
        ("unit_conflict", "performance_metadata_conflict"),
        ("missing_sample_metric", "performance_radar_sample_incomplete"),
        ("outside_scale", "performance_radar_value_outside_scale"),
    ],
)
def test_performance_contract_fails_closed(
    tmp_path: Path,
    mutation: str,
    reason_code: str,
) -> None:
    frame = _fixture_frame()
    if mutation == "duplicate":
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    elif mutation == "unit_conflict":
        frame.loc[
            (frame["Material"] == "Own B") & (frame["Metric"] == "density"),
            "Unit",
        ] = "kg m^-3"
    elif mutation == "missing_sample_metric":
        frame = frame.loc[
            ~((frame["Material"] == "Own C") & (frame["Metric"] == "tensile_strength"))
        ]
    elif mutation == "outside_scale":
        frame.loc[
            (frame["Material"] == "Own A")
            & (frame["Metric"] == "specific_impact_strength"),
            "Value",
        ] = 121
    source = _write_frame(tmp_path, frame)
    with pytest.raises(PerformanceComparisonError) as exc_info:
        comparison = load_performance_comparison(source)
        if mutation in {"missing_sample_metric", "outside_scale"}:
            build_performance_radar_payload(comparison)
    assert exc_info.value.reason_code == reason_code
