"""Small generated mechanical and rheology experiments for behavior controls."""
from __future__ import annotations

import csv
from pathlib import Path


def temperature_source(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for index, label in enumerate(("Cedar", "Birch", "Maple")):
        (directory / f"{label}.tsv").write_text(
            "Temperature\tStorage Modulus\tLoss Modulus\tTan Delta\n"
            "C\tPa\tPa\t\n"
            + "\n".join(f"{40 - row * 10}\t{1200 + index * 70 - row * 50}\t{300 + index * 20}\t{.25 + row * .02}"
                        for row in range(4)) + "\n", encoding="utf-8",
        )
    return directory


def mechanical_source(directory: Path, rule_id: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    if rule_id == "tensile_curve":
        directory = directory / "Cedar.is_tens_exports"
        directory.mkdir()
        for number, factor in enumerate((1., 2., 4.), start=1):
            (directory / f"Cedar__repeat {number}.csv").write_text(
                "Tensile Stress Maximum,Tensile Strain at Break,Tensile Modulus\n"
                f"MPa,%,MPa\n{10 * factor},4,{1000 * factor}\n"
                "结果表格2\n拉伸应变,拉伸应力\n%,MPa\n"
                + "\n".join(f"{x},{y * factor}" for x, y in
                            ((0, 0), (.1, 1), (.2, 2), (1, 8), (2, 10), (3, 2), (4, 0))) + "\n",
                encoding="utf-8",
            )
        return directory
    path = directory / f"generated_{rule_id}.csv"
    stress = {"compression_curve": "Compressive stress", "flexural_curve": "Flexural stress",
              "tensile_curve": "Tensile stress"}[rule_id]
    strain = "Tensile strain" if rule_id == "tensile_curve" else "Strain"
    rows: list[list[object]] = [[strain, stress] * 3, ["%", "MPa"] * 3,
                               [value for number in (1, 2, 3) for value in [f"Cedar repeat {number}"] * 2]]
    xs = (0., .05, .1, .15, .2, .25, 1., 2., 3., 4.)
    ys = (0., .5, 1., 1.5, 2., 2.5, 8., 10., 2., 0.)
    for x, y in zip(xs, ys, strict=True):
        rows.append([value for factor in (1., 2., 4.) for value in (x, (-1 if rule_id == "compression_curve" else 1) * y * factor)])
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)
    return path
