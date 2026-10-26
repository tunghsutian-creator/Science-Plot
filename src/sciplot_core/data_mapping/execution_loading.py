"""Load and verify a completed mapping execution and all lineage artifacts."""

from __future__ import annotations

from sciplot_core.data_mapping.execution_directories import mapping_directory_path

from copy import deepcopy
from pathlib import Path
from typing import Any
from sciplot_core.data_mapping.execution_inputs import (
    mapping_file_sha256 as file_sha256, mapping_file_path, mapping_file_bytes, mapping_literal,
    mapping_input_reads,
    mapping_execution_path,
    mark_mapping_metadata,
    mapping_execution_header, require_mapping_original_source,
)
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.mapping_contract import (
    LegacyDataMappingConfirmation,
)

from sciplot_core.data_mapping.contracts import (
    DATA_MAPPING_EXECUTION_KIND,
    DATA_MAPPING_PROPOSAL_FILENAME,
    DATA_MAPPING_CONFIRMATION_FILENAME,
    DATA_MAPPING_PREVIEW_FILENAME,
    DATA_MAPPING_REQUEST_FILENAME,
    DATA_MAPPING_REQUEST_SEED_FILENAME,
    DATA_MAPPING_BASE_REQUEST_FILENAME,
    DATA_MAPPING_BASE_LEDGER_FILENAME,
    data_mapping_proposal_sha256,
    _read_json,
    load_data_mapping_proposal,
    load_data_mapping_confirmation,
    _validate_confirmation,
    _validate_confirmation_paths,
    verify_data_mapping_sources,
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
from sciplot_core.data_mapping.raw_tables import (
    LEGACY_MAPPING_NUMERIC_CONTRACTS, MAPPING_NUMERIC_V3,
    MappingNumericContract, MappingNumericRejected,
)


class MappingReplayMismatch(ValueError):
    """An admitted historical pipeline does not reproduce the recorded output."""


def load_data_mapping_execution(
    path_or_dir: str | Path,
    *,
    verify: bool = True,
    expected_source: Path | None = None,
) -> dict[str, Any]:
    path = mapping_execution_path(path_or_dir)
    with mapping_input_reads(str(path), expected_source=expected_source) as readset:
        result = _load_data_mapping_execution(path, verify=verify)
        if readset is not None and verify:
            readset.seal()
        return result


def _load_data_mapping_execution(path: Path, *, verify: bool) -> dict[str, Any]:
    payload = mapping_execution_header(path, DATA_MAPPING_EXECUTION_KIND)
    execution_version = payload["version"]
    if not verify:
        return payload
    if execution_version == 3:
        return _verify_mapping_execution(path, payload, numeric_contract=MAPPING_NUMERIC_V3)
    mismatch: ValueError | None = None
    for numeric_contract in LEGACY_MAPPING_NUMERIC_CONTRACTS:
        try:
            return _verify_mapping_execution(path, payload, numeric_contract=numeric_contract)
        except (MappingNumericRejected, MappingReplayMismatch) as exc:
            mismatch = exc
    assert mismatch is not None
    raise mismatch


def _verify_mapping_execution(path: Path, payload: dict[str, Any], *,
                              numeric_contract: MappingNumericContract) -> dict[str, Any]:
    execution_version = payload["version"]
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
        if not mapping_file_path(mark_mapping_metadata(expected_path)).is_file():
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
    if not isinstance(confirmation, LegacyDataMappingConfirmation):
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
    source_root = mapping_literal(Path(str(payload.get("source_root") or "")))
    require_mapping_original_source(source_root, [item.relative_path for item in proposal.sources],
                                    _read_json(Path(payload["request_seed"])))
    sources = verify_data_mapping_sources(proposal, source_root=source_root)
    source_hashes = {reference.source_id: reference.sha256 for reference in proposal.sources}
    expected_raw_hashes = {
        source_id: file_sha256(source_path, expected_sha256=source_hashes[source_id])
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
        if not mapping_file_path(expected_path, expected_sha256=output.get("sha256")).is_file():
            raise FileNotFoundError(f"Mapped data output not found: {expected_path}")
        if file_sha256(expected_path) != output.get("sha256"):
            raise ValueError(f"Mapped data output hash mismatch: {expected_path}")
        expected_output_paths.append(expected_path)
    expected_effective_input = (
        expected_output_paths[0] if len(expected_output_paths) == 1 else data_dir
    )
    if proposal.provider == "explicit_table_choice":
        expected_effective_input = execution_root / "selected_pairs.csv"
        expected_output_paths.append(expected_effective_input)
    if (
        Path(str(payload.get("effective_input") or "")).expanduser().resolve()
        != expected_effective_input.resolve()
    ):
        raise ValueError("Data mapping execution effective_input is inconsistent.")
    if expected_effective_input == data_dir:
        mapping_directory_path(payload)
    seed = Path(str(payload.get("request_seed") or "")).expanduser()
    if not mapping_file_path(seed, expected_sha256=payload.get("request_seed_sha256")).is_file() or file_sha256(seed) != payload.get("request_seed_sha256"):
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
    if not mapping_file_path(ledger, expected_sha256=payload.get("transform_ledger_sha256")).is_file() or file_sha256(ledger) != payload.get(
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
        != _mapping_step_parameters(proposal, confirmation, execution_version=execution_version)
    ):
        raise ValueError(
            "Active data mapping step no longer matches the confirmed proposal."
        )
    step_inputs = mapping_step.get("input_artifacts")
    expected_input = (
        (source_root / proposal.sources[0].relative_path).resolve()
        if execution_version >= 2 and len({s.relative_path for s in proposal.sources}) == 1 else source_root
    )
    if (
        not isinstance(step_inputs, list)
        or len(step_inputs) != 1
        or not isinstance(step_inputs[0], dict)
        or Path(str(step_inputs[0].get("path") or "")).expanduser().resolve()
        != expected_input
    ):
        raise ValueError("Active data mapping step changed its confirmed source root.")
    if execution_version >= 2 and len({s.relative_path for s in proposal.sources}) == 1 and step_inputs[0].get("sha256") != file_sha256(
            expected_input, expected_sha256=proposal.sources[0].sha256):
        raise ValueError("Active data mapping step changed its confirmed source hash.")
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
            or not mapping_file_path(mark_mapping_metadata(superseded_ledger), expected_sha256=payload.get("superseded_base_transform_ledger_sha256")).is_file()
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
    # A historical parser is admitted only inside these already verified source,
    # output, request and ledger seals. Every candidate must reproduce all sources.
    _sources, frames, units, events, _headers = _prepare_mapping_frames(
        proposal, source_root=source_root, numeric_contract=numeric_contract,
    )
    post_sources = verify_data_mapping_sources(proposal, source_root=source_root)
    if {source_id: file_sha256(source_path, expected_sha256=source_hashes[source_id]) for source_id, source_path in post_sources.items()} != expected_raw_hashes:
        raise ValueError("Data mapping execution raw-source proof changed while reconstructing frames.")
    for reference in proposal.sources:
        output = output_by_source[reference.source_id]
        expected_path = Path(str(output["path"])).expanduser().resolve()
        expected_frame = frames[reference.source_id]
        expected_hash = _mapped_csv_sha256(expected_frame, full_precision=proposal.provider == "explicit_table_choice")
        if file_sha256(expected_path) != expected_hash or output.get("sha256") != expected_hash:
            raise MappingReplayMismatch(f"Mapped data output does not reproduce: {expected_path}")
        expected_record = {
            "source_relative_path": reference.relative_path, "source_sha256": reference.sha256,
            "rows": int(expected_frame.shape[0]), "columns": [str(column) for column in expected_frame.columns],
            "units": dict(units[reference.source_id]), "sample_label": proposal.sample_labels.get(reference.source_id),
            "transformations": events[reference.source_id],
        }
        for field, expected_value in expected_record.items():
            if output.get(field) != expected_value:
                raise MappingReplayMismatch(f"Mapped output metadata mismatch for {reference.source_id!r}: {field}.")
    if proposal.provider == "explicit_table_choice":
        from sciplot_core.data_mapping.output_files import paired_table_text
        if mapping_file_bytes(expected_effective_input) != paired_table_text(proposal, frames).encode("utf-8"):
            raise MappingReplayMismatch("Selected paired table does not reproduce original values and metadata.")
    # Retain the original late seed/ledger checks after complete frame/output replay.
    post_frame_seals = [(seed, payload.get("request_seed_sha256"), "Immutable mapped request seed hash mismatch."),
                        (ledger, payload.get("transform_ledger_sha256"), "Active data mapping transform ledger hash mismatch.")]
    if base_transform_ledger is not None:
        post_frame_seals.append((Path(str(superseded_ledger_value)).expanduser(),
                                 payload.get("superseded_base_transform_ledger_sha256"), "Superseded base transform ledger hash mismatch."))
    for sealed_path, sealed_sha256, message in post_frame_seals:
        if not mapping_file_path(sealed_path, expected_sha256=sealed_sha256).is_file() or file_sha256(sealed_path) != sealed_sha256:
            raise ValueError(message)
    verified = deepcopy(payload)
    verified["confirmation_schema_version"] = 1 if legacy_confirmation else 2
    verified["confirmation_migration_required"] = legacy_confirmation
    verified["handoff_allowed"] = not legacy_confirmation
    if legacy_confirmation:
        verified["ready_to_use"] = False
    return verified
