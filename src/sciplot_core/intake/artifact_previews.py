"""Cached image previews for completed figure artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.policy import canonical_figure_stem

from .packaging import _artifact_info


def _preview_path_for_figure(path: Path) -> Path:
    return path.with_name(f"{canonical_figure_stem(path)}_preview.png")


def _preview_is_fresh(
    preview_path: Path, source_path: Path, *, min_width_px: int = 0
) -> bool:
    if not preview_path.exists() or not preview_path.is_file():
        return False
    try:
        if preview_path.stat().st_mtime_ns < source_path.stat().st_mtime_ns:
            return False
        if min_width_px:
            from PIL import Image

            with Image.open(preview_path) as image:
                return int(image.width) >= min_width_px
        return True
    except OSError:
        return False


def _write_image_preview(source_path: Path, preview_path: Path) -> None:
    from PIL import Image

    with Image.open(source_path) as image:
        try:
            image.seek(0)
        except EOFError:
            pass
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").save(preview_path)


def _write_pdf_preview(source_path: Path, preview_path: Path) -> None:
    import fitz

    with fitz.open(source_path) as document:
        if document.page_count < 1:
            raise ValueError("PDF has no pages.")
        page = document.load_page(0)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(str(preview_path))


def _figure_preview_info(figures: list[Path], *, project_slug: str) -> dict[str, Any]:
    existing_images = [
        figure
        for figure in figures
        if figure.exists()
        and figure.is_file()
        and figure.suffix.casefold() in {".png", ".jpg", ".jpeg"}
    ]
    for image_path in existing_images:
        info = _artifact_info(image_path, project_slug=project_slug)
        return {**info, "display_kind": "image", "source_path": str(image_path)}

    source_figures = [
        figure for figure in figures if figure.exists() and figure.is_file()
    ]
    image_sources = [
        figure
        for figure in source_figures
        if figure.suffix.casefold() in {".tif", ".tiff"}
    ]
    pdf_sources = [
        figure for figure in source_figures if figure.suffix.casefold() == ".pdf"
    ]

    for source_path in image_sources:
        preview_path = _preview_path_for_figure(source_path)
        if _preview_is_fresh(preview_path, source_path, min_width_px=600):
            info = _artifact_info(preview_path, project_slug=project_slug)
            return {**info, "display_kind": "image", "source_path": str(source_path)}

    for source_path in image_sources:
        preview_path = _preview_path_for_figure(source_path)
        try:
            _write_image_preview(source_path, preview_path)
        except Exception:
            continue
        info = _artifact_info(preview_path, project_slug=project_slug)
        return {**info, "display_kind": "image", "source_path": str(source_path)}

    for source_path in pdf_sources:
        preview_path = _preview_path_for_figure(source_path)
        if _preview_is_fresh(preview_path, source_path):
            info = _artifact_info(preview_path, project_slug=project_slug)
            return {**info, "display_kind": "image", "source_path": str(source_path)}

    for source_path in pdf_sources:
        preview_path = _preview_path_for_figure(source_path)
        try:
            _write_pdf_preview(source_path, preview_path)
        except Exception:
            continue
        info = _artifact_info(preview_path, project_slug=project_slug)
        return {**info, "display_kind": "image", "source_path": str(source_path)}

    for source_path in pdf_sources:
        info = _artifact_info(source_path, project_slug=project_slug)
        return {**info, "display_kind": "pdf", "source_path": str(source_path)}

    return {
        "exists": False,
        "path": "",
        "name": "",
        "size_bytes": 0,
        "mtime_ns": 0,
        "content_type": "",
        "url": None,
        "display_kind": "none",
        "source_path": "",
    }
