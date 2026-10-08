"""Apply key placement and one complete axis contract to Veusz."""

from __future__ import annotations

from typing import Any
from sciplot_core.studio_render.categorical_values import (
    _veusz_axis_label,
)

from sciplot_core.studio_core.veusz_units import (
    _pt,
)


def _category_label_widths_mm(labels: list[str], *, family: str, size_pt: float) -> list[float]:
    """Measure literal category names with the native renderer's current font."""
    from PyQt6.QtGui import QFont, QFontMetricsF, QImage

    device = QImage(1, 1, QImage.Format.Format_ARGB32)
    device.setDotsPerMeterX(round(150 / 0.0254))
    device.setDotsPerMeterY(round(150 / 0.0254))
    font = QFont(family)
    font.setPointSizeF(size_pt)
    metrics = QFontMetricsF(font, device)
    return [metrics.horizontalAdvance(label) * 25.4 / device.logicalDpiX() for label in labels]


def category_label_lines(axis_spec: dict[str, Any], style: dict[str, Any],
                         plot_width_mm: float) -> list[list[str]]:
    """Wrap only colliding small category sets, at an existing literal space."""
    labels = [str(label) for label in axis_spec.get("category_labels") or []]
    lines = [[label] for label in labels]
    if len(labels) > 4 or len(labels) < 2:
        return lines  # Larger sets retain their established 45-degree policy.
    positions = axis_spec.get("category_positions") or []
    low, high = axis_spec.get("min"), axis_spec.get("max")
    if (len(positions) != len(labels)
            or low is None or high is None or low == high):
        return lines

    def measure(values: list[str]) -> list[float]:
        return _category_label_widths_mm(values, family=str(style["font_family"]),
                                         size_pt=float(axis_spec["tick_label_size_pt"]))

    widths = measure(labels)
    ordered = sorted(range(len(labels)), key=lambda index: positions[index])
    gaps = [abs(positions[right] - positions[left]) * plot_width_mm / abs(high - low)
            for left, right in zip(ordered, ordered[1:], strict=False)]
    if not any((widths[left] + widths[right]) / 2 > gap
               for left, right, gap in zip(ordered, ordered[1:], gaps, strict=False)):
        return lines
    for ordinal, index in enumerate(ordered):
        available = min(gaps[max(0, ordinal - 1):min(len(gaps), ordinal + 1)])
        if widths[index] <= available:
            continue
        label = labels[index]
        candidates = [(label[:offset], label[offset + 1:]) for offset, char in enumerate(label)
                      if char == " " and label[:offset].strip() and label[offset + 1:].strip()]
        fitted = [(max(measure(list(pair))), pair) for pair in candidates]
        fitted = [entry for entry in fitted if entry[0] <= available]
        if not fitted:
            raise ValueError(f"Category label cannot fit the fixed frame in two lines without changing its name: {label!r}.")
        lines[index] = list(min(fitted, key=lambda entry: entry[0])[1])
    return lines


def validate_category_display(document: Any, display: list[str], axis_label: str,
                              size_mm: list[float]) -> None:
    """Reject dropped or clipped wrapped text using the existing native renderer."""
    from collections import Counter
    from veusz import document as native_document, utils

    expected = Counter([*display, *([_veusz_axis_label(axis_label)] if axis_label else [])])
    original, observed = utils.Renderer, []

    def factory(*args: Any, **kwargs: Any) -> Any:
        renderer = original(*args, **kwargs)
        render = renderer.render
        widget = getattr(args[0], "widget", None)

        def measured() -> Any:
            result = render()
            if getattr(widget, "path", "") == "/page1/graph1/x":
                observed.append((str(args[4]), [float(value) * 25.4 / 150 for value in renderer.getBounds()]))
            return result

        renderer.render = measured
        return renderer

    try:
        utils.Renderer = factory
        helper = native_document.PaintHelper(document, document.pageSize(0, dpi=(150, 150), integer=False), dpi=(150, 150))
        document.paintTo(helper, 0)
    finally:
        utils.Renderer = original
    if Counter(text for text, _bounds in observed) != expected:
        raise ValueError("Category label layout suppressed text; the complete original category set must remain visible.")
    if any(left < -.30 or top < -.30 or right > size_mm[0] + .30 or bottom > size_mm[1] + .30
           for _text, (left, top, right, bottom) in observed):
        raise ValueError("Category label layout exceeds the fixed page; no clipped category figure can be delivered.")


