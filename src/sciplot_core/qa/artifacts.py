"""Discover canonical figure artifacts and assess raster visibility."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import fitz
import numpy as np


def _raster_visual_qa(pixmap: fitz.Pixmap) -> dict[str, Any]:
    channels = int(pixmap.n)
    if channels <= 0 or pixmap.width <= 0 or pixmap.height <= 0:
        raise ValueError("PDF rasterization produced an invalid pixmap.")
    pixels = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, channels
    )
    rgb = pixels[:, :, :3] if channels >= 3 else np.repeat(pixels[:, :, :1], 3, axis=2)
    luminance = rgb.astype(float).mean(axis=2)
    ink_mask = luminance < 248.0
    ink_count = int(np.count_nonzero(ink_mask))
    total = int(ink_mask.size)
    if ink_count == 0:
        raise ValueError("PDF raster appears blank.")
    ys, xs = np.where(ink_mask)
    bbox_area = int((xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1))
    ink_fraction = ink_count / max(total, 1)
    bbox_fraction = bbox_area / max(total, 1)
    if ink_fraction < 0.0005:
        raise ValueError(f"PDF raster has too little visible ink: {ink_fraction:.6f}.")
    return {
        "raster_width_px": int(pixmap.width),
        "raster_height_px": int(pixmap.height),
        "ink_fraction": round(float(ink_fraction), 6),
        "content_bbox_fraction": round(float(bbox_fraction), 6),
        "content_bbox_px": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
    }


def _canonical_artifacts(output_dir: Path, suffixes: tuple[str, ...]) -> list[Path]:
    figures_dir = output_dir / "figures"
    if figures_dir.exists():
        direct_figures = sorted(
            path
            for path in figures_dir.iterdir()
            if path.is_file() and path.suffix.casefold() in suffixes
        )
        if direct_figures:
            return direct_figures
        figures = sorted(
            path
            for path in figures_dir.rglob("*")
            if path.is_file()
            and path.suffix.casefold() in suffixes
            and not any(
                part.startswith("_") for part in path.relative_to(figures_dir).parts
            )
        )
        if figures:
            return figures
    direct = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.suffix.casefold() in suffixes
    )
    if direct:
        return direct
    excluded = {"delivery", "studio", "_veusz", "_sciplot_internal"}
    return sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file()
        and path.suffix.casefold() in suffixes
        and not excluded.intersection(path.relative_to(output_dir).parts)
    )
