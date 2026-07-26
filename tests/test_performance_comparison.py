from __future__ import annotations

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
    payload = build_performance_scatter_payload(
        load_performance_comparison(FIXTURE)
    )
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
    ref_series = [
        item for item in payload["series"] if item["role"] == "reference"
    ]
    assert all(item["marker_fill_color"] == "white" for item in ref_series)


def test_dense_scatter_uses_sixteen_marker_identities_and_fits_index(
    tmp_path: Path,
) -> None:
    source = _write_frame(tmp_path, _dense_scatter_frame())
    payload = build_performance_scatter_payload(
        load_performance_comparison(source)
    )
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
    assert min(
        min(float(value) for value in item["yPos"])
        for item in marker_polygons
    ) > 0.12


def test_scatter_groups_shared_marker_identities_in_compact_120mm_index(
    tmp_path: Path,
) -> None:
    frame = _dense_scatter_frame()
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
        ),
        "Reference 2": (
            "PA66 composites",
            "PA66 composites [ref x]",
            "Sandwich foam",
            1,
            "triangledown",
        ),
        "Reference 3": (
            "PLA/PBAT/ADR blends",
            "PLA/PBAT/ADR blends [ref x]",
            "Sandwich foam",
            1,
            "pentagon",
        ),
        "Reference 4": (
            "PP/PTFE blends",
            "PP/PTFE blends [ref x]",
            "Sandwich foam",
            1,
            "hexagon",
        ),
        "Reference 5": (
            "PP/GnP/GF composite",
            "PP/GnP/GF composite [ref x]",
            "Sandwich foam",
            1,
            "star",
        ),
        "Reference 6": (
            "PET copolymer",
            "PET copolymer [ref x]",
            "Bulk polymer",
            1,
            "plus",
        ),
        "Reference 7": (
            "Continuous basalt-fiber/epoxy laminate",
            "Continuous basalt-fiber/epoxy laminate [ref x]",
            "Laminate",
            1,
            "cross",
        ),
        "Reference 8": (
            "Continuous carbon fiber laminate",
            "Continuous carbon fiber laminate [ref x]",
            "Laminate",
            1,
            "triangleleft",
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
        identity, label, group, column, marker = reference_contract[str(material)]
        mask = frame["Material"] == material
        frame.loc[mask, "LegendIdentity"] = identity
        frame.loc[mask, "LegendLabel"] = label
        frame.loc[mask, "LegendGroup"] = group
        frame.loc[mask, "LegendColumn"] = column
        frame.loc[mask, "LegendItemsPerRow"] = 1
        frame.loc[mask, "Marker"] = marker

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
    assert len(payload["envelopes"]) == 1
    assert payload["envelopes"][0]["line_hide"] is True
    assert len(payload["envelopes"][0]["members"]) == 6
    assert all(
        not str(member).startswith("E0")
        for member in payload["envelopes"][0]["members"]
    )
    assert len(payload["envelopes"][0]["x_values"]) >= 16

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
    assert (
        exc_info.value.reason_code
        == "performance_legend_items_per_row_invalid"
    )


def test_performance_rejects_invalid_envelope_include_value(
    tmp_path: Path,
) -> None:
    frame = _fixture_frame()
    frame["EnvelopeInclude"] = "maybe"
    source = _write_frame(tmp_path, frame)
    with pytest.raises(PerformanceComparisonError) as exc_info:
        load_performance_comparison(source)
    assert (
        exc_info.value.reason_code
        == "performance_envelope_include_invalid"
    )


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
    assert (
        exc_info.value.reason_code
        == "performance_scatter_scale_invalid"
    )


def test_performance_rejects_scatter_bound_that_excludes_data(
    tmp_path: Path,
) -> None:
    frame = _fixture_frame()
    frame.loc[frame["Metric"] == "density", "ScatterMin"] = 1.2
    source = _write_frame(tmp_path, frame)
    with pytest.raises(PerformanceComparisonError) as exc_info:
        build_performance_scatter_payload(
            load_performance_comparison(source)
        )
    assert (
        exc_info.value.reason_code
        == "performance_scatter_bound_excludes_data"
    )


def test_radar_payload_uses_declared_directional_bounds() -> None:
    payload = build_performance_radar_payload(
        load_performance_comparison(FIXTURE)
    )
    assert payload["template"] == PERFORMANCE_RADAR_TEMPLATE_ID
    assert payload["layout"]["page_size_mm"] == [120.0, 55.0]
    assert payload["normalization"]["outer_is_better"] is True
    own_a = next(item for item in payload["series"] if item["label"] == "Own A")
    pa6 = next(item for item in payload["series"] if item["label"] == "PA6")
    assert own_a["filled_polygon"] is True
    assert own_a["radii"][0] == pytest.approx((1.6 - 1.05) / 0.8)
    assert own_a["radii"][-1] == own_a["radii"][0]
    assert pa6["filled_polygon"] is False
    assert len(pa6["radii"]) == 4
    assert payload["axis_labels"] == [
        "Density ↓",
        "Specific impact strength ↑",
        "Tensile strength ↑",
        "Elongation at break ↑",
    ]


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
            ~(
                (frame["Material"] == "Own C")
                & (frame["Metric"] == "tensile_strength")
            )
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
