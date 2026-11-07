"""Shared raster metadata, retaining streaming TIFF and immutable PNG inputs."""

from io import BytesIO
from hashlib import sha256
from pathlib import Path
from typing import Any
from PIL import Image
from sciplot_core.foundation.file_hashing import file_sha256


def _metadata(image: Image.Image) -> dict[str, Any]:
    dpi_value = image.info.get("dpi")
    dpi = [float(dpi_value[0]), float(dpi_value[1])] if isinstance(dpi_value, tuple | list) and len(dpi_value) >= 2 else [0.0, 0.0]
    width, height = image.size
    return {"pixel_size": [int(width), int(height)], "dpi": [round(dpi[0], 3), round(dpi[1], 3)],
            "physical_size_mm": [round(width / dpi[0] * 25.4, 3) if dpi[0] > 0 else None,
                                 round(height / dpi[1] * 25.4, 3) if dpi[1] > 0 else None]}


def _tiff_info(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        metadata = _metadata(image)
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": file_sha256(path), **metadata}


def _png_info(path: Path, content: bytes) -> dict[str, Any]:
    with Image.open(BytesIO(content)) as image:
        if image.format != "PNG":
            raise ValueError(f"Raster bytes do not match the declared PNG artifact: {path}")
        metadata = _metadata(image)
    return {"path": str(path), "size_bytes": len(content), "sha256": sha256(content).hexdigest(), **metadata}
