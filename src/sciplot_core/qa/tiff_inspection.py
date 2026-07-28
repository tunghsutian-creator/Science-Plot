"""Inspect TIFF size, resolution, color, and alpha metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from PIL import Image
from sciplot_core.foundation.file_hashing import file_sha256


def _tiff_info(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        dpi_value = image.info.get("dpi")
        if isinstance(dpi_value, tuple | list) and len(dpi_value) >= 2:
            dpi = [float(dpi_value[0]), float(dpi_value[1])]
        else:
            dpi = [0.0, 0.0]
        width_px, height_px = image.size
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "pixel_size": [int(width_px), int(height_px)],
        "dpi": [round(dpi[0], 3), round(dpi[1], 3)],
        "physical_size_mm": [
            round(width_px / dpi[0] * 25.4, 3) if dpi[0] > 0 else None,
            round(height_px / dpi[1] * 25.4, 3) if dpi[1] > 0 else None,
        ],
    }
