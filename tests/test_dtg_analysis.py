from __future__ import annotations

import csv
from pathlib import Path

from sciplot_core._paths import resolve_fixture_path
from sciplot_core.materials_rules import (
    compute_analysis_metrics,
    get_rule,
    semantic_payload_from_rule,
)


def test_dtg_peak_temperature_tracks_the_fixture_maximum_response(
    tmp_path: Path,
) -> None:
    rule = get_rule("dtg_curve")
    source = resolve_fixture_path(str(rule.fixture_path or ""))
    with source.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    points = tuple(
        (float(row[0]), float(row[1]))
        for row in rows[3:]
        if row[0] and row[1]
    )
    assert points
    assert any(response < 0.0 for _temperature, response in points)
    assert any(response > 0.0 for _temperature, response in points)
    expected_temperature, _maximum_response = max(
        points,
        key=lambda point: point[1],
    )

    metrics = compute_analysis_metrics(
        source_path=source,
        processed_source=None,
        semantic=semantic_payload_from_rule(rule, confidence=1.0),
        output_dir=tmp_path,
    )

    assert metrics == [
        {
            "metric": rule.analysis[0].metric,
            "value": expected_temperature,
            "unit": "°C",
            "status": "ok",
            "reason": (
                "Temperature of the maximum finite -d(mass)/dT response in "
                "the canonical paired trace."
            ),
        }
    ]


def test_xrd_peak_positions_track_each_fixture_maximum_intensity(
    tmp_path: Path,
) -> None:
    rule = get_rule("xrd_pattern")
    source = resolve_fixture_path(str(rule.fixture_path or ""))
    with source.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    samples = rows[2]
    expected = []
    for x_index in range(0, len(rows[0]), 2):
        points = tuple(
            (float(row[x_index]), float(row[x_index + 1]))
            for row in rows[3:]
            if row[x_index] and row[x_index + 1]
        )
        assert points
        expected.append(
            (
                samples[x_index],
                max(points, key=lambda point: point[1])[0],
            )
        )

    semantic = semantic_payload_from_rule(rule, confidence=1.0)
    metrics = compute_analysis_metrics(
        source_path=source,
        processed_source=None,
        semantic=semantic,
        output_dir=tmp_path,
    )

    suffixes = (
        [f"[{sample}]" for sample, _value in expected]
        if len(expected) > 1
        else [""]
    )
    assert metrics == [
        {
            "metric": f"{rule.analysis[0].metric}{suffix}",
            "value": value,
            "unit": semantic["axis_plan"]["x"]["canonical_unit"],
            "status": "ok",
            "reason": (
                "Diffraction angle of the maximum finite observed intensity; "
                "this descriptive position does not assign a crystalline phase."
            ),
        }
        for suffix, (_sample, value) in zip(suffixes, expected, strict=True)
    ]
