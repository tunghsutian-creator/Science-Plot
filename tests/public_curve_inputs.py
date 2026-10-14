"""Independently generated tables; no measured fixture or provenance is read."""
from __future__ import annotations

import csv
import math
from pathlib import Path

import pandas as pd

PAIR_AXES = {
    "dsc_curve": ("Temperature", "Heat Flow", "C", "W/g"),
    "tga_curve": ("Temperature", "Mass", "C", "%"),
    "dtg_curve": ("Temperature", "Derivative mass", "C", "%/C"),
    "uvvis_spectrum": ("Wavelength", "Absorbance", "nm", "a.u."),
    "xrd_pattern": ("2 theta", "Intensity", "deg", "counts"),
    "saxs_profile": ("q", "Intensity", "nm^-1", "a.u."),
    "dma_frequency_sweep": ("Angular Frequency", "Storage Modulus", "rad/s", "Pa"),
}


def paired_source(directory: Path, rule_id: str) -> tuple[Path, tuple[tuple[tuple[float, float], ...], ...]]:
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f"generated_{rule_id}.csv"
    x, y, xu, yu = PAIR_AXES[rule_id]
    points = (((7.0, 2.0), (5.0, 9.0), (3.0, 4.0)), ((2.0, 6.0), (8.0, 3.0)))
    if rule_id in {"dsc_curve", "dtg_curve"}:
        points = (((7.0, -2.0), (5.0, 9.0), (3.0, -4.0)), points[1])
    rows: list[list[object]] = [[x, y, x, y], [xu, yu, xu, yu],
                               ["Generated Cedar", "Generated Cedar", "Generated Birch", "Generated Birch"]]
    for index in range(3):
        rows.append([value for series in points for value in (series[index] if index < len(series) else ("", ""))])
    with source.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    return source, points


def dma_source(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "generated_dma.csv"
    source.write_text(
        "Temperature (C),Cedar Storage Modulus (MPa),Temperature (C),Birch Storage Modulus (MPa)\n"
        "-5,8,-4,3\n5,4,6,1\n15,-2.5,,\n25,1,,\n", encoding="utf-8",
    )
    return source


def gpc_source(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for index, label in enumerate(("Cedar", "Birch")):
        with pd.ExcelWriter(directory / f"{label}.xlsx") as writer:
            pd.DataFrame([
                ["Sample Name", label], ["Mw (g/mol)", "LogM", "dW/dLogM"],
                [100 + 50 * index, math.log10(100 + 50 * index), .2],
                [1000 + 500 * index, math.log10(1000 + 500 * index), .8],
            ]).to_excel(writer, sheet_name="Slice Table", index=False, header=False)
    return directory


def neutral_ftir_source(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "generated_ftir.csv"
    path.write_text("4000,0\n3500,-1\n3000,2\n", encoding="utf-8")
    return path
