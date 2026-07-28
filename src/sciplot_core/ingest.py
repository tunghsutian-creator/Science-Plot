"""Encoding-robust ingestion seam for source inspection.

The historical table reader tried a fixed list of text encodings in order, with the
greedy ``gb18030`` codec ahead of ``latin-1``. Because ``gb18030`` decodes
almost any byte sequence without error, Western instrument exports that contain
symbols like ``°C``, ``µm``, ``±`` or ``Å`` are silently mis-decoded into CJK
characters, which then appear as garbled axis labels in the rendered figure.

The deterministic byte decoder belongs to the low-level foundation package.
This module owns the ingestion decision: whether a source can be passed
through unchanged or needs a temporary UTF-8 normalization.

Statistical detectors such as ``charset-normalizer`` are unreliable on the short
tables typical of materials data (they mis-detect a two-row ``°C`` file as Big5),
so detection here is rule-based and deterministic instead.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sciplot_core.foundation.text_decoding import (
    decode_text_file,
    is_clean_utf8,
    smart_decode,
)

# Delimited text formats the source reader handles as plain text. Binary
# spreadsheet formats (.xls/.xlsx) carry their own encoding and are left alone.
TEXT_TABLE_SUFFIXES = frozenset({".csv", ".tsv", ".txt", ".dat", ".tab"})


@contextmanager
def normalized_source(input_path: str | Path) -> Iterator[Path]:
    """Yield a path safe to hand to source inspection.

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
    if is_clean_utf8(payload):
        yield path
        return
    text, _encoding = smart_decode(payload)
    with tempfile.TemporaryDirectory(prefix="sciplot_ingest_") as tmp:
        target = Path(tmp) / path.name
        target.write_bytes(text.encode("utf-8"))
        yield target


__all__ = [
    "TEXT_TABLE_SUFFIXES",
    "decode_text_file",
    "normalized_source",
    "smart_decode",
]
