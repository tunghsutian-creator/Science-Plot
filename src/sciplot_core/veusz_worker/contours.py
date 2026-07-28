"""Build and compare scalar contour inventory records."""

from __future__ import annotations

from typing import Any


def _expected_contour_records(
    *,
    data_name: str,
    visual: dict[str, Any],
) -> list[tuple[Any, ...]]:
    expected: list[tuple[Any, ...]] = []

    def append(
        *,
        name: str,
        levels: object,
        color: object,
        line_style: object,
        line_width: object,
        show_labels: bool,
    ) -> None:
        numeric_levels = list(levels) if isinstance(levels, list | tuple) else []
        if not numeric_levels:
            return
        line = str(
            (
                str(line_style),
                f"{float(line_width):g}pt",
                str(color),
                False,
            )
        )
        expected.append(
            (
                name,
                data_name,
                "manual",
                tuple(float(value) for value in numeric_levels),
                len(numeric_levels),
                (line,),
                False,
                True,
                True,
                not show_labels,
                False,
            )
        )

    if visual["show_contours"] is True:
        append(
            name="field_contours",
            levels=visual["contour_levels"],
            color=visual["contour_color"],
            line_style=visual["contour_line_style"],
            line_width=visual["contour_line_width_pt"],
            show_labels=bool(visual["contour_labels"]),
        )
    append(
        name="field_highlight_contours",
        levels=visual["highlight_contour_levels"],
        color=visual["highlight_contour_color"],
        line_style=visual["highlight_contour_line_style"],
        line_width=visual["highlight_contour_line_width_pt"],
        show_labels=False,
    )
    return expected


def _actual_contour_record(record: dict[str, Any]) -> tuple[Any, ...]:
    bindings = record["bindings"]
    return (
        str(record["name"]),
        str(bindings["data"]),
        str(bindings["scaling"]),
        tuple(float(value) for value in bindings["manualLevels"]),
        int(bindings["numLevels"]),
        tuple(str(value) for value in bindings["Lines/lines"]),
        bool(bindings["Lines/hide"]),
        bool(bindings["Fills/hide"]),
        bool(bindings["SubLines/hide"]),
        bool(bindings["ContourLabels/hide"]),
        bool(bindings["keyLevels"]),
    )
