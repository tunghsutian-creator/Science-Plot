"""Recognize the filesystem identity of tensile-export source directories."""

from __future__ import annotations

from pathlib import Path


TENSILE_EXPORT_DIR_SUFFIX = ".is_tens_exports"


def is_tensile_export_dir(path: Path) -> bool:
    return path.is_dir() and path.name.casefold().endswith(TENSILE_EXPORT_DIR_SUFFIX)


def has_tensile_export_parent(path: Path) -> bool:
    return any(
        parent.name.casefold().endswith(TENSILE_EXPORT_DIR_SUFFIX)
        for parent in path.parents
    )


def tensile_export_sample_name(path: Path) -> str:
    """Return the sample name encoded by a tensile-export directory."""

    if not is_tensile_export_dir(path):
        raise ValueError(f"Not a tensile export directory: {path}")
    return path.name[: -len(TENSILE_EXPORT_DIR_SUFFIX)].strip()


def tensile_export_csv_files(path: Path) -> list[Path]:
    """Return tensile CSV members with case-insensitive suffix handling."""

    if not is_tensile_export_dir(path):
        return []
    return sorted(
        (
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file() and candidate.suffix.casefold() == ".csv"
        ),
        key=lambda candidate: candidate.as_posix().casefold(),
    )
