from __future__ import annotations

import json
from pathlib import Path

import fitz
import pandas as pd
import pytest

from sciplot_core.figure_workflow import (
    PLOT_READY_REQUEST_KIND,
    build_shared_scalar_strip_spec,
    delivery_launcher_dry_run,
    run_plot_ready_figure_request,
)
from sciplot_core.policy import (
    DEFAULT_SCALAR_FIELD_COLORMAP_ID,
    DEFAULT_SCALAR_FIELD_COLORS,
    UNIFIED_LEFT_MARGIN_MM,
    UNIFIED_RIGHT_MARGIN_MM,
)


def _panel(sample: str, peak: float) -> dict[str, object]:
    return {
        "sample": sample,
        "source": f"{sample}.csv",
        "x_column": "thickness_position_mm",
        "value_column": "gradient_per_mm",
        "x_values": [-2.0, -1.5, -1.0, -0.5, 0.0],
        "z_values": [0.0, 0.5, peak, 0.5, 0.0],
    }


def test_shared_scalar_strip_requires_explicit_color_range() -> None:
    with pytest.raises(ValueError, match="explicit numeric `z_min`"):
        build_shared_scalar_strip_spec([_panel("E0", 35.0)])


@pytest.mark.parametrize(
    "colors",
    [
        ["#00000000", "#FFFFFF00"],
        ["#123456", "#123456FF"],
    ],
)
def test_shared_scalar_strip_rejects_invisible_colormaps(
    colors: list[str],
) -> None:
    with pytest.raises(ValueError, match="colormap_colors"):
        build_shared_scalar_strip_spec(
            [_panel("E0", 35.0)],
            options={
                "z_min": 0.0,
                "z_max": 40.0,
                "z_ticks": [0.0, 20.0, 40.0],
                "colormap_colors": colors,
            },
        )


def test_shared_scalar_strip_geometry_and_single_color_contract() -> None:
    spec = build_shared_scalar_strip_spec(
        [
            _panel("E0", 35.0),
            _panel("E2", 23.0),
            _panel("E3", 20.0),
            _panel("E4", 18.0),
        ],
        options={"z_min": 0.0, "z_max": 40.0, "z_ticks": [0, 10, 20, 30, 40]},
    )

    assert spec["size_mm"] == [120.0, 42.0]
    assert spec["scalar"] == {
        "name": "Γ_{G′}",
        "unit": "(mm⁻¹)",
        "min": 0.0,
        "max": 40.0,
        "ticks": [0.0, 10.0, 20.0, 30.0, 40.0],
        "colormap_name": DEFAULT_SCALAR_FIELD_COLORMAP_ID,
        "colormap_colors": list(DEFAULT_SCALAR_FIELD_COLORS),
        "color_invert": False,
        "shared_across_panels": True,
    }
    assert spec["geometry"]["outer_frame_x_mm"] == [
        UNIFIED_LEFT_MARGIN_MM,
        120.0 - UNIFIED_RIGHT_MARGIN_MM,
    ]
    assert spec["geometry"]["colorbar_frame_mm"] == [8.2, 6.0, 10.4, 34.0]
    assert spec["geometry"]["panel_width_mm"] == pytest.approx(24.55)
    panel_frames = [
        (panel["left_mm"], panel["right_mm"])
        for panel in spec["panels"]
    ]
    expected_frames = [
        (14.0, 38.55),
        (39.65, 64.2),
        (65.3, 89.85),
        (90.95, 115.5),
    ]
    for actual, expected in zip(panel_frames, expected_frames, strict=True):
        assert actual == pytest.approx(expected)
    assert spec["display_transform"]["scientific_values_changed"] is False


def test_plot_ready_cloud_request_exports_editable_minimal_package(tmp_path: Path) -> None:
    samples = ("E0", "E2", "E3", "E4")
    panel_requests: list[dict[str, str]] = []
    for index, sample in enumerate(samples):
        source = tmp_path / f"{sample}.csv"
        pd.DataFrame(
            {
                "thickness_position_mm": [-2.0, -1.5, -1.0, -0.5, 0.0],
                "gradient_per_mm": [0.0, 0.5, 35.0 - 5.0 * index, 0.5, 0.0],
            }
        ).to_csv(source, index=False)
        panel_requests.append(
            {
                "sample": sample,
                "data": source.name,
                "x_column": "thickness_position_mm",
                "value_column": "gradient_per_mm",
            }
        )
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "kind": PLOT_READY_REQUEST_KIND,
                "version": 1,
                "exports": ["pdf", "tiff_300"],
                "figures": [
                    {
                        "id": "gradient_cloud",
                        "profile": "relative_gradient_strip_v1",
                        "panels": panel_requests,
                        "options": {
                            "z_min": 0.0,
                            "z_max": 40.0,
                            "z_ticks": [0, 10, 20, 30, 40],
                        },
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = run_plot_ready_figure_request(request, output_dir=tmp_path / "output")

    assert result["status"] == "ready"
    output = Path(result["output_dir"])
    assert {path.name for path in (output / "delivery").iterdir()} == {
        "data",
        "pdf",
        "tiff",
        "project",
        "Open_in_Veusz.command",
    }
    document = output / "project" / "gradient_cloud.vsz"
    text = document.read_text(encoding="utf-8")
    assert text.count("Add('colorbar', name='gradient_colorbar'") == 1
    assert text.count("Add('image', name='relative_gradient_field'") == 4
    assert f"Set('colorMap', '{DEFAULT_SCALAR_FIELD_COLORMAP_ID}')" in text
    assert f"AddCustom('colormap', '{DEFAULT_SCALAR_FIELD_COLORMAP_ID}'" in text
    assert "Set('label', 'Thickness position (mm)')" in text
    assert "Set('label', 'Γ_{G′}')" in text
    assert "Set('label', '(mm⁻¹)')" in text
    assert text.count("Set('Text/bold', False)") >= 4

    pdf = output / "figures" / "gradient_cloud.pdf"
    with fitz.open(pdf) as rendered:
        rect = rendered[0].rect
        assert float(rect.width) * 25.4 / 72.0 == pytest.approx(120.0, abs=0.1)
        assert float(rect.height) * 25.4 / 72.0 == pytest.approx(42.0, abs=0.1)
        page_text = rendered[0].get_text("text")
        assert "Thickness position (mm)" in page_text
        assert all(sample in page_text for sample in samples)

    launcher_check = delivery_launcher_dry_run(
        output / "delivery",
        ["gradient_cloud.vsz"],
    )
    assert launcher_check["passed"] is True
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scientific_processing"]["performed"] is False
    assert manifest["qa"]["status"] == "passed"
    assert manifest["delivery_verification"]["passed"] is True
    assert all(
        item["passed"]
        for item in manifest["delivery_verification"]["artifact_hashes"]
    )
