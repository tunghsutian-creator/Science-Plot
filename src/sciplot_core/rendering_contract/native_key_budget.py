"""Pure estimates for a native legend key; the renderer audits measured bounds."""


def native_key_budget(
    *, label_cells: float, font_size_pt: float, key_length_mm: float,
    columns: int, rows: int, frame_visible: bool, margin_size: float,
) -> tuple[float, float, float]:
    point_to_mm = 25.4 / 72.0
    line_height = max(font_size_pt * 1.2 * point_to_mm, 0.1)
    text_width = max(label_cells * font_size_pt * .56 * point_to_mm, 0.2)
    width = (text_width + line_height + key_length_mm) * columns + line_height * (columns - 1)
    height = rows * line_height
    if frame_visible:
        margin = margin_size * line_height
        width += 2.0 * margin
        height += margin
    return width, height, line_height
