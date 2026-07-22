from pathlib import Path

import pandas as pd

from sciplot_core.semantic import read_impact_condition_payloads
from sciplot_core.studio import (
    _impact_condition_figure_queue,
    _veusz_axis_label,
)


def test_impact_workbook_sheets_are_independent_figure_conditions(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "impact.xlsx"
    with pd.ExcelWriter(source) as writer:
        for thickness, samples in (
            ("2mm", ("E0", "E2")),
            ("4mm", ("E0", "E2")),
            ("6mm", ("E3", "E4")),
        ):
            pd.DataFrame(
                [
                    ["Re", "Re"],
                    ["kJ/m²", "kJ/m²"],
                    list(samples),
                    [1.0, 2.0],
                    [1.5, 2.5],
                ]
            ).to_excel(writer, sheet_name=thickness, header=False, index=False)

    payloads = read_impact_condition_payloads(source)
    queue = _impact_condition_figure_queue(
        {"rule_id": "impact_metric", "input": str(source_dir)},
        base_dir=tmp_path,
        project_dir=tmp_path / "project",
    )

    assert [condition for condition, _payload in payloads] == ["2mm", "4mm", "6mm"]
    assert [item["id"] for item in queue] == ["impact_2mm", "impact_4mm", "impact_6mm"]
    assert [item["sample_order"] for item in queue] == [
        ["E0", "E2"],
        ["E0", "E2"],
        ["E3", "E4"],
    ]
    assert all(Path(item["condition_source"]).is_file() for item in queue)


def test_veusz_axis_label_closes_unit_superscript_before_parenthesis() -> None:
    assert _veusz_axis_label("Wavenumber (cm$^{-1}$)") == "Wavenumber (cm⁻¹)"
    assert _veusz_axis_label("Scattering vector (nm$^{-1}$)") == "Scattering vector (nm⁻¹)"
