"""Independent old/new rendering-contract regression, never a self-rebuild audit.

Callers supply semantically aligned structural snapshots and the two native
rasters. No registration, resizing, cropping or ignored structural fields can
hide geometry drift. Image tolerance covers small channel-level antialias noise;
it does not excuse a one-pixel displacement or a missing thin stroke.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image


@dataclass(frozen=True)
class RasterTolerance:
    """Fixed thresholds; foreground normalization prevents white-page dilution."""

    channel_noise: int = 8
    max_changed_ink_fraction: float = 0.005
    max_ink_mass_fraction: float = 0.01

    def __post_init__(self) -> None:
        if not 0 <= self.channel_noise <= 255:
            raise ValueError("channel_noise must be within 0..255")
        for value in (self.max_changed_ink_fraction, self.max_ink_mass_fraction):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Raster fraction thresholds must be within 0..1")


_DEFAULT_TOLERANCE = RasterTolerance()


def structural_diff(
    old: dict[str, Any], new: dict[str, Any], *, numeric_tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Compare every leaf with JSON-pointer paths and explicit missing values."""

    if not math.isfinite(numeric_tolerance) or numeric_tolerance < 0:
        raise ValueError("numeric_tolerance must be finite and nonnegative")
    differences: list[dict[str, Any]] = []
    checked: list[str] = []

    def compare(left: Any, right: Any, path: str) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(left.keys() | right.keys()):
                child = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
                if key not in left or key not in right:
                    checked.append(child)
                    differences.append({
                        "path": child, "old": left.get(key), "new": right.get(key),
                        "reason": "missing_old" if key not in left else "missing_new",
                    })
                else:
                    compare(left[key], right[key], child)
            if not left and not right:
                checked.append(path)
            return
        if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
            for index, (a, b) in enumerate(zip(left, right, strict=True)):
                compare(a, b, path + f"/{index}")
            if not left:
                checked.append(path)
            return
        checked.append(path)
        number_pair = (isinstance(left, int | float) and not isinstance(left, bool)
                       and isinstance(right, int | float) and not isinstance(right, bool))
        equal = (math.isfinite(left) and math.isfinite(right)
                 and math.isclose(left, right, rel_tol=0, abs_tol=numeric_tolerance)
                 if number_pair else type(left) is type(right) and left == right)
        if not equal:
            differences.append({"path": path, "old": left, "new": right,
                                "reason": "value_changed"})

    compare(old, new, "")
    return {"status": "passed" if not differences else "failed",
            "numeric_tolerance": numeric_tolerance, "checked_paths": checked,
            "checked_count": len(checked), "difference_count": len(differences),
            "differences": differences}


def _rgb(path: Path) -> NDArray[np.uint8]:
    with Image.open(path) as original:
        rgba = original.convert("RGBA")
        white = Image.new("RGBA", rgba.size, "white")
        white.alpha_composite(rgba)
        return np.asarray(white.convert("RGB"), dtype=np.uint8)


def _bounds(mask: NDArray[np.bool_]) -> list[int] | None:
    yy, xx = np.nonzero(mask)
    return [int(xx.min()), int(yy.min()), int(xx.max()) + 1,
            int(yy.max()) + 1] if len(xx) else None


def _regions(mask: NDArray[np.bool_]) -> list[dict[str, Any]]:
    """Bound connected 16-pixel tiles; bounds use actual changed pixels."""

    tile = 16
    height, width = mask.shape
    rows, columns = (height + tile - 1) // tile, (width + tile - 1) // tile
    padded = np.pad(mask, ((0, rows * tile - height), (0, columns * tile - width)))
    grid = padded.reshape(rows, tile, columns, tile).any(axis=(1, 3))
    unseen = set(zip(*np.nonzero(grid), strict=True))
    regions: list[dict[str, Any]] = []
    while unseen:
        first = min(unseen)
        unseen.remove(first)
        queue, group = [first], []
        while queue:
            row, column = queue.pop()
            group.append((row, column))
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                neighbor = (row + dr, column + dc)
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
        y1, x1 = (int(min(p[i] for p in group)) * tile for i in (0, 1))
        y2, x2 = ((int(max(p[i] for p in group)) + 1) * tile for i in (0, 1))
        local = np.zeros_like(mask[y1:y2, x1:x2])
        for row, column in group:
            local_top, local_left = int(row) * tile - y1, int(column) * tile - x1
            local[local_top:local_top + tile, local_left:local_left + tile] = (
                mask[int(row) * tile:(int(row) + 1) * tile,
                     int(column) * tile:(int(column) + 1) * tile])
        bounds = _bounds(local)
        if bounds is not None:
            regions.append({"bbox_px": [bounds[0] + x1, bounds[1] + y1,
                                        bounds[2] + x1, bounds[3] + y1],
                            "changed_pixels": int(local.sum())})
    return regions


