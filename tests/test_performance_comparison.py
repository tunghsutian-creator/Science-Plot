from __future__ import annotations

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
