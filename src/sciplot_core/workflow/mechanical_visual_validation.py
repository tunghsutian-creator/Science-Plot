"""Validate the one public palette and closed encodings for mechanical tasks."""

from __future__ import annotations

from typing import Any, NoReturn

from sciplot_core.policy import resolve_palette_authority
from sciplot_core.studio_core.series_encoding_contract import (
    series_encoding_from_spec,
    validate_series_encoding_contract,
)


_TERMINAL_MISMATCH = "mechanical_terminal_evidence_mismatch"


def validate_mechanical_visual_encoding(
    spec: dict[str, Any],
    *,
    series: list[dict[str, Any]],
) -> None:
    """Bind every closed series encoding to its ordered public-palette color."""

    source_request = _object(spec.get("source_request"), label="source_request")
    render_options = _object(spec.get("render_options"), label="render_options")
    expected_palette = resolve_palette_authority(
        source_request,
        template_id=str(spec.get("template") or ""),
        resolved_render_options=render_options,
    ).to_payload()
    if spec.get("palette_resolution") != expected_palette:
        _fail("public palette resolution")
    try:
        validate_series_encoding_contract(spec)
    except ValueError as exc:
        raise ValueError(
            f"{_TERMINAL_MISMATCH}: terminal series encoding contract is invalid."
        ) from exc
    palette_colors = expected_palette.get("colors")
    if not isinstance(palette_colors, list) or not palette_colors:
        _fail("palette color inventory")
    style = _object(spec.get("style"), label="style")
    for index, item in enumerate(series):
        try:
            encoding = series_encoding_from_spec(item, style=style)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{_TERMINAL_MISMATCH}: terminal series encoding is invalid."
            ) from exc
        if encoding != item.get("encoding"):
            _fail("canonical closed series encoding")
        expected_color = _expected_series_color(
            item,
            index=index,
            palette_colors=palette_colors,
            source_request=source_request,
        )
        line = _object(encoding.get("line"), label="encoding.line")
        marker = _object(encoding.get("marker"), label="encoding.marker")
        expected_fill = (
            "white"
            if item.get("presentation_kind") != "categorical_replicates"
            and str(render_options.get("marker_fill_mode") or "filled").casefold()
            == "open"
            else expected_color
        )
        if (
            item.get("name") != f"series_{index + 1}"
            or encoding.get("audit_policy")
            != "request_bound_fields_must_match_exact_current_vsz"
            or str(line.get("color") or "") != expected_color
            or str(marker.get("fill_color") or "") != expected_fill
            or str(marker.get("line_color") or "") != expected_color
        ):
            _fail("series colors derived in exact palette order")
        if not _flat_encoding_matches(item, line=line, marker=marker):
            _fail("flat and closed series encodings")


def _expected_series_color(
    item: dict[str, Any],
    *,
    index: int,
    palette_colors: list[Any],
    source_request: dict[str, Any],
) -> str:
    options = _object(source_request.get("render_options"), label="render_options")
    styles = options.get("series_styles")
    if isinstance(styles, list):
        for style in styles:
            if not isinstance(style, dict):
                continue
            label = style.get("label") or style.get("sample") or style.get("name")
            if label == item.get("label") and style.get("color"):
                return str(style["color"])
    return str(palette_colors[index % len(palette_colors)])


def _flat_encoding_matches(
    item: dict[str, Any],
    *,
    line: dict[str, Any],
    marker: dict[str, Any],
) -> bool:
    return (
        item.get("color") == line.get("color")
        and item.get("line_style") == line.get("style")
        and item.get("line_width_pt") == line.get("width_pt")
        and item.get("plot_line_hide") is (line.get("visible") is not True)
        and item.get("marker") == marker.get("shape")
        and item.get("marker_size_pt") == marker.get("size_pt")
        and item.get("marker_thin_factor") == marker.get("thin_factor")
        and item.get("marker_fill_color") == marker.get("fill_color")
        and item.get("marker_alpha") == marker.get("fill_alpha")
        and item.get("marker_line_hide") is (marker.get("line_visible") is not True)
        and item.get("marker_line_color") == marker.get("line_color")
        and item.get("marker_line_width_pt") == marker.get("line_width_pt")
    )


def _object(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(label)
    return value


def _fail(field: str) -> NoReturn:
    raise ValueError(
        f"{_TERMINAL_MISMATCH}: terminal {field} conflicts with the selected "
        "mechanical FigurePlan."
    )


__all__ = ["validate_mechanical_visual_encoding"]
