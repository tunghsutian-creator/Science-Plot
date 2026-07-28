"""Validate mapped source artifacts and expected output inventories."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256

from sciplot_core.source_coverage.file_snapshots import (
    _stable_file_snapshot,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _required_sha256(value: object, *, label: str) -> str:
    digest = str(value or "").strip().casefold()
    if not _SHA256.fullmatch(digest):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return digest


def _current_source_artifact(
    path_value: object,
    sha256_value: object,
    *,
    label: str,
) -> dict[str, str]:
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError(f"{label} has no source path.")
    path = Path(path_value).expanduser().resolve()
    digest = _required_sha256(sha256_value, label=f"{label} sha256")
    if not path.is_file():
        raise FileNotFoundError(f"{label} is not a current file: {path}")
    if file_sha256(path) != digest:
        raise ValueError(f"{label} changed after rendering: {path}")
    return {"path": str(path), "sha256": digest}


def _source_artifact_from_inventory(
    path_value: object,
    sha256_value: object,
    *,
    label: str,
    artifact_inventory: dict[str, str] | None,
) -> dict[str, str]:
    if artifact_inventory is None:
        return _current_source_artifact(
            path_value,
            sha256_value,
            label=label,
        )
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError(f"{label} has no source path.")
    path = str(Path(path_value).expanduser().resolve())
    digest = _required_sha256(sha256_value, label=f"{label} sha256")
    captured_digest = artifact_inventory.get(path)
    if captured_digest is None:
        raise ValueError(
            f"{label} is outside the captured terminal artifact inventory: {path}"
        )
    if captured_digest != digest:
        raise ValueError(f"{label} changed after rendering: {path}")
    return {"path": path, "sha256": digest}


def _series_source_artifacts(
    value: object,
    *,
    label: str,
    artifact_inventory: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    if not isinstance(value, list | tuple) or not value:
        raise ValueError(f"{label} has no renderer-recorded source artifacts.")
    records: list[dict[str, str]] = []
    for index, raw in enumerate(value, start=1):
        if isinstance(raw, dict):
            path_value = raw.get("path")
            sha256_value = raw.get("sha256")
        elif isinstance(raw, list | tuple) and len(raw) == 2:
            path_value, sha256_value = raw
        else:
            raise ValueError(
                f"{label} source artifact {index} must be a path/hash pair."
            )
        records.append(
            _source_artifact_from_inventory(
                path_value,
                sha256_value,
                label=f"{label} source artifact {index}",
                artifact_inventory=artifact_inventory,
            )
        )
    keys = [(record["path"], record["sha256"]) for record in records]
    if len(keys) != len(set(keys)):
        raise ValueError(f"{label} repeats a renderer-recorded source artifact.")
    return sorted(records, key=lambda record: (record["path"], record["sha256"]))


def _expected_mapping_outputs(
    mapping_application: dict[str, Any],
    *,
    artifact_inventory: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    values = mapping_application.get("mapped_outputs")
    if not isinstance(values, list) or not values:
        raise ValueError("Confirmed data mapping has no mapped output inventory.")
    expected: list[dict[str, str]] = []
    for index, raw in enumerate(values, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Mapped output {index} is not an object.")
        expected.append(
            _source_artifact_from_inventory(
                raw.get("path"),
                raw.get("sha256"),
                label=f"mapped output {index}",
                artifact_inventory=artifact_inventory,
            )
        )
    keys = [(record["path"], record["sha256"]) for record in expected]
    paths = [record["path"] for record in expected]
    if len(keys) != len(set(keys)) or len(paths) != len(set(paths)):
        raise ValueError("Confirmed data mapping repeats a mapped output identity.")
    return sorted(expected, key=lambda record: (record["path"], record["sha256"]))


def _result_path_list(
    result: dict[str, Any],
    *,
    plural: str,
    singular: str,
    label: str,
) -> list[Path]:
    raw_values = result.get(plural)
    if raw_values is None:
        raw_value = result.get(singular)
        raw_values = [raw_value] if raw_value is not None else []
    if (
        not isinstance(raw_values, list)
        or not raw_values
        or any(not isinstance(value, str) or not value.strip() for value in raw_values)
    ):
        raise ValueError(f"A mapped render must identify its exact {label}.")
    paths = [Path(value).expanduser().resolve() for value in raw_values]
    if len(paths) != len(set(paths)):
        raise ValueError(f"Mapped render repeats a {label} path.")
    return paths


def _terminal_file_snapshots(
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    paths = _result_path_list(
        result,
        plural="data_snapshot_sources",
        singular="data_snapshot_source",
        label="plotted data snapshot files",
    )
    snapshots = [
        _stable_file_snapshot(
            path,
            label=f"terminal plotted data snapshot {index}",
        )
        for index, path in enumerate(paths, start=1)
    ]
    return sorted(
        snapshots,
        key=lambda record: (str(record["path"]), record["sha256"]),
    )
