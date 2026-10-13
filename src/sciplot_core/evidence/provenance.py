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

    # These older local evidence schemas bind fixture bytes explicitly, using
    # different field names. A source hash is fixture evidence only when the
    # provenance declares the fixture to be an exact, unmodified source copy.
    if isinstance(payload, dict) and payload.get("version") == 1:
        if payload.get("kind") == "sciplot_digitized_fixture_provenance":
            output = payload.get("output_csv")
            digest = payload.get("output_csv_sha256")
            if (isinstance(output, str) and output.strip() and Path(output).name == output
                    and isinstance(digest, str) and len(digest) == 64
                    and HASH_PATTERN.fullmatch(digest)):
                expected[Path(output).name] = digest.casefold()
        if (payload.get("kind") == "sciplot_user_authorized_real_fixture_provenance"
                and payload.get("source_data_status")
                == "exact_unmodified_user_authorized_instrument_exports"):
            sources = payload.get("source_files")
            if isinstance(sources, list):
                for source in sources:
                    if not isinstance(source, dict):
                        continue
                    name = source.get("source_file")
                    digest = source.get("source_sha256")
                    if (isinstance(name, str) and name.strip() and Path(name).name == name
                            and isinstance(digest, str) and len(digest) == 64
                            and HASH_PATTERN.fullmatch(digest)):
                        expected[Path(name).name] = digest.casefold()

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
