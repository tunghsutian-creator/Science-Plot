"""Generate explicit synthetic showcase CSVs; never draw or alter a figure."""

import csv
import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REQUESTS = ROOT / "requests"
DATA.mkdir(exist_ok=True)
REQUESTS.mkdir(exist_ok=True)


def write_csv(name, rows):
    with (DATA / name).open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)


def write_options(name, options):
    (REQUESTS / name).write_text(
        json.dumps(options, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


rng = random.Random(1729)
means = [32, 47, 64, 79, 96]
sigmas = [4, 6, 7, 8, 7.5]
groups = [
    [round(rng.gauss(mean, sigma), 3) for _ in range(10)]
    for mean, sigma in zip(means, sigmas, strict=True)
]
write_csv(
    "synthetic-replicate-distributions.csv",
    [
        ["Tensile strength"] * 5,
        ["MPa"] * 5,
        list("ABCDE"),
        *zip(*groups, strict=True),
    ],
)
write_options(
    "replicate-distributions.json",
    {
        "size": "60x55",
        "x_label_override": "Synthetic formulations",
        "y_label_override": "Tensile strength (MPa)",
        "summary_statistic": "median_iqr",
        "raw_point_jitter_fraction": 0.24,
        "y_min": 10,
        "y_max": 120,
        "y_ticks": [20, 40, 60, 80, 100, 120],
    },
)

# Redesigned synthetic two-component example: the previous minor components
# are combined into the modifier fraction; these are not measured formulations.
compositions = [(82, 18), (69, 31), (62, 38), (56, 44), (42, 58)]
write_csv(
    "synthetic-composition-bars.csv",
    [
        ["Sample", "Component", "Mass fraction (%)"],
        *[
            [letter, component, value]
            for letter, values in zip("ABCDE", compositions, strict=True)
            for component, value in zip(
                ["Pol.", "Mod."], values, strict=True
            )
        ],
    ],
)
write_options(
    "composition-bars.json",
    {
        "size": "60x55",
        "x_label_override": "Synthetic formulations",
        "y_label_override": "Mass fraction (%)",
        "y_min": -2,
        "y_max": 135,
        "y_ticks": [0, 20, 40, 60, 80, 100],
    },
)

write_csv(
    "synthetic-response-heatmap.csv",
    [
        ["time_min", "temperature_C", "conversion_pct"],
        *[
            [
                time,
                temperature,
                round(
                    100
                    * (
                        1 - math.exp(-time * 0.015 * math.exp((temperature - 150) / 23))
                    ),
                    5,
                ),
            ]
            for temperature in range(120, 201, 2)
            for time in range(61)
        ],
    ],
)
write_options(
    "response-heatmap.json",
    {
        "size": "60x55",
        "data_variables": {
            "x": "time_min",
            "y": "temperature_C",
            "z": "conversion_pct",
        },
        "x_label_override": "Time (min)",
        "y_label_override": "Temperature (°C)",
        "y_min": 118,
        "y_max": 245,
        "y_ticks": [120, 140, 160, 180, 200],
        "z_label_override": "Synthetic conversion (%)",
        "z_min": 0,
        "z_max": 100,
        "z_ticks": [0, 25, 50, 75, 100],
        "z_tick_format": "%.0f",
        "show_colorbar": True,
        "colorbar_direction": "horizontal",
        "colorbar_width_mm": 35,
        "colorbar_height_mm": 2.8,
    },
)
