"""Execute a confirmed mapping proposal as one atomic materialization transaction."""

from __future__ import annotations

import os
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.mapping_contract import (
    DataMappingConfirmation,
    DataMappingProposal,
    LegacyDataMappingConfirmation,
)
from sciplot_core.publication import (
    build_transform_ledger,
    build_transform_step,
)
from sciplot_core.study_model import normalize_study_model

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
    _now,
    data_mapping_proposal_sha256,
    _write_json,
    _read_json,
    load_data_mapping_proposal,
    load_data_mapping_confirmation,
    _resolve_source_root,
    _verify_request_binding,
    _validate_confirmation,
    _validate_confirmation_paths,
)

from sciplot_core.data_mapping.source_mapping import (
    _prepare_mapping_frames,
    preview_data_mapping_proposal,
)

from sciplot_core.data_mapping.output_files import (
    _safe_output_name,
    _write_mapped_csv,
    _rebase_paths,
)

from sciplot_core.data_mapping.request_rebinding import (
    _candidate_request,
)

from sciplot_core.data_mapping.execution_shared import (
    _mapping_step_parameters,
)

from sciplot_core.data_mapping.execution_loading import (
    load_data_mapping_execution,
)


def _validate_existing_execution(
    execution_path: Path,
    *,
    proposal: DataMappingProposal,
    confirmation: DataMappingConfirmation,
    request_path: Path,
) -> dict[str, Any]:
    manifest = load_data_mapping_execution(execution_path)
    if manifest.get("proposal_sha256") != data_mapping_proposal_sha256(proposal):
        raise ValueError(
            "Existing data mapping output belongs to different proposal content."
        )
    if manifest.get("confirmation_id") != confirmation.confirmation_id:
        raise ValueError(
            "Existing data mapping output uses a different confirmation receipt."
        )
    if file_sha256(request_path) != proposal.base_request_sha256:
        raise ValueError(
            "Existing data mapping output cannot be reused after request changes."
        )
    manifest["idempotent_reuse"] = True
    return manifest


