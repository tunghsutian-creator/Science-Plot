from __future__ import annotations

from pathlib import Path

from sciplot_core.foundation.text_decoding import decode_text_file


def decode_text(path: Path) -> str:
    return decode_text_file(path)


class suppress_decode:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, _exc: object, _traceback: object) -> bool:
        return exc_type in {UnicodeError, OSError, ValueError}


def text_preview(path: Path, *, lines: int = 40) -> str:
    if path.is_dir():
        parts = [path.as_posix()]
        preview_files = [
            child
            for child in sorted(path.rglob("*"))
            if child.is_file() and child.suffix.lower() in {".csv", ".tsv", ".txt"}
        ]
        for child in preview_files[:3]:
            with suppress_decode():
                parts.append("\n".join(decode_text(child).splitlines()[:lines]))
        return "\n".join(parts)
    if not path.is_file():
        return path.as_posix()
    with suppress_decode():
        return "\n".join(decode_text(path).splitlines()[:lines])
    return path.as_posix()


__all__ = ["decode_text", "suppress_decode", "text_preview"]
