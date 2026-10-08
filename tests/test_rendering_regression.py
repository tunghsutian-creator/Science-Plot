"""Discriminating controls for independent old/new rendering regression."""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import pytest

from sciplot_core.qa.rendering_regression import (
    RasterTolerance,
    compare_rasters,
    rendering_contract_regression,
    structural_diff,
)


def _image(path: Path, *, width: int = 2, shift: int = 0, text_scale: int = 1) -> None:
    image = Image.new("RGB", (320, 250), "white")
    draw = ImageDraw.Draw(image)
    draw.line((35 + shift, 20, 35 + shift, 210, 290 + shift, 210), fill="black", width=1)
    draw.line((45 + shift, 190, 100 + shift, 165, 145 + shift, 170, 280 + shift, 35),
              fill="#3568c0", width=width)
    text = Image.new("RGB", (120, 15), "white")
    ImageDraw.Draw(text).text((0, 0), "Frequency (Hz)", fill="black")
    image.paste(text.resize((120 * text_scale, 15 * text_scale)), (100, 218))
    image.save(path)


def test_structural_diff_covers_every_leaf_without_native_identity_dependence() -> None:
    original = {"size_mm": [60, 55], "axes": {"x/axis": {"font": "Arial", "size_pt": 7}},
                "legend": {"enabled": True}, "series": [{"width_pt": 1.2}],
                "unspecified": "unspecified", "empty": []}
    changed = deepcopy(original)
    changed["axes"]["x/axis"]["size_pt"] = 8
    changed["series"][0]["width_pt"] = 0.7
    result = structural_diff(original, changed)
    assert result["status"] == "failed"
    assert result["checked_count"] == 8
    assert {item["path"] for item in result["differences"]} == {
        "/axes/x~1axis/size_pt", "/series/0/width_pt"}


def test_structural_missing_null_boolean_and_small_geometry_are_not_hidden() -> None:
    result = structural_diff({"null": None, "enabled": True, "left_mm": 12.0},
                             {"enabled": 1, "left_mm": 12.00001})
    assert result["difference_count"] == 3
    assert result["differences"][-1]["reason"] == "missing_new"
    assert structural_diff({"n": 1.0}, {"n": 1})["status"] == "passed"
    assert structural_diff({"n": float("nan")}, {"n": float("nan")})["status"] == "failed"


def test_identical_native_rasters_pass_and_write_readable_artifacts(tmp_path: Path) -> None:
    old, new = tmp_path / "old.png", tmp_path / "new.png"
    _image(old)
    _image(new)
    result = compare_rasters(old, new, output_dir=tmp_path / "evidence")
    assert result["status"] == "passed"
    assert result["changed_bbox_px"] is None
    assert result["changed_regions"] == []
    assert result["exact_pixel_fraction"] == 1
    assert result["registration_applied"] is False
    for artifact in result["artifacts"].values():
        with Image.open(artifact) as image:
            assert image.size == (320, 250)


def test_bounded_antialias_channel_noise_passes_without_geometric_tolerance(tmp_path: Path) -> None:
    old, new = tmp_path / "old.png", tmp_path / "new.png"
    _image(old)
    with Image.open(old) as image:
        pixels = np.array(image)
    pixels[190, 45] = np.minimum(pixels[190, 45].astype(int) + 4, 255)
    Image.fromarray(pixels).save(new)
    result = compare_rasters(old, new, output_dir=tmp_path / "evidence")
    assert result["status"] == "passed"
    assert result["raw_changed_pixels"] == 1
    assert result["changed_pixels"] == 0


@pytest.mark.parametrize("change", [{"width": 3}, {"shift": 1}, {"text_scale": 2}])
def test_line_layout_and_font_size_drift_fail_raster_gate(tmp_path: Path, change: dict) -> None:
    old, new = tmp_path / "old.png", tmp_path / "new.png"
    _image(old)
    _image(new, **change)
    result = compare_rasters(old, new, output_dir=tmp_path / "evidence")
    assert result["status"] == "failed"
    assert result["changed_pixels"] > 0
    assert result["changed_bbox_px"] is not None
    assert result["changed_regions"]
    assert result["psnr_db"] > 0


def test_extra_blank_canvas_cannot_pass_by_white_padding(tmp_path: Path) -> None:
    old, new = tmp_path / "old.png", tmp_path / "new.png"
    _image(old)
    with Image.open(old) as image:
        larger = Image.new("RGB", (321, 250), "white")
        larger.paste(image)
        larger.save(new)
    result = compare_rasters(old, new, output_dir=tmp_path / "evidence")
    assert result["status"] == "failed"
    assert "canvas_dimensions_changed" in result["failures"]


def test_blank_old_and_new_are_not_positive_evidence(tmp_path: Path) -> None:
    path = tmp_path / "blank.png"
    Image.new("RGB", (20, 20), "white").save(path)
    result = compare_rasters(path, path, output_dir=tmp_path / "evidence")
    assert result["status"] == "failed"
    assert result["failures"] == ["blank_raster"]


def test_structure_and_environment_are_independent_hard_gates(tmp_path: Path) -> None:
    path = tmp_path / "native.png"
    _image(path)
    result = rendering_contract_regression({"font": "Arial"}, {"font": "Helvetica"},
        old_image=path, new_image=path, output_dir=tmp_path / "evidence",
        old_environment={"renderer": "1", "font_hash": "abc"},
        new_environment={"renderer": "1", "font_hash": "xyz"})
    assert result["raster"]["status"] == "passed"
    assert result["structure"]["status"] == "failed"
    assert result["environment"]["status"] == "failed"
    assert result["status"] == "failed"
    saved = json.loads((tmp_path / "evidence/regression.json").read_text())
    assert saved == result


def test_undeclared_environment_cannot_certify_regression(tmp_path: Path) -> None:
    path = tmp_path / "native.png"
    _image(path)
    result = rendering_contract_regression({}, {}, old_image=path, new_image=path,
        output_dir=tmp_path / "evidence", old_environment={}, new_environment={})
    assert result["status"] == "failed"
    assert result["environment"]["reason"] == "renderer_and_font_environment_required"


@pytest.mark.parametrize("arguments", [{"channel_noise": -1}, {"channel_noise": 256},
    {"max_changed_ink_fraction": -1}, {"max_ink_mass_fraction": float("nan")}])
def test_invalid_tolerances_fail_closed(arguments: dict) -> None:
    with pytest.raises(ValueError):
        RasterTolerance(**arguments)
