"""Native artifact filename/DPI identities outside retained layout algorithms."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.policy.frame_export import canonical_export_format


_EXPORT_SUFFIXES: dict[str, tuple[str, int | None]] = {
    "pdf": (".pdf", None), "svg": (".svg", None),
    "png_300": ("_300dpi.png", 300), "png_600": ("_600dpi.png", 600),
    "tiff_300": ("_300dpi.tiff", 300),
}


def export_suffix(value: str) -> tuple[str, int | None]:
    """One native export filename/DPI contract for every supported format."""
    return _EXPORT_SUFFIXES[canonical_export_format(value)]


def export_format_from_path(value: str | Path) -> str | None:
    """Recognize only the exact existing native export filename forms."""
    name = Path(value).name.casefold()
    return next((fmt for fmt, (suffix, _dpi) in _EXPORT_SUFFIXES.items() if name.endswith(suffix)), None)
