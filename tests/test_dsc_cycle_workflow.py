from __future__ import annotations

from pathlib import Path

import pandas as pd

from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.studio import (
    StudioSeries,
    _apply_readability_render_defaults,
    _stack_studio_series,
)
from sciplot_core.workflow import _dsc_phase_sources


def _dsc_sheet(*, cooling: bool, shift: float) -> pd.DataFrame:
    hold_count = 8
    ramp_count = 126
    start_temperature = 280.0 if cooling else 30.0
    stop_temperature = 30.0 if cooling else 280.0
    temperatures = (
        [start_temperature] * hold_count
        + [
            start_temperature
            + (stop_temperature - start_temperature) * index / (ramp_count - 1)
            for index in range(ramp_count)
        ]
        + [stop_temperature] * hold_count
    )
    times = [index * 0.2 for index in range(len(temperatures))]
    heat_flow = [
        shift
        + 0.002 * temperature
        + (0.8 if index < hold_count else 0.0)
        for index, temperature in enumerate(temperatures)
    ]
    rows: list[list[object]] = [
        ["Time", "Temperature", "Heat flow"],
        ["min", "°C", "W/g"],
    ]
    rows.extend(
        [time, temperature, heat]
        for time, temperature, heat in zip(
            times, temperatures, heat_flow, strict=True
        )
    )
    return pd.DataFrame(rows)


def _write_dsc_workbook(path: Path, *, shift: float) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        _dsc_sheet(cooling=True, shift=shift).to_excel(
            writer, sheet_name="Cooling", header=False, index=False
        )
        _dsc_sheet(cooling=False, shift=shift).to_excel(
            writer, sheet_name="Second heating", header=False, index=False
        )


def test_dsc_workbooks_split_into_cooling_and_second_heating_stacks(
    tmp_path: Path,
) -> None:
    source = tmp_path / "DSC"
    source.mkdir()
    for index, sample in enumerate(("e0", "e2", "e3", "e4")):
        _write_dsc_workbook(source / f"{sample}.xlsx", shift=float(index))

    prepared = prepare_semantic_source(
        source,
        output_dir=tmp_path / "prepared",
        semantic={"semantic_family": "dsc_curve"},
    )
    processed = Path(prepared["processed_source"])
    frame = pd.read_csv(processed, header=None)

    assert frame.iloc[2, ::2].tolist() == [
        "Cooling E0",
        "Cooling E2",
        "Cooling E3",
        "Cooling E4",
        "Second heating E0",
        "Second heating E2",
        "Second heating E3",
        "Second heating E4",
    ]
    selections = prepared["transform_steps"][0]["parameters"]["source_selections"]
    assert all(item["selected_point_count"] < item["source_point_count"] for item in selections)
    assert all(item["temperature_boundary_guard_fraction"] == 0.015 for item in selections)

    phase_sources = _dsc_phase_sources(
        processed,
        request={"rule_id": "dsc_curve"},
        output_dir=tmp_path / "render",
    )

    assert [item[0] for item in phase_sources] == [
        "dsc_cooling",
        "dsc_second_heating",
    ]
    assert all("size" not in options for _name, _path, options in phase_sources)
    assert all(
        options["stack_peak_envelope"] is True
        for _name, _path, options in phase_sources
    )
    for _name, phase_source, _options in phase_sources:
        phase_frame = pd.read_csv(phase_source, header=None)
        assert phase_frame.iloc[2, ::2].tolist() == ["E0", "E2", "E3", "E4"]


def test_dsc_stack_and_axis_use_complete_peak_envelope() -> None:
    source_series = [
        StudioSeries(
            label="E0",
            x_name="x1",
            y_name="y1",
            x_values=(30.0, 100.0, 180.0, 280.0),
            y_values=(-0.2, 0.1, 1.8, 0.0),
            color="#222222",
        ),
        StudioSeries(
            label="E2",
            x_name="x2",
            y_name="y2",
            x_values=(30.0, 100.0, 180.0, 280.0),
            y_values=(-1.0, 0.2, 5.0, 0.1),
            color="#3568C0",
        ),
    ]
    stacked = _stack_studio_series(
        source_series,
        render_options={},
        full_peak_envelope=True,
    )
    first_values = [value for value in stacked[0].y_values]
    second_values = [value for value in stacked[1].y_values]

    assert max(first_values) < min(second_values)

    options = _apply_readability_render_defaults(
        {},
        request={"rule_id": "dsc_curve", "template": "stacked_curve"},
        axis_info={"x_label": "Temperature", "y_label": "Heat flow"},
        series=stacked,
        template_id="stacked_curve",
    )
    plotted = first_values + second_values
    plotted_span = max(plotted) - min(plotted)
    assert options["y_min"] <= min(plotted) - 0.08 * plotted_span
    assert options["y_max"] >= max(plotted) + 0.08 * plotted_span
    assert "dsc_full_peak_envelope_axis" in options["_autofixes_applied"]