def execute_data_mapping_proposal(
    proposal: DataMappingProposal | str | Path | dict[str, Any],
    confirmation: (
        DataMappingConfirmation
        | LegacyDataMappingConfirmation
        | str
        | Path
        | dict[str, Any]
    ),
    *,
    source_root: str | Path,
    request_path: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    resolved = load_data_mapping_proposal(proposal)
    receipt = load_data_mapping_confirmation(confirmation)
    _validate_confirmation(resolved, receipt)
    if isinstance(receipt, LegacyDataMappingConfirmation):
        raise ValueError(
            "DataMappingConfirmation v1 is inspectable only; explicitly "
            "reconfirm the normalized source, request, and output paths before execution."
        )
    root = _resolve_source_root(source_root)
    request_file = _verify_request_binding(resolved, request_path=request_path)
    mapping_root = Path(output_root).expanduser().resolve()
    _validate_confirmation_paths(
        receipt,
        source_root=root,
        request_path=request_file,
        output_root=mapping_root,
    )
    base_request = _read_json(request_file)
    preview = preview_data_mapping_proposal(
        resolved,
        source_root=root,
        request_path=request_file,
    )
    sources, frames, units, events, _headers = _prepare_mapping_frames(
        resolved, source_root=root
    )
    mapping_root.mkdir(parents=True, exist_ok=True)
    final_root = mapping_root / resolved.proposal_id
    final_execution = final_root / DATA_MAPPING_EXECUTION_FILENAME
    if final_root.exists():
        return _validate_existing_execution(
            final_execution,
            proposal=resolved,
            confirmation=receipt,
            request_path=request_file,
        )

    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{resolved.proposal_id}.tmp-",
            dir=mapping_root,
        )
    )
    raw_hashes_before = {
        source_id: file_sha256(path) for source_id, path in sources.items()
    }
    try:
        data_dir = temporary / "data"
        used_names: set[str] = set()
        outputs: list[dict[str, Any]] = []
        output_labels: list[str] = []
        output_paths: list[Path] = []
        for reference in resolved.sources:
            filename = _safe_output_name(reference, resolved, used=used_names)
            destination = data_dir / filename
            frame = frames[reference.source_id]
            _write_mapped_csv(destination, frame)
            output_paths.append(destination)
            output_labels.append(destination.stem)
            outputs.append(
                {
                    "source_id": reference.source_id,
                    "source_relative_path": reference.relative_path,
                    "source_sha256": reference.sha256,
                    "path": str(destination),
                    "sha256": file_sha256(destination),
                    "rows": int(frame.shape[0]),
                    "columns": [str(column) for column in frame.columns],
                    "units": dict(units[reference.source_id]),
                    "sample_label": resolved.sample_labels.get(reference.source_id),
                    "transformations": events[reference.source_id],
                }
            )

        if not output_paths:
            raise ValueError("Data mapping produced no output tables.")
        effective_input = output_paths[0] if len(output_paths) == 1 else data_dir
        proposal_hash = data_mapping_proposal_sha256(resolved)
        step = build_transform_step(
            step_id=f"data_mapping_{resolved.proposal_id}",
            operation="execute_confirmed_data_mapping_proposal",
            input_path=root,
            output_path=output_paths[0],
            additional_outputs=output_paths[1:],
            implementation_ref=(
                "sciplot_core.data_mapping.execute_data_mapping_proposal"
            ),
            parameters=_mapping_step_parameters(resolved, receipt),
        )
        final_step = _rebase_paths(step, source=temporary, target=final_root)
        study_model = (
            base_request.get("study_model")
            if isinstance(base_request.get("study_model"), dict)
            else {
                "kind": "sciplot_study_model",
                "version": 2,
                "samples": [],
                "figure_queue": [],
            }
        )
        base_transform_ledger = (
            deepcopy(base_request.get("transform_ledger"))
            if isinstance(base_request.get("transform_ledger"), dict)
            else None
        )
        ledger = build_transform_ledger(
            normalize_study_model(study_model),
            request=base_request,
            input_path=root,
            steps=[final_step],
            existing=None,
        )
        final_execution_path = final_root / DATA_MAPPING_EXECUTION_FILENAME
        superseded_ledger_path = (
            final_root / DATA_MAPPING_BASE_LEDGER_FILENAME
            if base_transform_ledger is not None
            else None
        )
        candidate = _candidate_request(
            base_request,
            resolved,
            source_root=root,
            execution_path=final_execution_path,
            output_root=final_root,
            transform_ledger=ledger,
            output_labels=output_labels,
            superseded_ledger_path=superseded_ledger_path,
        )
        proposal_path = temporary / DATA_MAPPING_PROPOSAL_FILENAME
        confirmation_path = temporary / DATA_MAPPING_CONFIRMATION_FILENAME
        preview_path = temporary / DATA_MAPPING_PREVIEW_FILENAME
        request_candidate_path = temporary / DATA_MAPPING_REQUEST_FILENAME
        request_seed_path = temporary / DATA_MAPPING_REQUEST_SEED_FILENAME
        base_request_path = temporary / DATA_MAPPING_BASE_REQUEST_FILENAME
        ledger_path = temporary / "transform_ledger.json"
        base_ledger_path = temporary / DATA_MAPPING_BASE_LEDGER_FILENAME
        base_request_path.write_bytes(request_file.read_bytes())
        if file_sha256(base_request_path) != resolved.base_request_sha256:
            raise RuntimeError(
                "The transaction base-request snapshot does not match "
                "the confirmed request hash."
            )
        _write_json(proposal_path, resolved.to_dict())
        _write_json(confirmation_path, receipt.to_dict())
        _write_json(preview_path, preview)
        _write_json(ledger_path, ledger)
        if base_transform_ledger is not None:
            _write_json(base_ledger_path, base_transform_ledger)
        _write_json(request_seed_path, candidate)
        _write_json(request_candidate_path, candidate)

        rebased_outputs = _rebase_paths(outputs, source=temporary, target=final_root)
        raw_hashes_after = {
            source_id: file_sha256(path) for source_id, path in sources.items()
        }
        if raw_hashes_after != raw_hashes_before:
            raise RuntimeError("Raw source hash changed during data mapping execution.")
        manifest = {
            "kind": DATA_MAPPING_EXECUTION_KIND,
            "version": DATA_MAPPING_EXECUTION_VERSION,
            "status": "passed",
            "state": "ready",
            "ready_to_use": True,
            "created_at": _now(),
            "proposal_id": resolved.proposal_id,
            "proposal_sha256": proposal_hash,
            "provider": resolved.provider,
            "confirmation_id": receipt.confirmation_id,
            "confirmed_by": receipt.confirmed_by,
            "confirmed_at": receipt.confirmed_at,
            "base_request": str(request_file),
            "base_request_sha256": resolved.base_request_sha256,
            "base_request_snapshot": str(
                final_root / DATA_MAPPING_BASE_REQUEST_FILENAME
            ),
            "base_request_snapshot_sha256": file_sha256(base_request_path),
            "source_root": str(root),
            "source_hashes": resolved.source_hashes,
            "raw_hashes_before": raw_hashes_before,
            "raw_hashes_after": raw_hashes_after,
            "raw_inputs_unchanged": True,
            "output_root": str(final_root),
            "data_dir": str(final_root / "data"),
            "effective_input": _rebase_paths(
                str(effective_input), source=temporary, target=final_root
            ),
            "outputs": rebased_outputs,
            "proposal": str(final_root / DATA_MAPPING_PROPOSAL_FILENAME),
            "confirmation": str(final_root / DATA_MAPPING_CONFIRMATION_FILENAME),
            "preview": str(final_root / DATA_MAPPING_PREVIEW_FILENAME),
            "request_candidate": str(final_root / DATA_MAPPING_REQUEST_FILENAME),
            "request_candidate_initial_sha256": file_sha256(request_candidate_path),
            "request_seed": str(final_root / DATA_MAPPING_REQUEST_SEED_FILENAME),
            "request_seed_sha256": file_sha256(request_seed_path),
            "transform_ledger": str(final_root / "transform_ledger.json"),
            "transform_ledger_sha256": file_sha256(ledger_path),
            "superseded_base_transform_ledger": (
                str(final_root / DATA_MAPPING_BASE_LEDGER_FILENAME)
                if base_transform_ledger is not None
                else None
            ),
            "superseded_base_transform_ledger_sha256": (
                file_sha256(base_ledger_path)
                if base_transform_ledger is not None
                else None
            ),
            "transform_steps": [final_step],
            "request_patch": json_safe(resolved.request_patch),
            "limitations": [
                "The mapped request is a candidate and does not overwrite the current project request or exact-current VSZ.",
                "Any prior transform ledger is archived as superseded because this candidate starts a new derivation from the proposal's explicit source hashes.",
                "Visual regeneration remains an explicit user action.",
            ],
        }
        _write_json(temporary / DATA_MAPPING_EXECUTION_FILENAME, manifest)
        os.replace(temporary, final_root)
        return load_data_mapping_execution(final_execution_path)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
