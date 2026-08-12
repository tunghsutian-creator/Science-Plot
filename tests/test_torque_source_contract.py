from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sciplot_core.semantic import prepare_semantic_source
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.torque_event_selection import (
    _auto_torque_event_selection,
)
from sciplot_core.semantic_sources.torque_sources import (
    _read_torque_full_series,
    _read_torque_series,
)


_CURATION_POINTS = (
    (10.0, 2.0),
    (20.0, 18.0),
    (30.0, 12.0),
    (40.0, 7.0),
    (50.0, 3.0),
)


def _confident_detector_points() -> tuple[tuple[float, float], ...]:
    responses = (
        [1.0] * 3
        + [40.0]
        + [10.0 + float(index % 11) for index in range(36)]
        + [1.0] * 8
    )
    return tuple(
        (100.0 + 10.0 * index, response)
        for index, response in enumerate(responses)
    )


def _write_torque_source(
    path: Path,
    points: tuple[tuple[float, float], ...],
    *,
    x_header: str = "Time",
    x_unit: str = "s",
    y_unit: str = "N.m",
) -> None:
    path.write_text(
        f"{x_header},Screw Torque\n"
        f"{x_unit},{y_unit}\n"
        + "".join(f"{time},{torque}\n" for time, torque in points),
        encoding="utf-8",
    )


def test_prepare_without_curation_preserves_full_absolute_torque_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "synthetic_curve.csv"
    source_points = _confident_detector_points()
    _write_torque_source(source, source_points)

    candidate = _auto_torque_event_selection(_read_torque_full_series(source))
    assert candidate["source"] == "auto_detected"
    assert candidate["needs_human_review"] is False

    resolved = _read_torque_series(source)
    assert resolved.points == source_points
    assert (resolved.x_unit, resolved.y_unit) == ("s", "N·m")
    diagnostics = dict(resolved.diagnostics or {})
    assert diagnostics["x_unit_conversion"] == {
        "source_unit": "s",
        "canonical_unit": "s",
        "factor": 1.0,
        "method": "identity",
        "unit_detection": "detected_from_adjacent_unit_row",
    }
    assert diagnostics["y_unit_conversion"] == {
        "source_unit": "N.m",
        "canonical_unit": "N·m",
        "factor": 1.0,
        "method": "identity",
        "unit_detection": "detected_from_adjacent_unit_row",
    }
    assert diagnostics["event_selection"]["source"] == "full_curve"
    assert diagnostics["event_selection"]["start_s"] == source_points[0][0]
    assert diagnostics["event_selection"]["end_s"] == source_points[-1][0]
    assert diagnostics["event_selection"]["time_zero"] == "absolute"
    assert diagnostics["source_point_count"] == len(source_points)
    assert diagnostics["selected_point_count"] == len(source_points)

    prepared = prepare_semantic_source(
        source,
        output_dir=tmp_path / "prepared",
        semantic={"semantic_family": "torque_curve", "rule_id": "torque_curve"},
    )
    parameters = prepared["transform_steps"][0]["parameters"]
    assert parameters["automatic_event_selection_applied"] is False
    assert parameters["event_selection_policy"] == "explicit_curation_or_full_source"
    assert parameters["event_selections"][0]["source"] == "full_curve"
    assert parameters["event_selections"][0]["x_unit_conversion"] == diagnostics[
        "x_unit_conversion"
    ]
    assert parameters["event_selections"][0]["y_unit_conversion"] == diagnostics[
        "y_unit_conversion"
    ]

    table = pd.read_csv(prepared["processed_source"], header=None)
    output_points = tuple(
        (float(time), float(torque))
        for time, torque in table.iloc[3:, :2].itertuples(index=False, name=None)
    )
    assert output_points == source_points


def test_torque_minutes_are_converted_before_second_based_curation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "minutes.csv"
    _write_torque_source(
        source,
        ((0.0, 2.0), (1.0, 18.0), (2.0, 12.0)),
        x_unit="min",
    )

    full = _read_torque_full_series(source)
    assert full.points == ((0.0, 2.0), (60.0, 18.0), (120.0, 12.0))
    assert (full.diagnostics or {})["x_unit_conversion"] == {
        "source_unit": "min",
        "canonical_unit": "s",
        "factor": 60.0,
        "method": "minute_to_second",
        "unit_detection": "detected_from_adjacent_unit_row",
    }

    curated = _read_torque_series(
        source,
        curation={
            "samples": [
                {
                    "source_path": str(source.resolve()),
                    "start_s": 60.0,
                    "end_s": 120.0,
                    "time_zero": "absolute",
                    "source": "explicit_curation",
                }
            ]
        },
    )
    assert curated.points == ((60.0, 18.0), (120.0, 12.0))
    assert (curated.diagnostics or {})["event_selection"][
        "x_unit_conversion"
    ]["factor"] == 60.0


@pytest.mark.parametrize(
    ("x_header", "x_unit", "y_unit", "error"),
    (
        ("Index", "count", "N.m", "Index alone is not time evidence"),
        ("Time", "", "N.m", "Torque time unit is missing"),
        ("Time", "day", "N.m", "Unsupported torque time unit"),
        ("Time", "s", "", "Torque response unit is missing"),
        ("Time", "s", "lbf.ft", "Unsupported torque response unit"),
    ),
)
def test_torque_prepare_rejects_unverified_units_before_processed_write(
    tmp_path: Path,
    x_header: str,
    x_unit: str,
    y_unit: str,
    error: str,
) -> None:
    source = tmp_path / "unverified.csv"
    _write_torque_source(
        source,
        ((0.0, 1.0), (1.0, 2.0)),
        x_header=x_header,
        x_unit=x_unit,
        y_unit=y_unit,
    )
    output_dir = tmp_path / "prepared"

    with pytest.raises(ValueError, match=error):
        prepare_semantic_source(
            source,
            output_dir=output_dir,
            semantic={"semantic_family": "torque_curve", "rule_id": "torque_curve"},
        )

    assert not (output_dir / "processed" / "torque_comparison.csv").exists()


def test_explicit_torque_curation_honors_each_time_zero_mode(tmp_path: Path) -> None:
    source = tmp_path / "synthetic_curve.csv"
    _write_torque_source(source, _CURATION_POINTS)

    def curated(mode: str) -> CurveSeriesPayload:
        return _read_torque_series(
            source,
            curation={
                "samples": [
                    {
                        "source_path": str(source.resolve()),
                        "start_s": 20.0,
                        "end_s": 40.0,
                        "time_zero": mode,
                        "source": "explicit_curation",
                    }
                ]
            },
        )

    assert curated("absolute").points == (
        (20.0, 18.0),
        (30.0, 12.0),
        (40.0, 7.0),
    )
    expected_rebased = ((0.0, 18.0), (10.0, 12.0), (20.0, 7.0))
    assert curated("start_s").points == expected_rebased
    assert curated("selected_first").points == expected_rebased
