"""Bind mapping proposals, confirmations, requests, and sources to immutable hashes."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import (
    canonical_json_sha256 as _canonical_sha256,
)
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.mapping_contract import (
    DataMappingConfirmation,
    DataMappingProposal,
    DataSourceReference,
    LegacyDataMappingConfirmation,
)


DATA_MAPPING_PREVIEW_KIND = "sciplot_data_mapping_preview"


DATA_MAPPING_PREVIEW_VERSION = 1


DATA_MAPPING_EXECUTION_KIND = "sciplot_data_mapping_execution"


DATA_MAPPING_EXECUTION_VERSION = 1


DATA_MAPPING_APPLICATION_KIND = "sciplot_data_mapping_application"


DATA_MAPPING_APPLICATION_VERSION = 1


DATA_MAPPING_PROPOSAL_FILENAME = "proposal.json"


DATA_MAPPING_CONFIRMATION_FILENAME = "confirmation.json"


DATA_MAPPING_PREVIEW_FILENAME = "preview.json"


DATA_MAPPING_EXECUTION_FILENAME = "execution.json"


DATA_MAPPING_REQUEST_FILENAME = "plot_request.json"


DATA_MAPPING_REQUEST_SEED_FILENAME = "request_seed.json"


DATA_MAPPING_BASE_REQUEST_FILENAME = "base_request.json"


DATA_MAPPING_BASE_LEDGER_FILENAME = "superseded_base_transform_ledger.json"


_SUPPORTED_TABLE_SUFFIXES = frozenset(
    {".csv", ".tsv", ".txt", ".dat", ".tab", ".xlsx", ".xls"}
)


_MISSING_STRINGS = frozenset({"", "na", "n/a", "nan", "null", "none"})


_NUMERIC_COLUMN_ROLES = frozenset({"x", "y", "z", "value", "x_error", "y_error"})


_PRIMARY_NUMERIC_COLUMN_ROLES = frozenset({"x", "y", "z", "value"})


_DECIMAL_COMMA_NUMBER = re.compile(r"^[+-]?(?:\d+(?:,\d*)?|,\d+)(?:[eE][+-]?\d+)?$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def data_mapping_proposal_sha256(proposal: DataMappingProposal) -> str:
    return _canonical_sha256(proposal.to_dict())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def load_data_mapping_proposal(
    value: DataMappingProposal | str | Path | dict[str, Any],
) -> DataMappingProposal:
    if isinstance(value, DataMappingProposal):
        return value
    if isinstance(value, dict):
        return DataMappingProposal.from_dict(value)
    return DataMappingProposal.from_dict(_read_json(Path(value).expanduser().resolve()))


def load_data_mapping_confirmation(
    value: (
        DataMappingConfirmation
        | LegacyDataMappingConfirmation
        | str
        | Path
        | dict[str, Any]
    ),
) -> DataMappingConfirmation | LegacyDataMappingConfirmation:
    if isinstance(value, (DataMappingConfirmation, LegacyDataMappingConfirmation)):
        return value
    payload = (
        value
        if isinstance(value, dict)
        else _read_json(Path(value).expanduser().resolve())
    )
    if payload.get("version") == 1:
        return LegacyDataMappingConfirmation.from_dict(payload)
    return DataMappingConfirmation.from_dict(payload)


def _resolve_source_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Data mapping source root not found: {root}")
    if not root.is_dir():
        raise ValueError(
            "DataMappingProposal source paths are relative to a source directory."
        )
    return root


def _resolve_request_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Data mapping request not found: {path}")
    return path


def _resolve_source_path(
    root: Path,
    reference: DataSourceReference,
) -> Path:
    candidate = (root / Path(reference.relative_path)).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(
            f"Data source escapes the declared root: {reference.relative_path}"
        )
    if not candidate.is_file():
        raise FileNotFoundError(
            f"Data mapping source not found: {reference.relative_path}"
        )
    if candidate.suffix.casefold() not in _SUPPORTED_TABLE_SUFFIXES:
        raise ValueError(
            f"Unsupported data mapping source format: {candidate.suffix or '<none>'}"
        )
    current_hash = file_sha256(candidate)
    if current_hash != reference.sha256:
        raise ValueError(f"Data mapping source hash changed: {reference.relative_path}")
    return candidate


def verify_data_mapping_sources(
    proposal: DataMappingProposal,
    *,
    source_root: str | Path,
) -> dict[str, Path]:
    root = _resolve_source_root(source_root)
    return {
        reference.source_id: _resolve_source_path(root, reference)
        for reference in proposal.sources
    }


def _verify_request_binding(
    proposal: DataMappingProposal,
    *,
    request_path: str | Path,
) -> Path:
    path = _resolve_request_path(request_path)
    if file_sha256(path) != proposal.base_request_sha256:
        raise ValueError(
            "DataMappingProposal is stale because plot_request.json changed."
        )
    return path


def create_data_mapping_confirmation(
    proposal: DataMappingProposal | str | Path | dict[str, Any],
    *,
    source_root: str | Path,
    request_path: str | Path,
    output_root: str | Path,
    confirmed_by: str,
) -> DataMappingConfirmation:
    resolved = load_data_mapping_proposal(proposal)
    resolved_source_root = _resolve_source_root(source_root)
    resolved_request_path = _verify_request_binding(resolved, request_path=request_path)
    verify_data_mapping_sources(resolved, source_root=resolved_source_root)
    resolved_output_root = Path(output_root).expanduser().resolve()
    return DataMappingConfirmation(
        proposal_id=resolved.proposal_id,
        proposal_sha256=data_mapping_proposal_sha256(resolved),
        base_request_sha256=resolved.base_request_sha256,
        source_hashes=resolved.source_hashes,
        source_root=str(resolved_source_root),
        request_path=str(resolved_request_path),
        output_root=str(resolved_output_root),
        confirmed_by=confirmed_by,
    )


def write_data_mapping_confirmation(
    path: str | Path,
    confirmation: DataMappingConfirmation,
) -> Path:
    destination = Path(path).expanduser().resolve()
    if destination.exists() and destination.is_dir():
        destination = destination / DATA_MAPPING_CONFIRMATION_FILENAME
    elif destination.suffix.casefold() != ".json":
        destination.mkdir(parents=True, exist_ok=True)
        destination = destination / DATA_MAPPING_CONFIRMATION_FILENAME
    _write_json(destination, confirmation.to_dict())
    return destination


def _validate_confirmation(
    proposal: DataMappingProposal,
    confirmation: DataMappingConfirmation | LegacyDataMappingConfirmation,
) -> None:
    if confirmation.proposal_id != proposal.proposal_id:
        raise ValueError("Data mapping confirmation targets another proposal.")
    if confirmation.proposal_sha256 != data_mapping_proposal_sha256(proposal):
        raise ValueError("Data mapping confirmation does not match proposal content.")
    if confirmation.base_request_sha256 != proposal.base_request_sha256:
        raise ValueError("Data mapping confirmation request binding is stale.")
    if confirmation.source_hashes != proposal.source_hashes:
        raise ValueError("Data mapping confirmation source binding is stale.")


def _validate_confirmation_paths(
    confirmation: DataMappingConfirmation,
    *,
    source_root: Path,
    request_path: Path,
    output_root: Path,
) -> None:
    if Path(confirmation.source_root) != source_root.resolve():
        raise ValueError("Data mapping confirmation source-root binding is stale.")
    if Path(confirmation.request_path) != request_path.resolve():
        raise ValueError("Data mapping confirmation request-path binding is stale.")
    if Path(confirmation.output_root) != output_root.resolve():
        raise ValueError("Data mapping confirmation output-root binding is stale.")
