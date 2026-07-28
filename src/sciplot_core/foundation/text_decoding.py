"""Deterministic decoding primitives for text-based instrument exports."""

from __future__ import annotations

from pathlib import Path


# High-byte density at or above this fraction is treated as a multibyte CJK
# encoding rather than Western single-byte text with occasional symbols.
_CJK_DENSITY_THRESHOLD = 0.12

# NUL-byte density at or above this fraction indicates BOM-less UTF-16.
_UTF16_NUL_THRESHOLD = 0.25


def smart_decode(payload: bytes) -> tuple[str, str]:
    """Decode bytes deterministically and return text plus an encoding label."""

    if not payload:
        return "", "utf-8"

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

    nul_count = payload.count(0)
    if nul_count and nul_count / len(payload) >= _UTF16_NUL_THRESHOLD:
        even_nul_count = sum(
            1 for index in range(0, len(payload), 2) if payload[index] == 0
        )
        odd_nul_count = sum(
            1 for index in range(1, len(payload), 2) if payload[index] == 0
        )
        encoding = "utf-16-be" if even_nul_count >= odd_nul_count else "utf-16-le"
        try:
            return payload.decode(encoding), encoding
        except UnicodeError:
            pass

    try:
        return payload.decode("utf-8"), "utf-8"
    except UnicodeError:
        pass

    high_byte_density = sum(byte >= 0x80 for byte in payload) / len(payload)
    candidates = (
        ("gb18030", "big5", "cp1252", "latin-1")
        if high_byte_density >= _CJK_DENSITY_THRESHOLD
        else ("cp1252", "latin-1")
    )
    for encoding in candidates:
        try:
            return payload.decode(encoding), encoding
        except UnicodeError:
            continue
    return payload.decode("latin-1"), "latin-1"


def decode_text_file(path: str | Path) -> str:
    """Read and deterministically decode one text file."""

    return smart_decode(Path(path).read_bytes())[0]


def is_clean_utf8(payload: bytes) -> bool:
    """Return whether bytes are strict UTF-8 without a byte-order mark."""

    if payload[:3] == b"\xef\xbb\xbf":
        return False
    try:
        payload.decode("utf-8")
    except UnicodeError:
        return False
    return True


__all__ = ["decode_text_file", "is_clean_utf8", "smart_decode"]
