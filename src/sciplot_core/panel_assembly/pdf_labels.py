"""Render and measure outer PDF labels independently of scientific panels."""

from importlib import import_module
from typing import Any

from .errors import AssemblyError


POINTS_PER_MM = 72.0 / 25.4


def _label(page: Any, label: str, position: list[float] | None, cell: list[float], content: list[float]) -> dict[str, Any]:
    pymupdf: Any = import_module("pymupdf")
    from sciplot_core.rendering_contract import contract_value

    if not label:
        return {"visible": False, "text": ""}
    if position is None or not label.isprintable():
        raise AssemblyError("assembly_label_unsupported", "Outer panel labels require printable single-line text.")
    family = contract_value("font.family")
    size = float(contract_value("panel_label.font_size_pt"))
    weight = contract_value("panel_label.weight")
    unicode_label = not label.isascii()
    fontname = "cjk" if unicode_label else "hebo" if weight == "bold" else "helv"
    font = pymupdf.Font(fontname)
    if any(not font.has_glyph(ord(character), fallback=False) for character in label):
        raise AssemblyError("assembly_label_unsupported", "The embedded panel-label font cannot render every selected character.")
    stroke_em = .05 if unicode_label and weight == "bold" else 0.0
    stroke_half_pt = size * stroke_em / 2
    width = font.text_length(label, fontsize=size)
    x, y = (value * POINTS_PER_MM for value in position)
    if width + stroke_half_pt > (cell[0] + cell[2] - position[0]) * POINTS_PER_MM:
        raise AssemblyError("assembly_label_clipping", "Panel label exceeds its reserved physical cell width.")
    # The solver anchor is the vertical center of the six-mm label band.
    baseline = y + (font.ascender + font.descender) * size / 2
    if unicode_label:
        # Subset only the new outer label font. Never subset or rewrite the
        # existing native scientific font resources embedded in the composite.
        with pymupdf.open() as caption:
            label_page = caption.new_page(width=page.rect.width, height=page.rect.height)
            label_page.insert_font(fontname="panelunicode", fontbuffer=font.buffer)
            label_page.insert_text((x, baseline), label, fontname="panelunicode", fontsize=size,
                                   render_mode=2 if stroke_em else 0, border_width=stroke_em,
                                   color=(0, 0, 0), fill=(0, 0, 0))
            caption.subset_fonts()
            page.show_pdf_page(page.rect, caption, 0)
    else:
        page.insert_text((x, baseline), label, fontname=fontname, fontsize=size, color=(0, 0, 0))
    spans = [span for block in page.get_text("dict")["blocks"] if "lines" in block
             for line in block["lines"] for span in line["spans"]
             if span["text"] == label and abs(span["size"] - size) < 1e-4
             and abs(span["origin"][0] - x) < 1e-3 and abs(span["origin"][1] - baseline) < 1e-3]
    if len(spans) != 1:
        raise AssemblyError("assembly_label_qa_failed", "The exported panel label has no unique measured PDF text bounds.")
    bounds = [(float(value) + (-stroke_half_pt if index < 2 else stroke_half_pt)) / POINTS_PER_MM
              for index, value in enumerate(spans[0]["bbox"])]
    band = [cell[0], cell[1], cell[2], min(2 * (position[1] - cell[1]), content[1] - cell[1])]
    if (bounds[0] < band[0] - 1e-4 or bounds[1] < band[1] - 1e-4
            or bounds[2] > band[0] + band[2] + 1e-4 or bounds[3] > band[1] + band[3] + 1e-4):
        raise AssemblyError("assembly_label_clipping", "The measured PDF panel label exceeds its reserved physical band.")
    return {"visible": True, "text": label, "font_size_pt": size, "font_weight": weight,
            "requested_font_family": family, "actual_font": spans[0]["font"],
            "font_policy": ("Embedded Droid Sans Fallback subset (stroke added only for bold)."
                            if unicode_label else "Explicit PDF Base14 Helvetica fallback for outer labels only."),
            "bounds_mm": [bounds[0], bounds[1], bounds[2] - bounds[0], bounds[3] - bounds[1]],
            "allowed_band_mm": band, "anchor_mm": position, "native_text_scaled": False}
