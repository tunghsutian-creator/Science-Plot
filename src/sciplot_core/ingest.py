"""Encoding-robust ingestion seam for the public SciPlot wrapper.

The vendored renderer tries a fixed list of text encodings in order, with the
greedy ``gb18030`` codec ahead of ``latin-1``. Because ``gb18030`` decodes
almost any byte sequence without error, Western instrument exports that contain
symbols like ``°C``, ``µm``, ``±`` or ``Å`` are silently mis-decoded into CJK
characters, which then appear as garbled axis labels in the rendered figure.

This module owns a single deterministic decoder used by the public layer. It
resolves the unambiguous cases first (UTF-8, BOM-marked and BOM-less UTF-16),
then disambiguates the genuinely ambiguous high-byte cases with a byte-density
heuristic: sparse high bytes look like Western single-byte text (cp1252 /
latin-1), dense high bytes look like a multibyte CJK encoding (gb18030 / big5).

Statistical detectors such as ``charset-normalizer`` are unreliable on the short
tables typical of materials data (they mis-detect a two-row ``°C`` file as Big5),
so detection here is rule-based and deterministic instead.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Delimited text formats the vendored loader reads as plain text. Binary
# spreadsheet formats (.xls/.xlsx) carry their own encoding and are left alone.
TEXT_TABLE_SUFFIXES = frozenset({".csv", ".tsv", ".txt", ".dat", ".tab"})

# High-byte density at or above this fraction is treated as a multibyte CJK
# encoding rather than Western single-byte text with occasional symbols.
_CJK_DENSITY_THRESHOLD = 0.12

# NUL-byte density at or above this fraction indicates BOM-less UTF-16.
_UTF16_NUL_THRESHOLD = 0.25


def smart_decode(payload: bytes) -> tuple[str, str]:
    """Decode ``payload`` into text, returning ``(text, encoding_label)``.

    Deterministic and total: always returns a string (latin-1 is the final
    fallback because it maps every byte). Never raises on real-world input.
    """
    if not payload:
        return "", "utf-8"

    # Byte-order marks are unambiguous. Fall through if the marked body is
    # nonetheless undecodable, so the function stays total on degenerate input.
    bom_attempts = (
        (b"\xef\xbb\xbf", "utf-8", "utf-8-sig"),
        (b"\xff\xfe", "utf-16-le", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be", "utf-16-be"),
    )
    for marker, codec, label in bom_attempts:
        if payload[: len(marker)] == marker:
            try:
                return payload[len(marker) :].decode(codec), label
            except UnicodeError:
                break

    # BOM-less UTF-16: a large fraction of NUL bytes concentrated on one parity.
    nul = payload.count(0)
    if nul and nul / len(payload) >= _UTF16_NUL_THRESHOLD:
        even_nul = sum(1 for i in range(0, len(payload), 2) if payload[i] == 0)
        odd_nul = sum(1 for i in range(1, len(payload), 2) if payload[i] == 0)
        enc = "utf-16-be" if even_nul >= odd_nul else "utf-16-le"
        try:
            return payload.decode(enc), enc
        except UnicodeError:
            pass

    # UTF-8 has enough structure that a successful strict decode is trustworthy.
    try:
        return payload.decode("utf-8"), "utf-8"
    except UnicodeError:
        pass

    # Ambiguous high bytes: sparse -> Western single-byte, dense -> CJK multibyte.
    density = sum(1 for byte in payload if byte >= 0x80) / len(payload)
    if density >= _CJK_DENSITY_THRESHOLD:
        candidates = ("gb18030", "big5", "cp1252", "latin-1")
    else:
        candidates = ("cp1252", "latin-1")
    for enc in candidates:
        try:
            return payload.decode(enc), enc
        except UnicodeError:
            continue
    return payload.decode("latin-1"), "latin-1"


def decode_text_file(path: str | Path) -> str:
    """Read a text file and decode it with :func:`smart_decode`."""
    return smart_decode(Path(path).read_bytes())[0]


def _is_clean_utf8(payload: bytes) -> bool:
    if payload[:3] == b"\xef\xbb\xbf":
        return False  # UTF-8 BOM: re-emit without the BOM for the loader.
    try:
        payload.decode("utf-8")
    except UnicodeError:
        return False
    return True


@contextmanager
def normalized_source(input_path: str | Path) -> Iterator[Path]:
    """Yield a path safe to hand to the vendored loader.

    For a delimited text table whose bytes are not already clean UTF-8, the
    content is transcoded to UTF-8 in a temporary directory (preserving the
    original filename so downstream output names are unchanged) and that path is
    yielded. In every other case the original path is yielded untouched, so the
    common UTF-8/ASCII path has zero overhead and unchanged behavior.
    """
    path = Path(input_path)
    if path.suffix.lower() not in TEXT_TABLE_SUFFIXES or not path.is_file():
        yield path
        return
    payload = path.read_bytes()
    if _is_clean_utf8(payload):
        yield path
        return
    text, _encoding = smart_decode(payload)
    with tempfile.TemporaryDirectory(prefix="sciplot_ingest_") as tmp:
        target = Path(tmp) / path.name
        target.write_bytes(text.encode("utf-8"))
        yield target


__all__ = ["TEXT_TABLE_SUFFIXES", "decode_text_file", "normalized_source", "smart_decode"]