def compare_rasters(
    old_path: Path, new_path: Path, *, output_dir: Path,
    tolerance: RasterTolerance = _DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """Write old/new/diff PNG evidence and return a fail-closed native pixel gate."""

    left, right = _rgb(old_path), _rgb(new_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray(left).save(output_dir / "old.png")
    Image.fromarray(right).save(output_dir / "new.png")
    same_size = left.shape == right.shape
    height, width = max(left.shape[0], right.shape[0]), max(left.shape[1], right.shape[1])
    arrays = [np.full((height, width, 3), 255, dtype=np.uint8) for _ in range(2)]
    for image, canvas in zip((left, right), arrays, strict=True):
        canvas[:image.shape[0], :image.shape[1]] = image
    a, b = (array.astype(np.float64) for array in arrays)
    delta = np.abs(a - b)
    changed = np.max(delta, axis=2) > tolerance.channel_noise
    if not same_size:
        overlap_height, overlap_width = min(left.shape[0], right.shape[0]), min(left.shape[1], right.shape[1])
        changed[overlap_height:, :] = True
        changed[:, overlap_width:] = True
    ink_a, ink_b = (np.max(255 - array, axis=2) / 255 for array in (a, b))
    foreground = np.maximum(ink_a, ink_b) > tolerance.channel_noise / 255
    foreground_count = int(foreground.sum())
    changed_fraction = int(changed.sum()) / max(foreground_count, 1)
    mass_fraction = abs(float(ink_a.sum() - ink_b.sum())) / max(float(ink_a.sum()), float(ink_b.sum()), 1)
    rmse = float(np.sqrt(np.mean(np.square(delta))))
    failures = []
    if not same_size:
        failures.append("canvas_dimensions_changed")
    if foreground_count == 0:
        failures.append("blank_raster")
    if changed_fraction > tolerance.max_changed_ink_fraction:
        failures.append("changed_ink_exceeds_tolerance")
    if mass_fraction > tolerance.max_ink_mass_fraction:
        failures.append("ink_mass_exceeds_tolerance")
    visualization = (arrays[0].astype(float) * .2 + 255 * .8).astype(np.uint8)
    visualization[np.max(delta, axis=2) > 0] = [255, 180, 0]
    visualization[changed] = [220, 0, 45]
    Image.fromarray(visualization).save(output_dir / "diff.png")
    return {
        "status": "failed" if failures else "passed", "failures": failures,
        "old_size_px": [left.shape[1], left.shape[0]],
        "new_size_px": [right.shape[1], right.shape[0]],
        "tolerance": asdict(tolerance), "registration_applied": False,
        "raw_changed_pixels": int((np.max(delta, axis=2) > 0).sum()),
        "changed_pixels": int(changed.sum()), "changed_ink_fraction": changed_fraction,
        "ink_mass_fraction": mass_fraction, "mae": float(np.mean(delta)),
        "rmse": rmse, "psnr_db": 20 * math.log10(255 / rmse) if rmse else None,
        "exact_pixel_fraction": float((np.max(delta, axis=2) == 0).mean()),
        "changed_bbox_px": _bounds(changed), "changed_regions": _regions(changed),
        "bbox_convention": "left,top,right-exclusive,bottom-exclusive",
        "region_grouping": "connected_16px_tiles", "difference_legend": {
            "red": "above_channel_tolerance", "orange": "within_channel_tolerance"},
        "artifacts": {name: str((output_dir / f"{name}.png").resolve())
                      for name in ("old", "new", "diff")},
        "source_sha256": {"old": hashlib.sha256(old_path.read_bytes()).hexdigest(),
                          "new": hashlib.sha256(new_path.read_bytes()).hexdigest()},
    }


def rendering_contract_regression(
    old_structure: dict[str, Any], new_structure: dict[str, Any], *,
    old_image: Path, new_image: Path, output_dir: Path,
    old_environment: dict[str, Any], new_environment: dict[str, Any],
    tolerance: RasterTolerance = _DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """Join independent structure, environment and pixel gates with local evidence."""

    structure = structural_diff(old_structure, new_structure)
    if not old_structure or not new_structure:
        structure["status"] = "failed"
        structure["reason"] = "resolved_rendering_structure_required"
    environment = structural_diff(old_environment, new_environment)
    if not old_environment or not new_environment:
        environment["status"] = "failed"
        environment["reason"] = "renderer_and_font_environment_required"
    raster = compare_rasters(old_image, new_image, output_dir=output_dir,
                             tolerance=tolerance)
    report = {"kind": "sciplot_rendering_contract_regression", "version": 1,
              "status": "passed" if all(check["status"] == "passed"
                for check in (structure, environment, raster)) else "failed",
              "structure": structure, "environment": environment, "raster": raster}
    for name, payload in (("old-structure", old_structure), ("new-structure", new_structure),
                          ("structural-diff", structure), ("regression", report)):
        (output_dir / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8")
    return report
