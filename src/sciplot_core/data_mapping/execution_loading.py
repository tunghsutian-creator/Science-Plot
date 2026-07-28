"""Load and verify a completed mapping execution and all lineage artifacts."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.mapping_contract import (
    LegacyDataMappingConfirmation,
)

from sciplot_core.data_mapping.contracts import (
    DATA_MAPPING_EXECUTION_KIND,
    DATA_MAPPING_EXECUTION_VERSION,
    DATA_MAPPING_PROPOSAL_FILENAME,
    DATA_MAPPING_CONFIRMATION_FILENAME,
    DATA_MAPPING_PREVIEW_FILENAME,
    DATA_MAPPING_EXECUTION_FILENAME,
    DATA_MAPPING_REQUEST_FILENAME,
    DATA_MAPPING_REQUEST_SEED_FILENAME,
    DATA_MAPPING_BASE_REQUEST_FILENAME,
    DATA_MAPPING_BASE_LEDGER_FILENAME,
    data_mapping_proposal_sha256,
    _read_json,
    load_data_mapping_proposal,
    load_data_mapping_confirmation,
    _resolve_source_root,
    _validate_confirmation,
    _validate_confirmation_paths,
)

from sciplot_core.data_mapping.source_mapping import (
    _prepare_mapping_frames,
)

from sciplot_core.data_mapping.output_files import (
    _safe_output_name,
    _mapped_csv_sha256,
)

from sciplot_core.data_mapping.execution_shared import (
    _mapping_step_parameters,
)


def load_data_mapping_execution(
    path_or_dir: str | Path,
    *,
    verify: bool = True,
) -> dict[str, Any]:
    path = Path(path_or_dir).expanduser().resolve()
    if path.is_dir():
        path = path / DATA_MAPPING_EXECUTION_FILENAME
    payload = _read_json(path)
    if payload.get("kind") != DATA_MAPPING_EXECUTION_KIND:
        raise ValueError("Not a SciPlot data mapping execution manifest.")
    execution_version = payload.get("version")
    if (
        type(execution_version) is not int
        or execution_version != DATA_MAPPING_EXECUTION_VERSION
    ):
        raise ValueError(
            f"Unsupported data mapping execution version: {execution_version!r}"
        )
    if payload.get("status") != "passed":
        raise ValueError("Data mapping execution is not in passed state.")
    if not verify:
        return payload
    execution_root = path.parent.resolve()
    proposal_path = Path(str(payload.get("proposal") or "")).expanduser()
    confirmation_path = Path(str(payload.get("confirmation") or "")).expanduser()
    expected_paths = {
        "proposal": execution_root / DATA_MAPPING_PROPOSAL_FILENAME,
        "confirmation": execution_root / DATA_MAPPING_CONFIRMATION_FILENAME,
        "preview": execution_root / DATA_MAPPING_PREVIEW_FILENAME,
        "request_candidate": execution_root / DATA_MAPPING_REQUEST_FILENAME,
        "request_seed": execution_root / DATA_MAPPING_REQUEST_SEED_FILENAME,
        "base_request_snapshot": (execution_root / DATA_MAPPING_BASE_REQUEST_FILENAME),
        "transform_ledger": execution_root / "transform_ledger.json",
    }
    for field, expected_path in expected_paths.items():
        recorded = Path(str(payload.get(field) or "")).expanduser().resolve()
        if recorded != expected_path.resolve():
            raise ValueError(f"Data mapping execution {field} path is not canonical.")
        if not expected_path.is_file():
            raise FileNotFoundError(
                f"Data mapping execution {field} is missing: {expected_path}"
            )
    if Path(str(payload.get("output_root") or "")).expanduser().resolve() != (
        execution_root
    ):
        raise ValueError("Data mapping execution output_root is inconsistent.")
    proposal = load_data_mapping_proposal(proposal_path)
    confirmation = load_data_mapping_confirmation(confirmation_path)
    _validate_confirmation(proposal, confirmation)
    legacy_confirmation = isinstance(confirmation, LegacyDataMappingConfirmation)
    manifest_source_root = (
        Path(str(payload.get("source_root") or "")).expanduser().resolve()
    )
    manifest_request_path = (
        Path(str(payload.get("base_request") or "")).expanduser().resolve()
    )
    if not legacy_confirmation:
        _validate_confirmation_paths(
            confirmation,
            source_root=manifest_source_root,
            request_path=manifest_request_path,
            output_root=execution_root.parent,
        )
        expected_execution_root = (
            Path(confirmation.output_root) / proposal.proposal_id
        ).resolve()
        if execution_root != expected_execution_root:
            raise ValueError(
                "Data mapping execution path does not match the confirmed output root."
            )
    if data_mapping_proposal_sha256(proposal) != payload.get("proposal_sha256"):
        raise ValueError("Data mapping execution proposal hash mismatch.")
    if confirmation.confirmation_id != payload.get("confirmation_id"):
        raise ValueError("Data mapping execution confirmation mismatch.")
    if payload.get("confirmed_by") != confirmation.confirmed_by:
        raise ValueError("Data mapping execution confirmation operator mismatch.")
    if payload.get("confirmed_at") != confirmation.confirmed_at:
        raise ValueError("Data mapping execution confirmation timestamp mismatch.")
    if payload.get("provider") != proposal.provider:
        raise ValueError("Data mapping execution provider mismatch.")
    if payload.get("base_request_sha256") != proposal.base_request_sha256:
        raise ValueError("Data mapping execution request binding mismatch.")
    base_request_snapshot = Path(
        str(payload.get("base_request_snapshot") or "")
    ).expanduser()
    if (
        file_sha256(base_request_snapshot) != proposal.base_request_sha256
        or payload.get("base_request_snapshot_sha256") != proposal.base_request_sha256
    ):
        raise ValueError("Data mapping execution base-request snapshot hash mismatch.")
    base_request_payload = _read_json(base_request_snapshot)
    if payload.get("source_hashes") != proposal.source_hashes:
        raise ValueError("Data mapping execution source binding mismatch.")
    if payload.get("request_patch") != json_safe(proposal.request_patch):
        raise ValueError("Data mapping execution request patch mismatch.")
    source_root = _resolve_source_root(str(payload.get("source_root") or ""))
    sources, frames, units, events, _headers = _prepare_mapping_frames(
        proposal,
        source_root=source_root,
    )
    expected_raw_hashes = {
        source_id: file_sha256(source_path)
        for source_id, source_path in sources.items()
    }
    if (
        payload.get("raw_hashes_before") != expected_raw_hashes
        or payload.get("raw_hashes_after") != expected_raw_hashes
    ):
        raise ValueError("Data mapping execution raw-source proof mismatch.")
    output_records = payload.get("outputs")
    if not isinstance(output_records, list) or len(output_records) != len(
        proposal.sources
    ):
        raise ValueError("Data mapping execution output inventory mismatch.")
    output_by_source: dict[str, dict[str, Any]] = {}
    for output in output_records:
        if not isinstance(output, dict):
            raise ValueError("Data mapping output record must be an object.")
        source_id = str(output.get("source_id") or "")
        if source_id in output_by_source:
            raise ValueError(f"Duplicate mapped output source ID: {source_id!r}")
        output_by_source[source_id] = output
    if set(output_by_source) != {source.source_id for source in proposal.sources}:
        raise ValueError("Data mapping output source IDs do not match proposal.")
    data_dir = execution_root / "data"
    if Path(str(payload.get("data_dir") or "")).expanduser().resolve() != (data_dir):
        raise ValueError("Data mapping execution data_dir is inconsistent.")
    used_names: set[str] = set()
    expected_output_paths: list[Path] = []
    for reference in proposal.sources:
        output = output_by_source[reference.source_id]
        expected_path = data_dir / _safe_output_name(
            reference,
            proposal,
            used=used_names,
        )
        output_path = Path(str(output.get("path") or "")).expanduser()
        if output_path.resolve() != expected_path.resolve():
            raise ValueError(f"Mapped output path changed for {reference.source_id!r}.")
        if not expected_path.is_file():
            raise FileNotFoundError(f"Mapped data output not found: {expected_path}")
        expected_frame = frames[reference.source_id]
        expected_hash = _mapped_csv_sha256(expected_frame)
        if (
            file_sha256(expected_path) != expected_hash
            or output.get("sha256") != expected_hash
        ):
            raise ValueError(f"Mapped data output does not reproduce: {expected_path}")
        expected_record = {
            "source_relative_path": reference.relative_path,
            "source_sha256": reference.sha256,
            "rows": int(expected_frame.shape[0]),
            "columns": [str(column) for column in expected_frame.columns],
            "units": dict(units[reference.source_id]),
            "sample_label": proposal.sample_labels.get(reference.source_id),
            "transformations": events[reference.source_id],
        }
        for field, expected_value in expected_record.items():
            if output.get(field) != expected_value:
                raise ValueError(
                    "Mapped output metadata mismatch for "
                    f"{reference.source_id!r}: {field}."
                )
        expected_output_paths.append(expected_path)
    expected_effective_input = (
        expected_output_paths[0] if len(expected_output_paths) == 1 else data_dir
    )
    if (
        Path(str(payload.get("effective_input") or "")).expanduser().resolve()
        != expected_effective_input.resolve()
    ):
        raise ValueError("Data mapping execution effective_input is inconsistent.")
    seed = Path(str(payload.get("request_seed") or "")).expanduser()
    if not seed.is_file() or file_sha256(seed) != payload.get("request_seed_sha256"):
        raise ValueError("Immutable mapped request seed hash mismatch.")
    seed_payload = _read_json(seed)
    if payload.get("request_candidate_initial_sha256") != payload.get(
        "request_seed_sha256"
    ):
        raise ValueError(
            "Initial mapped request hash no longer matches its immutable seed."
        )
    if seed_payload.get("data_mapping_execution") != str(path):
        raise ValueError("Immutable mapped request seed execution link mismatch.")
    if seed_payload.get("input") != base_request_payload.get("input"):
        raise ValueError("Immutable mapped request seed changed raw input authority.")
    if seed_payload.get("data_mapping_proposal_id") != proposal.proposal_id:
        raise ValueError("Immutable mapped request seed changed proposal identity.")
    if seed_payload.get("output") != str(execution_root / "run"):
        raise ValueError(
            "Immutable mapped request seed changed its isolated output root."
        )
    for key, expected_value in proposal.request_patch.items():
        if seed_payload.get(key) != expected_value:
            raise ValueError(
                f"Immutable mapped request seed changed confirmed field {key!r}."
            )
    ledger = Path(str(payload.get("transform_ledger") or "")).expanduser()
    if not ledger.is_file() or file_sha256(ledger) != payload.get(
        "transform_ledger_sha256"
    ):
        raise ValueError("Active data mapping transform ledger hash mismatch.")
    ledger_payload = _read_json(ledger)
    if (
        ledger_payload.get("steps") != payload.get("transform_steps")
        or seed_payload.get("transform_ledger") != ledger_payload
    ):
        raise ValueError("Active data mapping transform lineage mismatch.")
    transform_steps = payload.get("transform_steps")
    if (
        not isinstance(transform_steps, list)
        or len(transform_steps) != 1
        or not isinstance(transform_steps[0], dict)
    ):
        raise ValueError(
            "Data mapping execution must contain one confirmed mapping step."
        )
    mapping_step = transform_steps[0]
    if (
        mapping_step.get("id") != f"data_mapping_{proposal.proposal_id}"
        or mapping_step.get("operation") != "execute_confirmed_data_mapping_proposal"
        or mapping_step.get("implementation_ref")
        != "sciplot_core.data_mapping.execute_data_mapping_proposal"
        or mapping_step.get("parameters")
        != _mapping_step_parameters(proposal, confirmation)
    ):
        raise ValueError(
            "Active data mapping step no longer matches the confirmed proposal."
        )
    step_inputs = mapping_step.get("input_artifacts")
    if (
        not isinstance(step_inputs, list)
        or len(step_inputs) != 1
        or not isinstance(step_inputs[0], dict)
        or Path(str(step_inputs[0].get("path") or "")).expanduser().resolve()
        != source_root
    ):
        raise ValueError("Active data mapping step changed its confirmed source root.")
    step_outputs = mapping_step.get("output_artifacts")
    if not isinstance(step_outputs, list) or len(step_outputs) != len(
        expected_output_paths
    ):
        raise ValueError("Active data mapping step output inventory mismatch.")
    for artifact, expected_path in zip(
        step_outputs,
        expected_output_paths,
        strict=True,
    ):
        if (
            not isinstance(artifact, dict)
            or Path(str(artifact.get("path") or "")).expanduser().resolve()
            != expected_path
            or artifact.get("sha256") != file_sha256(expected_path)
        ):
            raise ValueError("Active data mapping step output evidence mismatch.")
    if payload.get("raw_inputs_unchanged") is not True:
        raise ValueError(
            "Data mapping execution does not prove raw-input immutability."
        )
    superseded_ledger_value = payload.get("superseded_base_transform_ledger")
    base_transform_ledger = (
        base_request_payload.get("transform_ledger")
        if isinstance(base_request_payload.get("transform_ledger"), dict)
        else None
    )
    if base_transform_ledger is not None:
        superseded_ledger = Path(str(superseded_ledger_value or "")).expanduser()
        expected_superseded = execution_root / DATA_MAPPING_BASE_LEDGER_FILENAME
        if (
            superseded_ledger.resolve() != expected_superseded.resolve()
            or not superseded_ledger.is_file()
            or file_sha256(superseded_ledger)
            != payload.get("superseded_base_transform_ledger_sha256")
            or _read_json(superseded_ledger) != base_transform_ledger
            or seed_payload.get("data_mapping_superseded_transform_ledger")
            != str(expected_superseded)
        ):
            raise ValueError("Superseded base transform ledger hash mismatch.")
    elif (
        superseded_ledger_value is not None
        or payload.get("superseded_base_transform_ledger_sha256") is not None
    ):
        raise ValueError("Data mapping execution invented superseded base lineage.")
    verified = deepcopy(payload)
    verified["confirmation_schema_version"] = 1 if legacy_confirmation else 2
    verified["confirmation_migration_required"] = legacy_confirmation
    verified["handoff_allowed"] = not legacy_confirmation
    if legacy_confirmation:
        verified["ready_to_use"] = False
    return verified
