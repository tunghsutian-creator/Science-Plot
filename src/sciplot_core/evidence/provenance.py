"""Resolve expected and registered source hashes."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core._paths import real_world_fixture_root

from sciplot_core.evidence.json_sources import (
    HASH_PATTERN,
)


def _provenance_candidates(
    fixture: Path, metadata: dict[str, Any], repo_root: Path
) -> list[Path]:
    candidates: list[Path] = []
    provenance_value = metadata.get("provenance_path")
    if isinstance(provenance_value, str) and provenance_value.strip():
        candidates.append(
            (real_world_fixture_root(repo_root=repo_root) / provenance_value).resolve()
        )
    base = fixture if fixture.is_dir() else fixture.parent
    candidates.extend(
        [
            base / "source_provenance.json",
            base / "digitization_provenance.json",
        ]
    )
    seen: set[Path] = set()
    return [
        candidate
        for candidate in candidates
        if not (candidate in seen or seen.add(candidate))
    ]


def _expected_fixture_hashes(payload: object) -> dict[str, str]:
    expected: dict[str, str] = {}

    def visit(value: object) -> None:
        if isinstance(value, dict):
            path_value = next(
                (
                    value.get(key)
                    for key in ("fixture_file", "fixture_path", "path")
                    if isinstance(value.get(key), str) and str(value.get(key)).strip()
                ),
                None,
            )
            hash_value = next(
                (
                    value.get(key)
                    for key in ("fixture_sha256", "sha256")
                    if isinstance(value.get(key), str)
                    and HASH_PATTERN.fullmatch(str(value.get(key)))
                ),
                None,
            )
            if path_value and hash_value:
                expected[Path(str(path_value)).name] = str(hash_value).casefold()
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return expected


def _registered_source_hashes(payload: object) -> list[str]:
    registered: list[str] = []

    def visit(value: object, parent_key: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_token = key.casefold()
                if (
                    isinstance(item, str)
                    and HASH_PATTERN.fullmatch(item)
                    and (
                        "source" in key_token
                        or "archive" in key_token
                        or "member" in key_token
                    )
                ):
                    registered.append(item.casefold())
                visit(item, key)
        elif isinstance(value, list):
            for item in value:
                visit(item, parent_key)

    visit(payload)
    return sorted(set(registered))
