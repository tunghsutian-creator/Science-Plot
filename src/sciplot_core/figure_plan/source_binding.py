"""Compute relocation-stable fingerprints for resolved-plan source inputs."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.foundation.source_tree import source_tree_sha256


def source_trees_match_sha256(
    expected_sha256: str | None,
    *sources: Path | None,
) -> bool:
    """Return whether every current source tree matches one expected digest."""

    return bool(
        expected_sha256
        and sources
        and all(source_tree_sha256(source) == expected_sha256 for source in sources)
    )


__all__ = ["source_tree_sha256", "source_trees_match_sha256"]
