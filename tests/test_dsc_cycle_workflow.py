from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sciplot_core._paths import resolve_fixture_path
from sciplot_core.materials_rules import compute_analysis_metrics, get_rule
from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.studio import StudioSeries, _apply_readability_render_defaults
from sciplot_core.studio_render.series_transforms import (
    _apply_template_series_transforms,
)


def _dsc_sheet(*, cooling: bool) -> pd.DataFrame:
    temperatures = [280.0 - 2.0 * index for index in range(126)]
    if not cooling:
        temperatures = list(reversed(temperatures))
    rows: list[list[object]] = [
        ["Time", "Temperature", "Heat flow"],
        ["min", "°C", "W/g"],
    ]
    rows.extend(
        [index * 0.2, temperature, 0.002 * temperature]
        for index, temperature in enumerate(temperatures)
    )
    return pd.DataFrame(rows)


def _write_cycle_workbook(path: Path) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        _dsc_sheet(cooling=True).to_excel(
            writer, sheet_name="Cooling", header=False, index=False
        )
        _dsc_sheet(cooling=False).to_excel(
            writer, sheet_name="Heating", header=False, index=False
        )


def _stack_source_series() -> list[StudioSeries]:
    return [
        StudioSeries(
            label="A",
            x_name="x1",
            y_name="y1",
            x_values=(30.0, 100.0, 180.0, 280.0),
            y_values=(-0.2, 0.1, 1.8, 0.0),
            color="#222222",
        ),
        StudioSeries(
            label="B",
            x_name="x2",
            y_name="y2",
            x_values=(30.0, 100.0, 180.0, 280.0),
            y_values=(-1.0, 0.2, 5.0, 0.1),
            color="#3568C0",
        ),
    ]


def test_dsc_curve_rejects_ambiguous_cycle_sheets_without_phase_projection(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "cycle.xlsx"
    _write_cycle_workbook(workbook)

    with pytest.raises(ValueError, match="More than one source table"):
        prepare_semantic_source(
            workbook,
            output_dir=tmp_path / "prepared",
            semantic={"semantic_family": "dsc_curve"},
        )

    assert not (
        tmp_path / "prepared" / "processed" / "dsc_cycle_comparison.csv"
    ).exists()


def test_dsc_curve_no_longer_selects_full_peak_stacking_implicitly() -> None:
    source_series = _stack_source_series()
    dsc_default = _apply_template_series_transforms(
        source_series,
        request={"rule_id": "dsc_curve", "template": "stacked_curve"},
        render_options={},
    )
    generic_default = _apply_template_series_transforms(
        source_series,
        request={"template": "stacked_curve"},
        render_options={},
    )
    explicit_envelope = _apply_template_series_transforms(
        source_series,
        request={"template": "stacked_curve"},
        render_options={"stack_peak_envelope": True},
    )

    assert dsc_default == generic_default
    assert dsc_default != explicit_envelope

    default_axis = _apply_readability_render_defaults(
        {},
        request={"rule_id": "dsc_curve", "template": "stacked_curve"},
        axis_info={"x_label": "Temperature", "y_label": "Heat flow"},
        series=dsc_default,
        template_id="stacked_curve",
    )
    explicit_axis = _apply_readability_render_defaults(
        {"stack_peak_envelope": True},
        request={"template": "stacked_curve"},
        axis_info={"x_label": "Temperature", "y_label": "Heat flow"},
        series=explicit_envelope,
        template_id="stacked_curve",
    )
    assert "stack_full_peak_envelope_axis" not in default_axis.get(
        "_autofixes_applied", []
    )
    assert "stack_full_peak_envelope_axis" in explicit_axis["_autofixes_applied"]


def test_dsc_analysis_metrics_remain_algorithmic_without_transition_identity(
    tmp_path: Path,
) -> None:
    fixture = resolve_fixture_path(str(get_rule("dsc_curve").fixture_path or ""))
    metrics = compute_analysis_metrics(
        source_path=fixture,
        processed_source=None,
        semantic={"rule_id": "dsc_curve", "axis_plan": {}},
        output_dir=tmp_path,
    )
    metric_ids = {str(item["metric"]) for item in metrics}

    assert all("tg" not in metric.casefold() for metric in metric_ids)
    assert metric_ids == {
        f"maximum_absolute_heat_flow_slope_temperature_C[{sample}]"
        for sample in ("UDC 2", "UDC 3", "UDC 4")
    } | {
        f"maximum_absolute_heat_flow_temperature_C[{sample}]"
        for sample in ("UDC 2", "UDC 3", "UDC 4")
    }
