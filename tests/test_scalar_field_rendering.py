from __future__ import annotations

from pathlib import Path

import pandas as pd

from sciplot_core.render import render_to_dir
from sciplot_core.studio import (
    _reference_guides_contract,
    _scalar_field_from_frames,
    _scalar_field_plot_contract,
)


def test_scalar_field_contract_preserves_xy_orientation_and_zero_transparency() -> None:
    frame = pd.DataFrame(
        {
            "thickness_mm": [-2.0, 0.0, 2.0, -2.0, 0.0, 2.0],
            "in_plane_mm": [0.0, 0.0, 0.0, 20.0, 20.0, 20.0],
            "temperature_C": [125.0, 265.0, 125.0, 125.0, 265.0, 125.0],
        }
    )
    series, axis_info = _scalar_field_from_frames(
        [("field", frame)],
        render_options={
            "data_variables": {
                "x": "thickness_mm",
                "y": "in_plane_mm",
                "z": "temperature_C",
            }
        },
    )
    scalar = axis_info["scalar_field"]
    assert len(series) == 1
    assert scalar["x_values"] == [-2.0, 0.0, 2.0]
    assert scalar["y_values"] == [0.0, 20.0]
    assert scalar["grid_shape"] == [2, 3]
    assert scalar["z_values"] == [[125.0, 265.0, 125.0], [125.0, 265.0, 125.0]]
    plot_contract = _scalar_field_plot_contract(
        axis_info,
        render_options={"colorbar_vert_manual": 0.0},
        template_id="heatmap",
    )
    assert plot_contract is not None
    assert plot_contract["colorbar_vert_manual"] == 0.0

    guides = _reference_guides_contract(
        {
            "reference_guides": [
                {
                    "kind": "band",
                    "axis": "x",
                    "start": -1.0,
                    "end": -0.8,
                    "color": "#ECECEC",
                    "transparency": 0,
                }
            ]
        }
    )
    assert guides[0]["transparency"] == 0


def test_public_render_writes_editable_scalar_field_with_visible_overlay_order(
    tmp_path: Path,
) -> None:
    source = tmp_path / "field.csv"
    pd.DataFrame(
        {
            "x": [0.0, 1.0, 2.0, 0.0, 1.0, 2.0],
            "y": [0.0, 0.0, 0.0, 1.0, 1.0, 1.0],
            "z": [1.0, 2.0, 3.0, 2.0, 3.0, 4.0],
        }
    ).to_csv(source, index=False)
    result = render_to_dir(
        source,
        template="heatmap",
        output_dir=tmp_path / "rendered",
        options={
            "size": "60x55",
            "data_variables": {"x": "x", "y": "y", "z": "z"},
            "z_min": 1.0,
            "z_max": 4.0,
            "contour_levels": [2.0, 3.0],
            "highlight_contour_levels": [2.5],
            "show_colorbar": True,
            "colorbar_direction": "horizontal",
        },
        export_formats=("pdf",),
    )
    assert result["render_engine"] == "veusz"
    assert all(Path(path).exists() for path in result["outputs"])
    assert all(not report["issues"] for report in result["qa_reports"])

    document = Path(result["veusz_documents"][0])
    text = document.read_text(encoding="utf-8")
    colorbar_index = text.index("Add('colorbar', name='field_colorbar'")
    contour_index = text.index("Add('contour', name='field_contours'")
    image_index = text.index("Add('image', name='field_image'")
    assert colorbar_index < image_index
    assert contour_index < image_index
    assert "Set('widgetName', 'field_image')" in text
    colorbar_block = text[colorbar_index:image_index]
    assert "Set('min', 1.0)" in colorbar_block
    assert "Set('max', 4.0)" in colorbar_block
    assert "Add('rect', name='page_export_background'" in text
