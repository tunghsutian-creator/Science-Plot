from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.studio_render.models import StudioPreparationBlocked
from sciplot_core.studio_render.terminal_contract import (
    derive_terminal_render_data_contract,
)


def _write_conditions(path: Path) -> None:
    with pd.ExcelWriter(path) as writer:
        for condition, offset in (("2mm", 0.0), ("4mm", 10.0)):
            pd.DataFrame(
                [
                    ["Re", "Re"],
                    ["kJ/m²", "kJ/m²"],
                    ["A", "B"],
                    [offset + 1.0, offset + 2.0],
                    [offset + 1.2, offset + 2.2],
                ]
            ).to_excel(writer, sheet_name=condition, header=False, index=False)


def test_impact_workbook_replays_layered_conditions_and_all_raw_observations(
    tmp_path: Path,
) -> None:
    source = tmp_path / "impact.xlsx"
    _write_conditions(source)
    request = {
        "rule_id": "impact_metric",
        "template": "point_line",
        "condition_order": ["4mm", "2mm"],
        "condition_label_mapping": {"4mm": "4 mm specimen", "2mm": "2 mm specimen"},
        "series_order": ["4 mm specimen", "4 mm specimen · A mean"],
        "render_options": {
            "series_order": ["4 mm specimen", "2 mm specimen"],
            "size": "60x55",
        },
    }
    original_request = deepcopy(request)
    original_bytes = source.read_bytes()

    result = derive_terminal_render_data_contract(
        request=request, terminal_sources=[source]
    )
    units = result["units"]
    by_label = {unit["label"]: unit for unit in units}

    assert result["status"] == "passed"
    assert result["unit_count"] == 10
    assert [units[0]["label"], units[5]["label"]] == ["4 mm specimen", "2 mm specimen"]
    assert by_label["4 mm specimen"]["y_values"] == pytest.approx([11.1, 12.1])
    assert by_label["2 mm specimen"]["y_values"] == pytest.approx([1.1, 2.1])
    raw_units = [
        unit
        for unit in units
        if unit["presentation_kind"] == "impact_point_line_raw_points"
    ]
    assert sum(len(unit["y_values"]) for unit in raw_units) == 8
    assert by_label["4 mm specimen · A raw"]["y_values"] == [11.0, 11.2]
    assert by_label["2 mm specimen · B raw"]["y_values"] == [2.0, 2.2]
    assert all(
        unit["plot_line_hide"]
        for unit in units
        if unit["category_position"] is not None
    )
    assert by_label["4 mm specimen"]["plot_line_hide"] is False
    assert all(unit["source_artifacts"] == result["source_artifacts"] for unit in units)
    assert "kJ" in units[0]["axes"]["y"]["label"]
    assert request == original_request
    assert source.read_bytes() == original_bytes


def test_impact_replay_requires_one_workbook_and_known_conditions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "impact.xlsx"
    second = tmp_path / "second.xlsx"
    _write_conditions(source)
    _write_conditions(second)
    request = {"rule_id": "impact_metric", "template": "point_line"}

    with pytest.raises(ValueError, match="one condition workbook"):
        derive_terminal_render_data_contract(
            request=request, terminal_sources=[source, second]
        )
    with pytest.raises(
        StudioPreparationBlocked, match="Unknown impact point-line condition"
    ):
        derive_terminal_render_data_contract(
            request={**request, "condition_order": ["missing", "2mm"]},
            terminal_sources=[source],
        )


def test_ordinary_terminal_replay_still_rejects_unknown_series_order(
    tmp_path: Path,
) -> None:
    source = tmp_path / "curve.csv"
    source.write_text("Time,Response\ns,Pa\n,A\n0,10\n1,11\n", encoding="utf-8")

    with pytest.raises(StudioPreparationBlocked, match="series_order contains unknown"):
        derive_terminal_render_data_contract(
            request={"template": "curve", "series_order": ["missing"]},
            terminal_sources=[source],
        )