def _apply_key_position(
    interface: Any,
    mode: str,
    *,
    horz_position: str | None = None,
    vert_position: str | None = None,
    horz_manual: float | None = None,
    vert_manual: float | None = None,
) -> None:
    normalized = str(mode or "inside_best").strip().casefold()
    if normalized == "manual" or horz_position is not None or vert_position is not None:
        horz = str(horz_position or "manual")
        vert = str(vert_position or "manual")
        interface.Set("horzPosn", horz)
        interface.Set("vertPosn", vert)
        if horz == "manual":
            interface.Set(
                "horzManual", float(horz_manual if horz_manual is not None else 0.5)
            )
        if vert == "manual":
            interface.Set(
                "vertManual", float(vert_manual if vert_manual is not None else 0.5)
            )
        return
    if normalized in {"upper_right", "top_right"}:
        interface.Set("horzPosn", "right")
        interface.Set("vertPosn", "top")
        return
    if normalized in {"upper_left", "top_left"}:
        interface.Set("horzPosn", "left")
        interface.Set("vertPosn", "top")
        return
    if normalized in {"lower_left", "bottom_left"}:
        interface.Set("horzPosn", "left")
        interface.Set("vertPosn", "bottom")
        return
    interface.Set("horzPosn", "right")
    interface.Set("vertPosn", "bottom")


def _add_veusz_axis(
    interface: Any, axis: str, axis_spec: dict[str, Any], style: dict[str, Any]
) -> None:
    interface.Add("axis", name=axis, autoadd=False)
    interface.To(axis)
    interface.Set("label", _veusz_axis_label(axis_spec["label"]))
    if axis == "y":
        interface.Set("direction", "vertical")
    if axis_spec.get("mode") == "labels":
        interface.Set("mode", "labels")
    interface.Set("autoMirror", False)
    interface.Set("outerticks", True)
    foreground_color = str(axis_spec["foreground_color"])
    interface.Set("Line/color", foreground_color)
    interface.Set("Line/width", _pt(float(axis_spec["line_width_pt"])))
    interface.Set("Line/hide", False)
    interface.Set("Line/transparency", 0)
    interface.Set(
        "MajorTicks/width",
        _pt(float(axis_spec["major_tick_width_pt"])),
    )
    interface.Set(
        "MajorTicks/length",
        _pt(float(axis_spec["major_tick_length_pt"])),
    )
    interface.Set("MajorTicks/transparency", 0)
    interface.Set(
        "MinorTicks/width",
        _pt(float(axis_spec["minor_tick_width_pt"])),
    )
    interface.Set(
        "MinorTicks/length",
        _pt(float(axis_spec["minor_tick_length_pt"])),
    )
    interface.Set("MinorTicks/transparency", 0)
    interface.Set("MinorTicks/number", int(axis_spec.get("minor_tick_count") or 20))
    minor_ticks = (
        axis_spec.get("minor_ticks")
        if isinstance(axis_spec.get("minor_ticks"), list)
        else []
    )
    if minor_ticks:
        interface.Set("MinorTicks/hide", False)
        interface.Set("MinorTicks/manualTicks", [float(value) for value in minor_ticks])
    interface.Set("Label/size", _pt(float(axis_spec["label_size_pt"])))
    interface.Set("Label/color", foreground_color)
    interface.Set("Label/hide", False)
    interface.Set("Label/offset", _pt(float(style["axes_labelpad_pt"])))
    interface.Set(
        "TickLabels/size",
        _pt(float(axis_spec["tick_label_size_pt"])),
    )
    interface.Set("TickLabels/color", foreground_color)
    interface.Set("TickLabels/format", str(axis_spec.get("tick_format") or "Auto"))
    if (
        axis == "x"
        and axis_spec.get("mode") == "labels"
        and len(axis_spec.get("category_labels") or []) > 4
    ):
        interface.Set("TickLabels/rotate", "45")
    tick_offset = (
        style["xtick_major_pad_pt"] if axis == "x" else style["ytick_major_pad_pt"]
    )
    interface.Set("TickLabels/offset", _pt(float(tick_offset)))
    if axis == "y" and axis_spec.get("show_ticks") is False:
        interface.Set("MajorTicks/hide", True)
        interface.Set("MinorTicks/hide", True)
        interface.Set("TickLabels/hide", True)
    if axis_spec.get("min") is not None:
        interface.Set("min", float(axis_spec["min"]))
    if axis_spec.get("max") is not None:
        interface.Set("max", float(axis_spec["max"]))
    ticks = axis_spec.get("ticks") if isinstance(axis_spec.get("ticks"), list) else []
    if 1 < len(ticks) <= 12:
        interface.Set("MajorTicks/manualTicks", [float(value) for value in ticks])
    if axis_spec.get("scale") == "log":
        interface.Set("log", True)
    interface.To("..")
