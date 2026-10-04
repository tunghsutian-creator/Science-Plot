"""Identify incidental Finder metadata only inside a visible delivery."""

from __future__ import annotations

from pathlib import Path
from stat import S_ISREG
from typing import TypedDict


FINDER_METADATA_NAME = ".DS_Store"


def is_delivery_finder_metadata(path: Path) -> bool:
    """Exclude only a standalone regular Finder file, never linked content."""
    if path.name != FINDER_METADATA_NAME:
        return False
    try:
        status = path.lstat()
    except FileNotFoundError:
        return False
    return S_ISREG(status.st_mode) and status.st_nlink == 1


class DeliveryTopLevelMetadataPayload(TypedDict):
    expected: list[str]
    actual: list[str]
    ignored_finder_metadata: list[str]


class DeliveryMetadataInspection(TypedDict):
    minimal_top_level: bool
    filesystem_metadata_safe: bool
    top_level: DeliveryTopLevelMetadataPayload
    invalid_finder_metadata: list[str]


def inspect_delivery_metadata(
    root: Path, *, expected_top_level: set[str],
) -> DeliveryMetadataInspection:
    """Describe incidental metadata without obscuring the actual directory entries."""
    top_level_paths = list(root.iterdir()) if root.is_dir() else []
    actual_top_level = {path.name for path in top_level_paths}
    ignored_top_level = {
        path.name for path in top_level_paths if is_delivery_finder_metadata(path)
    }
    invalid_metadata = [
        str(path.relative_to(root))
        for path in root.rglob(FINDER_METADATA_NAME)
        if not is_delivery_finder_metadata(path)
    ]
    return {
        "minimal_top_level": actual_top_level - ignored_top_level == expected_top_level,
        "filesystem_metadata_safe": not invalid_metadata,
        "top_level": {
            "expected": sorted(expected_top_level),
            "actual": sorted(actual_top_level),
            "ignored_finder_metadata": sorted(ignored_top_level),
        },
        "invalid_finder_metadata": sorted(invalid_metadata),
    }
