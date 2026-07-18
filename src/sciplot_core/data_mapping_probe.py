from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas import (
    DataColumnMapping,
    DataMappingConfirmation,
    DataMappingProposal,
    DataSourceReference,
    DeclarativeTransformation,
    LegacyDataMappingConfirmation,
)
from sciplot_core.data_mapping import (
    DATA_MAPPING_BASE_LEDGER_FILENAME,
    DATA_MAPPING_BASE_REQUEST_FILENAME,
    DATA_MAPPING_REQUEST_SEED_FILENAME,
    create_data_mapping_confirmation,
    execute_data_mapping_proposal,
    load_data_mapping_confirmation,
    load_data_mapping_execution,
    preview_data_mapping_proposal,
    resolve_data_mapping_request,
)
from sciplot_core.publication import build_transform_ledger, build_transform_step


def _check(
    check_id: str,
    label: str,
    passed: bool,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "evidence": json_safe(evidence or {}),
    }


def _raises_value_error(callback: Any) -> bool:
    try:
        callback()
    except (OSError, RuntimeError, ValueError):
        return True
    return False


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(file_sha256(path).encode("ascii"))
    return digest.hexdigest()


def _write_request(path: Path, source: Path) -> None:
    prior_step = build_transform_step(
        step_id="prior_semantic",
        operation="legacy_semantic_preparation",
        input_path=source,
        output_path=source,
        implementation_ref="probe_legacy_runtime",
    )
    path.write_text(
        json.dumps(
            {
                "input": str(source),
                "output": str(path.parent / "baseline_run"),
                "template": "curve",
                "exports": ["pdf", "tiff_300"],
                "transform_ledger": {
                    "kind": "sciplot_transform_ledger",
                    "version": 1,
                    "status": "runtime_recorded",
                    "steps": [prior_step],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _primary_proposal(
    *,
    request: Path,
    source_file: Path,
) -> DataMappingProposal:
    return DataMappingProposal(
        proposal_id="mapping-probe-primary",
        base_request_sha256=file_sha256(request),
        provider="typed_provider_stub",
        sources=(
            DataSourceReference(
                source_id="experiment",
                relative_path=source_file.name,
                sha256=file_sha256(source_file),
            ),
        ),
        columns=(
            DataColumnMapping(
                source_id="experiment",
                source_column_index=0,
                expected_header="time_ms",
                output_column="time_ms",
                role="x",
            ),
            DataColumnMapping(
                source_id="experiment",
                source_column_index=1,
                expected_header="signal",
                output_column="signal",
                role="y",
            ),
            DataColumnMapping(
                source_id="experiment",
                source_column_index=2,
                expected_header="reference",
                output_column="reference",
                role="y",
            ),
            DataColumnMapping(
                source_id="experiment",
                source_column_index=3,
                expected_header="quality",
                output_column="quality",
                role="metadata",
            ),
        ),
        unit_overrides={"time_ms": "ms"},
        transformations=(
            DeclarativeTransformation(
                transformation_id="exclude_bad_quality",
                transformation_type="exclude",
                parameters={
                    "where": [
                        {
                            "column": "quality",
                            "operator": "eq",
                            "value": "bad",
                        }
                    ]
                },
            ),
            DeclarativeTransformation(
                transformation_id="convert_time",
                transformation_type="unit_convert",
                parameters={
                    "column": "time_ms",
                    "from_unit": "ms",
                    "to_unit": "s",
                },
            ),
            DeclarativeTransformation(
                transformation_id="derive_signal_ratio",
                transformation_type="derive_ratio",
                parameters={
                    "numerator": "signal",
                    "denominator": "reference",
                    "output": "ratio",
                },
            ),
            DeclarativeTransformation(
                transformation_id="normalize_signal",
                transformation_type="normalize_baseline",
                parameters={
                    "column": "signal",
                    "output": "signal_norm",
                    "method": "first_finite",
                },
            ),
            DeclarativeTransformation(
                transformation_id="select_plot_columns",
                transformation_type="select",
                parameters={"columns": ["time_ms", "signal_norm", "ratio"]},
            ),
            DeclarativeTransformation(
                transformation_id="sort_time",
                transformation_type="sort",
                parameters={"by": ["time_ms"], "ascending": True},
            ),
        ),
        request_patch={
            "x_metric": "time_ms",
            "y_metric": "signal_norm",
        },
        confidence=0.93,
        rationale="Exercise the deterministic mapping contract.",
    )


def _aggregate_proposal(
    *,
    request: Path,
    source_file: Path,
) -> DataMappingProposal:
    return DataMappingProposal(
        proposal_id="mapping-probe-aggregate",
        base_request_sha256=file_sha256(request),
        provider="typed_provider_stub",
        sources=(
            DataSourceReference(
                source_id="replicates",
                relative_path=source_file.name,
                sha256=file_sha256(source_file),
            ),
        ),
        columns=(
            DataColumnMapping(
                "replicates", 0, "sample", "sample", expected_header="sample"
            ),
            DataColumnMapping("replicates", 1, "x", "x", expected_header="x"),
            DataColumnMapping(
                "replicates", 2, "value", "value", expected_header="value"
            ),
        ),
        transformations=(
            DeclarativeTransformation(
                transformation_id="aggregate_mean",
                transformation_type="aggregate_replicates",
                parameters={
                    "group_by": ["sample", "x"],
                    "value_columns": ["value"],
                    "method": "mean",
                    "include_count": True,
                    "count_column": "n",
                },
            ),
            DeclarativeTransformation(
                transformation_id="aggregate_sort",
                transformation_type="sort",
                parameters={"by": ["sample", "x"], "ascending": True},
            ),
        ),
        confidence=0.9,
        rationale="Exercise deterministic replicate aggregation.",
    )


def run_data_mapping_probe(
    *,
    output_root: str | Path,
) -> dict[str, Any]:
    root = Path(output_root).expanduser().resolve()
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    source = root / "source"
    source.mkdir()
    primary_source = source / "experiment.csv"
    primary_source.write_text(
        "time_ms,signal,reference,quality\n"
        "0,10,2,ok\n"
        "1000,12,3,ok\n"
        "2000,14,0,bad\n"
        "3000,16,4,ok\n",
        encoding="utf-8",
    )
    aggregate_source = source / "replicates.csv"
    aggregate_source.write_text(
        "sample,x,value\nA,0,1\nA,0,3\nA,1,5\nA,1,7\n",
        encoding="utf-8",
    )
    decimal_source = source / "decimal_comma.csv"
    decimal_source.write_text(
        "x;y\n10,0;20,0\n2,5;5,0\n1,25;2,5\n",
        encoding="utf-8",
    )
    nonnumeric_source = source / "nonnumeric.csv"
    nonnumeric_source.write_text(
        "x,y\nalpha,beta\ngamma,delta\n",
        encoding="utf-8",
    )
    request = root / "plot_request.json"
    _write_request(request, source)
    proposal = _primary_proposal(
        request=request,
        source_file=primary_source,
    )
    proposal_roundtrip = DataMappingProposal.from_dict(proposal.to_dict())
    initial_tree = _tree_digest(root)
    preview = preview_data_mapping_proposal(
        proposal,
        source_root=source,
        request_path=request,
    )
    preview_tree = _tree_digest(root)
    confirmation = create_data_mapping_confirmation(
        proposal,
        source_root=source,
        request_path=request,
        output_root=root / "mappings",
        confirmed_by="probe_user",
    )
    alternate_source = root / "alternate_source"
    alternate_source.mkdir()
    shutil.copy2(primary_source, alternate_source / primary_source.name)
    alternate_request = root / "alternate_plot_request.json"
    shutil.copy2(request, alternate_request)
    rebound_output = root / "rebound_output"
    source_root_rebind_rejected = _raises_value_error(
        lambda: execute_data_mapping_proposal(
            proposal,
            confirmation,
            source_root=alternate_source,
            request_path=request,
            output_root=root / "mappings",
        )
    )
    request_path_rebind_rejected = _raises_value_error(
        lambda: execute_data_mapping_proposal(
            proposal,
            confirmation,
            source_root=source,
            request_path=alternate_request,
            output_root=root / "mappings",
        )
    )
    output_root_rebind_rejected = _raises_value_error(
        lambda: execute_data_mapping_proposal(
            proposal,
            confirmation,
            source_root=source,
            request_path=request,
            output_root=rebound_output,
        )
    )
    rebound_paths_zero_write = not rebound_output.exists()
    primary_hash = file_sha256(primary_source)
    result = execute_data_mapping_proposal(
        proposal,
        confirmation,
        source_root=source,
        request_path=request,
        output_root=root / "mappings",
    )
    mapped = pd.read_csv(result["effective_input"])
    candidate_path = Path(result["request_candidate"])
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    superseded_ledger_path = (
        Path(result["output_root"]) / DATA_MAPPING_BASE_LEDGER_FILENAME
    )
    superseded_ledger = json.loads(superseded_ledger_path.read_text(encoding="utf-8"))
    execution_reuse = execute_data_mapping_proposal(
        proposal,
        confirmation,
        source_root=source,
        request_path=request,
        output_root=root / "mappings",
    )

    legacy_confirmation_payload = confirmation.to_dict()
    legacy_confirmation_payload["version"] = 1
    for field in ("source_root", "request_path", "output_root"):
        legacy_confirmation_payload.pop(field)
    legacy_fixture_path = root / "committed_confirmation_v1.json"
    legacy_fixture_path.write_text(
        json.dumps(legacy_confirmation_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    legacy_confirmation = load_data_mapping_confirmation(legacy_fixture_path)
    legacy_execution_rejected = _raises_value_error(
        lambda: execute_data_mapping_proposal(
            proposal,
            legacy_confirmation,
            source_root=source,
            request_path=request,
            output_root=root / "legacy_execution_blocked",
        )
    )
    committed_confirmation_path = Path(result["confirmation"])
    committed_confirmation_bytes = committed_confirmation_path.read_bytes()
    committed_confirmation_path.write_text(
        json.dumps(legacy_confirmation_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    try:
        legacy_execution = load_data_mapping_execution(result["output_root"])
        legacy_handoff_rejected = _raises_value_error(
            lambda: resolve_data_mapping_request(
                candidate,
                base_dir=candidate_path.parent,
            )
        )
    finally:
        committed_confirmation_path.write_bytes(committed_confirmation_bytes)
    legacy_execution_inspectable = bool(
        isinstance(legacy_confirmation, LegacyDataMappingConfirmation)
        and legacy_execution.get("confirmation_schema_version") == 1
        and legacy_execution.get("confirmation_migration_required") is True
        and legacy_execution.get("handoff_allowed") is False
        and legacy_execution.get("ready_to_use") is False
    )
    reconfirmed = create_data_mapping_confirmation(
        proposal,
        source_root=source,
        request_path=request,
        output_root=root / "legacy_reconfirmed_mappings",
        confirmed_by="legacy_v1_explicit_reconfirmation_probe",
    )
    reconfirmed_result = execute_data_mapping_proposal(
        proposal,
        reconfirmed,
        source_root=source,
        request_path=request,
        output_root=root / "legacy_reconfirmed_mappings",
    )
    reconfirmed_execution = load_data_mapping_execution(
        reconfirmed_result["output_root"]
    )
    legacy_reconfirmation_restores_authority = bool(
        reconfirmed.to_dict()["version"] == 2
        and reconfirmed.confirmation_id != legacy_confirmation.confirmation_id
        and reconfirmed_execution.get("confirmation_schema_version") == 2
        and reconfirmed_execution.get("confirmation_migration_required") is False
        and reconfirmed_execution.get("handoff_allowed") is True
        and reconfirmed_execution.get("ready_to_use") is True
    )

    candidate["review_notes"] = [
        *candidate.get("review_notes", []),
        "Runtime metadata may evolve without invalidating the immutable request seed.",
    ]
    candidate_path.write_text(
        json.dumps(candidate, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    evolving_candidate_valid = (
        load_data_mapping_execution(result["output_root"])["status"] == "passed"
    )
    candidate_with_wrong_raw_input = dict(candidate)
    candidate_with_wrong_raw_input["input"] = str(aggregate_source)
    raw_authority_tamper_rejected = _raises_value_error(
        lambda: resolve_data_mapping_request(
            candidate_with_wrong_raw_input,
            base_dir=candidate_path.parent,
        )
    )
    candidate_with_wrong_proposal = dict(candidate)
    candidate_with_wrong_proposal["data_mapping_proposal_id"] = (
        "another-confirmed-mapping"
    )
    proposal_identity_tamper_rejected = _raises_value_error(
        lambda: resolve_data_mapping_request(
            candidate_with_wrong_proposal,
            base_dir=candidate_path.parent,
        )
    )

    output_path = Path(result["outputs"][0]["path"])
    output_bytes = output_path.read_bytes()
    output_path.write_bytes(output_bytes + b"\n")
    output_tamper_rejected = _raises_value_error(
        lambda: load_data_mapping_execution(result["output_root"])
    )
    output_path.write_bytes(output_bytes)

    seed_path = Path(result["output_root"]) / DATA_MAPPING_REQUEST_SEED_FILENAME
    seed_bytes = seed_path.read_bytes()
    seed_path.write_bytes(seed_bytes + b"\n")
    seed_tamper_rejected = _raises_value_error(
        lambda: load_data_mapping_execution(result["output_root"])
    )
    seed_path.write_bytes(seed_bytes)

    superseded_ledger_bytes = superseded_ledger_path.read_bytes()
    superseded_ledger_path.write_bytes(superseded_ledger_bytes + b"\n")
    superseded_ledger_tamper_rejected = _raises_value_error(
        lambda: load_data_mapping_execution(result["output_root"])
    )
    superseded_ledger_path.write_bytes(superseded_ledger_bytes)

    active_ledger_path = Path(result["transform_ledger"])
    active_ledger_bytes = active_ledger_path.read_bytes()
    active_ledger_path.write_bytes(active_ledger_bytes + b"\n")
    active_ledger_tamper_rejected = _raises_value_error(
        lambda: load_data_mapping_execution(result["output_root"])
    )
    active_ledger_path.write_bytes(active_ledger_bytes)

    execution_path = Path(result["output_root"]) / "execution.json"
    execution_bytes = execution_path.read_bytes()

    coordinated_seed = json.loads(seed_bytes)
    coordinated_seed["input"] = str(aggregate_source)
    seed_path.write_text(
        json.dumps(coordinated_seed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    coordinated_manifest = json.loads(execution_bytes)
    coordinated_seed_hash = file_sha256(seed_path)
    coordinated_manifest["request_seed_sha256"] = coordinated_seed_hash
    coordinated_manifest["request_candidate_initial_sha256"] = coordinated_seed_hash
    execution_path.write_text(
        json.dumps(coordinated_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    coordinated_seed_tamper_rejected = _raises_value_error(
        lambda: load_data_mapping_execution(result["output_root"])
    )
    seed_path.write_bytes(seed_bytes)
    execution_path.write_bytes(execution_bytes)

    redirected_ledger = root / "redirected_superseded_ledger.json"
    redirected_ledger.write_bytes(superseded_ledger_bytes)
    coordinated_seed = json.loads(seed_bytes)
    coordinated_seed["data_mapping_superseded_transform_ledger"] = str(
        redirected_ledger
    )
    seed_path.write_text(
        json.dumps(coordinated_seed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    coordinated_manifest = json.loads(execution_bytes)
    coordinated_manifest["superseded_base_transform_ledger"] = str(redirected_ledger)
    coordinated_manifest["superseded_base_transform_ledger_sha256"] = file_sha256(
        redirected_ledger
    )
    coordinated_seed_hash = file_sha256(seed_path)
    coordinated_manifest["request_seed_sha256"] = coordinated_seed_hash
    coordinated_manifest["request_candidate_initial_sha256"] = coordinated_seed_hash
    execution_path.write_text(
        json.dumps(coordinated_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    coordinated_superseded_redirect_rejected = _raises_value_error(
        lambda: load_data_mapping_execution(result["output_root"])
    )
    seed_path.write_bytes(seed_bytes)
    execution_path.write_bytes(execution_bytes)

    coordinated_ledger = json.loads(active_ledger_bytes)
    coordinated_ledger["steps"][0]["parameters"]["provider"] = "forged_provider"
    active_ledger_path.write_text(
        json.dumps(coordinated_ledger, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    coordinated_seed = json.loads(seed_bytes)
    coordinated_seed["transform_ledger"] = coordinated_ledger
    seed_path.write_text(
        json.dumps(coordinated_seed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    coordinated_manifest = json.loads(execution_bytes)
    coordinated_manifest["transform_steps"] = coordinated_ledger["steps"]
    coordinated_manifest["transform_ledger_sha256"] = file_sha256(active_ledger_path)
    coordinated_seed_hash = file_sha256(seed_path)
    coordinated_manifest["request_seed_sha256"] = coordinated_seed_hash
    coordinated_manifest["request_candidate_initial_sha256"] = coordinated_seed_hash
    execution_path.write_text(
        json.dumps(coordinated_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    coordinated_lineage_tamper_rejected = _raises_value_error(
        lambda: load_data_mapping_execution(result["output_root"])
    )
    active_ledger_path.write_bytes(active_ledger_bytes)
    seed_path.write_bytes(seed_bytes)
    execution_path.write_bytes(execution_bytes)

    execution_payload = json.loads(execution_bytes)
    execution_payload["request_patch"] = {
        **execution_payload.get("request_patch", {}),
        "template": "silently_changed_template",
    }
    execution_path.write_text(
        json.dumps(execution_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    manifest_request_patch_tamper_rejected = _raises_value_error(
        lambda: load_data_mapping_execution(result["output_root"])
    )
    execution_path.write_bytes(execution_bytes)

    execution_payload = json.loads(execution_bytes)
    execution_payload["effective_input"] = str(primary_source)
    execution_path.write_text(
        json.dumps(execution_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    manifest_effective_input_tamper_rejected = _raises_value_error(
        lambda: load_data_mapping_execution(result["output_root"])
    )
    execution_path.write_bytes(execution_bytes)

    request_bytes = request.read_bytes()
    request.write_bytes(request_bytes + b"\n")
    stale_request_rejected = _raises_value_error(
        lambda: preview_data_mapping_proposal(
            proposal,
            source_root=source,
            request_path=request,
        )
    )
    request.write_bytes(request_bytes)

    source_bytes = primary_source.read_bytes()
    primary_source.write_bytes(source_bytes + b"\n")
    source_tamper_rejected = _raises_value_error(
        lambda: preview_data_mapping_proposal(
            proposal,
            source_root=source,
            request_path=request,
        )
    )
    primary_source.write_bytes(source_bytes)

    forged_confirmation = DataMappingConfirmation(
        proposal_id=proposal.proposal_id,
        proposal_sha256="f" * 64,
        base_request_sha256=proposal.base_request_sha256,
        source_hashes=proposal.source_hashes,
        source_root=str(source.resolve()),
        request_path=str(request.resolve()),
        output_root=str((root / "forged").resolve()),
        confirmed_by="forged",
    )
    forged_confirmation_rejected = _raises_value_error(
        lambda: execute_data_mapping_proposal(
            proposal,
            forged_confirmation,
            source_root=source,
            request_path=request,
            output_root=root / "forged",
        )
    )
    unsafe_path_rejected = _raises_value_error(
        lambda: DataSourceReference(
            source_id="unsafe",
            relative_path="../escape.csv",
            sha256="a" * 64,
        )
    )
    executable_key_rejected = _raises_value_error(
        lambda: DeclarativeTransformation(
            transformation_type="select",
            parameters={
                "columns": ["x"],
                "script": "drop everything",
            },
        )
    )
    self_authorization_rejected = _raises_value_error(
        lambda: DataMappingProposal.from_dict(
            {
                **proposal.to_dict(),
                "executable": True,
            }
        )
    )
    proposal_without_timestamp = proposal.to_dict()
    proposal_without_timestamp.pop("created_at")
    missing_proposal_timestamp_rejected = _raises_value_error(
        lambda: DataMappingProposal.from_dict(proposal_without_timestamp)
    )
    confirmation_without_timestamp = confirmation.to_dict()
    confirmation_without_timestamp.pop("confirmed_at")
    missing_confirmation_timestamp_rejected = _raises_value_error(
        lambda: DataMappingConfirmation.from_dict(confirmation_without_timestamp)
    )
    proposal_without_transformation_id = proposal.to_dict()
    proposal_without_transformation_id["transformations"][0].pop("transformation_id")
    missing_transformation_id_rejected = _raises_value_error(
        lambda: DataMappingProposal.from_dict(proposal_without_transformation_id)
    )
    non_string_provider = proposal.to_dict()
    non_string_provider["provider"] = True
    non_string_contract_fields_rejected = all(
        (
            _raises_value_error(
                lambda: DataMappingProposal.from_dict(non_string_provider)
            ),
            _raises_value_error(
                lambda: DataSourceReference(
                    source_id=8,
                    relative_path="source.csv",
                    sha256="a" * 64,
                )
            ),
            _raises_value_error(
                lambda: DeclarativeTransformation(
                    transformation_id="invalid_sort_option",
                    transformation_type="sort",
                    parameters={
                        "by": ["x"],
                        "na_position": False,
                    },
                )
            ),
            _raises_value_error(
                lambda: DeclarativeTransformation(
                    transformation_id="invalid_numeric_condition",
                    transformation_type="exclude",
                    parameters={
                        "where": [
                            {
                                "column": "x",
                                "operator": "lt",
                                "value": "2",
                            }
                        ]
                    },
                )
            ),
        )
    )
    invalid_numeric_outputs_rejected = all(
        (
            _raises_value_error(
                lambda: DataMappingProposal(
                    proposal_id="category-only",
                    base_request_sha256=file_sha256(request),
                    provider="typed_provider_stub",
                    sources=(
                        DataSourceReference(
                            source_id="category_only",
                            relative_path=primary_source.name,
                            sha256=file_sha256(primary_source),
                        ),
                    ),
                    columns=(
                        DataColumnMapping(
                            "category_only",
                            3,
                            "quality",
                            "category",
                            expected_header="quality",
                        ),
                    ),
                )
            ),
            _raises_value_error(
                lambda: preview_data_mapping_proposal(
                    DataMappingProposal(
                        proposal_id="empty-mapped-output",
                        base_request_sha256=file_sha256(request),
                        provider="typed_provider_stub",
                        sources=(
                            DataSourceReference(
                                source_id="empty_output",
                                relative_path=primary_source.name,
                                sha256=file_sha256(primary_source),
                            ),
                        ),
                        columns=(
                            DataColumnMapping(
                                "empty_output",
                                0,
                                "x",
                                "x",
                                expected_header="time_ms",
                            ),
                            DataColumnMapping(
                                "empty_output",
                                1,
                                "y",
                                "y",
                                expected_header="signal",
                            ),
                        ),
                        transformations=(
                            DeclarativeTransformation(
                                transformation_id="drop_every_row",
                                transformation_type="exclude",
                                parameters={
                                    "row_indices": [0, 1, 2, 3],
                                },
                            ),
                        ),
                    ),
                    source_root=source,
                    request_path=request,
                )
            ),
            _raises_value_error(
                lambda: preview_data_mapping_proposal(
                    DataMappingProposal(
                        proposal_id="nonnumeric-mapped-output",
                        base_request_sha256=file_sha256(request),
                        provider="typed_provider_stub",
                        sources=(
                            DataSourceReference(
                                source_id="nonnumeric_output",
                                relative_path=nonnumeric_source.name,
                                sha256=file_sha256(nonnumeric_source),
                            ),
                        ),
                        columns=(
                            DataColumnMapping(
                                "nonnumeric_output",
                                0,
                                "x",
                                "x",
                                expected_header="x",
                            ),
                            DataColumnMapping(
                                "nonnumeric_output",
                                1,
                                "y",
                                "y",
                                expected_header="y",
                            ),
                        ),
                    ),
                    source_root=source,
                    request_path=request,
                )
            ),
        )
    )

    aggregate_proposal = _aggregate_proposal(
        request=request,
        source_file=aggregate_source,
    )
    aggregate_confirmation = create_data_mapping_confirmation(
        aggregate_proposal,
        source_root=source,
        request_path=request,
        output_root=root / "aggregate_mappings",
        confirmed_by="probe_user",
    )
    aggregate_result = execute_data_mapping_proposal(
        aggregate_proposal,
        aggregate_confirmation,
        source_root=source,
        request_path=request,
        output_root=root / "aggregate_mappings",
    )
    aggregate_frame = pd.read_csv(aggregate_result["effective_input"])

    decimal_proposal = DataMappingProposal(
        proposal_id="mapping-probe-decimal-comma",
        base_request_sha256=file_sha256(request),
        provider="typed_provider_stub",
        sources=(
            DataSourceReference(
                source_id="decimal",
                relative_path=decimal_source.name,
                sha256=file_sha256(decimal_source),
                delimiter=";",
                decimal=",",
            ),
        ),
        columns=(
            DataColumnMapping("decimal", 0, "x", "x", expected_header="x"),
            DataColumnMapping("decimal", 1, "y", "y", expected_header="y"),
        ),
        transformations=(
            DeclarativeTransformation(
                transformation_id="sort_decimal_x",
                transformation_type="sort",
                parameters={"by": ["x"], "ascending": True},
            ),
        ),
        confidence=0.9,
    )
    decimal_confirmation = create_data_mapping_confirmation(
        decimal_proposal,
        source_root=source,
        request_path=request,
        output_root=root / "decimal_mappings",
        confirmed_by="probe_user",
    )
    decimal_result = execute_data_mapping_proposal(
        decimal_proposal,
        decimal_confirmation,
        source_root=source,
        request_path=request,
        output_root=root / "decimal_mappings",
    )
    decimal_frame = pd.read_csv(decimal_result["effective_input"])

    atomic_source_2 = source / "second.csv"
    atomic_source_2.write_text(
        "x,y\n0,1\n1,2\n",
        encoding="utf-8",
    )
    atomic_proposal = DataMappingProposal(
        proposal_id="mapping-probe-atomic",
        base_request_sha256=file_sha256(request),
        provider="typed_provider_stub",
        sources=(
            DataSourceReference(
                "first", primary_source.name, file_sha256(primary_source)
            ),
            DataSourceReference(
                "second", atomic_source_2.name, file_sha256(atomic_source_2)
            ),
        ),
        columns=(
            DataColumnMapping("first", 0, "x", "x", expected_header="time_ms"),
            DataColumnMapping("first", 1, "y", "y", expected_header="signal"),
            DataColumnMapping("second", 0, "x", "x", expected_header="x"),
            DataColumnMapping("second", 1, "y", "y", expected_header="y"),
        ),
        sample_labels={
            "first": "Sample",
            "second": "sample",
        },
        confidence=0.8,
    )
    atomic_root = root / "atomic_mappings"
    atomic_confirmation = create_data_mapping_confirmation(
        atomic_proposal,
        source_root=source,
        request_path=request,
        output_root=atomic_root,
        confirmed_by="probe_user",
    )
    call_count = 0

    def _faulting_write(path: Path, frame: pd.DataFrame) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("injected second-output write failure")
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)

    with patch(
        "sciplot_core.data_mapping._write_mapped_csv",
        side_effect=_faulting_write,
    ):
        atomic_failure_rejected = _raises_value_error(
            lambda: execute_data_mapping_proposal(
                atomic_proposal,
                atomic_confirmation,
                source_root=source,
                request_path=request,
                output_root=atomic_root,
            )
        )
    atomic_final_absent = not (atomic_root / atomic_proposal.proposal_id).exists()
    atomic_temps_absent = not any(
        path.name.startswith(f".{atomic_proposal.proposal_id}.tmp-")
        for path in atomic_root.iterdir()
    )
    collision_root = root / "casefold_mappings"
    collision_confirmation = create_data_mapping_confirmation(
        atomic_proposal,
        source_root=source,
        request_path=request,
        output_root=collision_root,
        confirmed_by="probe_user",
    )
    collision_result = execute_data_mapping_proposal(
        atomic_proposal,
        collision_confirmation,
        source_root=source,
        request_path=request,
        output_root=collision_root,
    )
    collision_output_names = [
        Path(str(output["path"])).name
        for output in collision_result.get("outputs", [])
        if isinstance(output, dict)
    ]

    existing_step = build_transform_step(
        step_id="mapping_step",
        operation="execute_confirmed_data_mapping_proposal",
        input_path=primary_source,
        output_path=Path(result["effective_input"]),
        implementation_ref="probe",
    )
    runtime_step = build_transform_step(
        step_id="semantic_step",
        operation="prepare_semantic_source",
        input_path=Path(result["effective_input"]),
        output_path=Path(result["effective_input"]),
        implementation_ref="probe",
    )
    merged_ledger = build_transform_ledger(
        {
            "kind": "sciplot_study_model",
            "version": 2,
            "samples": [],
            "figure_queue": [],
        },
        request={},
        input_path=primary_source,
        steps=[existing_step, runtime_step],
        existing=None,
    )
    merged_ids = [
        str(step.get("id"))
        for step in merged_ledger.get("steps", [])
        if isinstance(step, dict)
    ]
    from sciplot_core.studio import (
        StudioSeries,
        _apply_series_options,
        _coerced_numeric_frame,
        _mapping_series_coverage,
        _read_source_frame_records,
        _save_veusz_document_from_spec,
        _series_label_from_column,
        _series_from_frame_records,
        _series_from_request,
        _studio_export_semantic_payload,
        _studio_snapshot_sources,
        _write_veusz_document,
    )
    from sciplot_core.source_coverage import (
        verify_rendered_mapping_source_coverage,
    )
    from sciplot_core.render import render_to_dir
    from sciplot_core.split import build_split_plan

    request_only_semantic = _studio_export_semantic_payload(
        request={"rule_id": "ftir_spectrum"},
        intake_manifest={},
    )
    numeric_sample_label = _series_label_from_column(
        pd.Series(["a.u.", "8", 0.1, 0.2]),
        fallback="fallback",
    )
    unit_like_sample_label = _series_label_from_column(
        pd.Series(["PA", "Pa", 1.0, 2.0]),
        fallback="fallback",
    )
    numeric_sample_frame = _coerced_numeric_frame(
        pd.DataFrame(
            {
                "Elution time": ["min", "8", 14.5, 15.0],
                "Detector response": ["a.u.", "8", 0.1, 0.2],
            }
        )
    )
    ordinary_numeric_frame = _coerced_numeric_frame(
        pd.DataFrame(
            {
                "x": [1.0, 2.0, 3.0],
                "y": [1.0, 4.0, 9.0],
            }
        )
    )
    ambiguous_metadata_source = root / "ambiguous_unit_like_metadata.csv"
    pd.DataFrame(
        [
            ["Time", "Signal", "Time", "Signal", "Time", "Signal"],
            ["s", "a.u.", "s", "a.u.", "s", "a.u."],
            ["C", "C", "Pa", "Pa", "min", "min"],
            [1.0, 1.0, 1.0, 2.0, 1.0, 3.0],
            [2.0, 1.5, 2.0, 2.5, 2.0, 3.5],
        ]
    ).to_csv(ambiguous_metadata_source, index=False, header=False)
    ambiguous_metadata_roles_rejected = _raises_value_error(
        lambda: _series_from_frame_records(
            {"template": "curve"},
            frames=_read_source_frame_records(
                ambiguous_metadata_source,
                request={"template": "curve"},
            ),
        )
    )
    selection_probe_series = StudioSeries(
        label="A",
        x_name="selection_x",
        y_name="selection_y",
        x_values=(1.0, 2.0),
        y_values=(2.0, 3.0),
        color="#000000",
    )
    unknown_series_include_rejected = _raises_value_error(
        lambda: _apply_series_options(
            [selection_probe_series],
            render_options={"series_include": ["missing"]},
            request={"template": "line"},
        )
    )
    all_series_hidden_rejected = _raises_value_error(
        lambda: _apply_series_options(
            [selection_probe_series],
            render_options={
                "series_styles": [{"label": "A", "visible": False}]
            },
            request={"template": "line"},
        )
    )
    duplicate_series_label_rejected = _raises_value_error(
        lambda: _apply_series_options(
            [
                selection_probe_series,
                StudioSeries(
                    label="A",
                    x_name="selection_x_2",
                    y_name="selection_y_2",
                    x_values=(1.0, 2.0),
                    y_values=(4.0, 5.0),
                    color="#111111",
                ),
            ],
            render_options={},
            request={"template": "line"},
        )
    )
    duplicate_split_label_rejected = _raises_value_error(
        lambda: build_split_plan(
            ["A", "A", "B"],
            policy={
                "mode": "series_chunks",
                "max_series_per_panel": 1,
            },
        )
    )
    coverage_root = root / "renderer_source_coverage"
    coverage_root.mkdir(parents=True, exist_ok=True)
    coverage_source_a = coverage_root / "source_a.csv"
    coverage_source_b = coverage_root / "source_b.csv"
    pd.DataFrame(
        {
            "x": [0.0, 1.0],
            "y": [1.0, 2.0],
            "y_alt": [11.0, 12.0],
        }
    ).to_csv(
        coverage_source_a,
        index=False,
    )
    pd.DataFrame(
        {
            "x": [0.0, 1.0],
            "y": [3.0, 4.0],
            "y_alt": [13.0, 14.0],
        }
    ).to_csv(
        coverage_source_b,
        index=False,
    )
    reserved_terminal_flag_rejected = _raises_value_error(
        lambda: _series_from_request(
            {
                "input": str(coverage_source_a),
                "template": "curve",
                "_terminal_source_prepared": True,
            },
            base_dir=coverage_root,
        )
    )
    coverage_request = {
        "template": "curve",
        "render_options": {"show_legend": False},
        "x_metric": "x",
        "y_metric": "y",
    }
    coverage_application = {
        "proposal_id": "coverage-probe",
        "mapped_outputs": [
            {
                "path": str(path.resolve()),
                "sha256": file_sha256(path),
            }
            for path in (coverage_source_a, coverage_source_b)
        ],
    }
    plural_snapshot_step = build_transform_step(
        step_id="coverage_plural_snapshot",
        operation="execute_confirmed_data_mapping_proposal",
        input_path=coverage_root,
        output_path=coverage_source_a,
        additional_outputs=[coverage_source_b],
        implementation_ref="sciplot_core.data_mapping.execute_data_mapping_proposal",
    )
    plural_snapshot_sources = _studio_snapshot_sources(
        None,
        project_dir=coverage_root,
        transform_ledger={"steps": [plural_snapshot_step]},
    )
    coverage_series = [
        StudioSeries(
            # Labels are intentionally non-injective. Path/hash provenance,
            # never a case-folded display label, is the coverage authority.
            label="sample",
            x_name=f"x_{index}",
            y_name=f"y_{index}",
            x_values=(0.0, 1.0),
            y_values=(
                (1.0, 2.0)
                if path == coverage_source_a
                else (3.0, 4.0)
            ),
            color="#000000",
            source_artifacts=(
                (str(path.resolve()), file_sha256(path)),
            ),
        )
        for index, path in enumerate(
            (coverage_source_a, coverage_source_b),
            start=1,
        )
    ]
    complete_coverage = _mapping_series_coverage(
        coverage_series,
        mapping_application=coverage_application,
        request={"template": "curve"},
    )
    incomplete_coverage_rejected = _raises_value_error(
        lambda: _mapping_series_coverage(
            coverage_series[:1],
            mapping_application=coverage_application,
            request={"template": "curve"},
        )
    )
    coverage_source_extra = coverage_root / "attacker.csv"
    pd.DataFrame({"x": [0.0, 1.0], "y": [8.0, 9.0]}).to_csv(
        coverage_source_extra,
        index=False,
    )
    unexpected_coverage_rejected = _raises_value_error(
        lambda: _mapping_series_coverage(
            [
                *coverage_series,
                StudioSeries(
                    label="sample",
                    x_name="x_extra",
                    y_name="y_extra",
                    x_values=(0.0, 1.0),
                    y_values=(8.0, 9.0),
                    color="#000000",
                    source_artifacts=(
                        (
                            str(coverage_source_extra.resolve()),
                            file_sha256(coverage_source_extra),
                        ),
                    ),
                ),
            ],
            mapping_application=coverage_application,
            request={"template": "curve"},
        )
    )
    coverage_render_frames = []
    for path in (coverage_source_a, coverage_source_b):
        coverage_render_frames.extend(
            _read_source_frame_records(path, request=coverage_request)
        )
    coverage_render_series, coverage_render_axis_info = (
        _series_from_frame_records(
            coverage_request,
            frames=coverage_render_frames,
        )
    )
    coverage_document_path = coverage_root / "document.vsz"
    coverage_spec_path = _write_veusz_document(
        coverage_document_path,
        request=coverage_request,
        series=coverage_render_series,
        axis_info=coverage_render_axis_info,
    )
    coverage_result = {
        "veusz_specs": [str(coverage_spec_path)],
        "veusz_documents": [str(coverage_document_path)],
        "data_snapshot_sources": [
            str(coverage_source_a.resolve()),
            str(coverage_source_b.resolve()),
        ],
    }
    rendered_coverage = verify_rendered_mapping_source_coverage(
        coverage_result,
        mapping_application=coverage_application,
        request=coverage_request,
    )
    forged_request_root = coverage_root / "terminal_request_forgery"
    forged_request_root.mkdir(parents=True, exist_ok=True)
    forged_terminal_request = {
        **coverage_request,
        "y_metric": "y_alt",
    }
    forged_terminal_series, forged_terminal_axis_info = (
        _series_from_frame_records(
            forged_terminal_request,
            frames=coverage_render_frames,
        )
    )
    forged_terminal_document = forged_request_root / "document.vsz"
    forged_terminal_spec = _write_veusz_document(
        forged_terminal_document,
        request=forged_terminal_request,
        series=forged_terminal_series,
        axis_info=forged_terminal_axis_info,
    )
    forged_terminal_spec_payload = json.loads(
        forged_terminal_spec.read_text(encoding="utf-8")
    )
    coordinated_terminal_request_forgery_materialized = (
        forged_terminal_spec_payload["series"][0]["y_values"]
        == [11.0, 12.0]
        and forged_terminal_document.is_file()
    )
    coordinated_terminal_request_forgery_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            {
                **coverage_result,
                "veusz_specs": [str(forged_terminal_spec)],
                "veusz_documents": [str(forged_terminal_document)],
                "terminal_render_requests": [
                    {
                        "template": "curve",
                        "render_options": {"show_legend": False},
                        "x_metric": "x",
                        "y_metric": "y_alt",
                    }
                ],
            },
            mapping_application=coverage_application,
            request=coverage_request,
        )
    )
    original_spec_text = coverage_spec_path.read_text(encoding="utf-8")
    coverage_spec = json.loads(original_spec_text)
    coverage_spec["series"][1]["source_artifacts"] = list(
        coverage_spec["series"][0]["source_artifacts"]
    )
    coverage_spec_path.write_text(
        json.dumps(coverage_spec, indent=2),
        encoding="utf-8",
    )
    rendered_omission_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            coverage_result,
            mapping_application=coverage_application,
            request=coverage_request,
        )
    )
    coverage_spec_path.write_text(original_spec_text, encoding="utf-8")
    terminal_substitution_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            {
                **coverage_result,
                "data_snapshot_sources": [str(coverage_source_a.resolve())],
            },
            mapping_application=coverage_application,
            request=coverage_request,
        )
    )
    original_document_text = coverage_document_path.read_text(encoding="utf-8")
    mutated_document_text = original_document_text.replace(
        "2.000000e+00",
        "9.000000e+00",
        1,
    )
    document_mutation_materialized = (
        mutated_document_text != original_document_text
    )
    coverage_document_path.write_text(
        mutated_document_text,
        encoding="utf-8",
    )
    vsz_data_mismatch_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            coverage_result,
            mapping_application=coverage_application,
            request=coverage_request,
        )
    )
    coverage_document_path.write_text(
        original_document_text,
        encoding="utf-8",
    )
    style_edited_document_text = original_document_text.replace(
        "Set('Background/color', 'white')",
        "Set('Background/color', '#FDFDFD')",
        1,
    )
    style_edit_materialized = (
        style_edited_document_text != original_document_text
    )
    coverage_document_path.write_text(
        style_edited_document_text,
        encoding="utf-8",
    )
    try:
        style_only_coverage = verify_rendered_mapping_source_coverage(
            coverage_result,
            mapping_application=coverage_application,
            request=coverage_request,
        )
    except (OSError, RuntimeError, ValueError):
        style_only_edit_accepted = False
    else:
        style_only_edit_accepted = style_only_coverage.get("status") == "passed"
    finally:
        coverage_document_path.write_text(
            original_document_text,
            encoding="utf-8",
        )
    axis_label_document_text = (
        original_document_text
        + "\nTo('/page1/graph1/x')\n"
        + "Set('label', 'Misleading axis')\n"
        + "To('/')\n"
    )
    axis_label_mutation_materialized = (
        axis_label_document_text != original_document_text
    )
    coverage_document_path.write_text(
        axis_label_document_text,
        encoding="utf-8",
    )
    axis_label_mutation_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            coverage_result,
            mapping_application=coverage_application,
            request=coverage_request,
        )
    )
    coverage_document_path.write_text(
        original_document_text,
        encoding="utf-8",
    )
    axis_contract_mutation_commands = {
        "direction": "Set('direction', 'vertical')",
        "tick_format": "Set('TickLabels/format', '%.2f')",
        "minor_tick_count": "Set('MinorTicks/number', 9)",
        "minor_manual_ticks": (
            "Set('MinorTicks/manualTicks', [0.25, 0.75])"
        ),
        "x_tick_visibility": "Set('TickLabels/hide', True)",
        "axis_label_visibility": "Set('Label/hide', True)",
    }
    axis_contract_mutation_results: dict[str, bool] = {}
    for mutation_id, command in axis_contract_mutation_commands.items():
        coverage_document_path.write_text(
            original_document_text
            + "\nTo('/page1/graph1/x')\n"
            + command
            + "\nTo('/')\n",
            encoding="utf-8",
        )
        axis_contract_mutation_results[mutation_id] = _raises_value_error(
            lambda: verify_rendered_mapping_source_coverage(
                coverage_result,
                mapping_application=coverage_application,
                request=coverage_request,
            )
        )
    coverage_document_path.write_text(
        original_document_text,
        encoding="utf-8",
    )

    coordinated_axis_spec = json.loads(original_spec_text)
    coordinated_axis_spec["axes"]["x"]["label"] = "Misleading axis"
    coverage_spec_path.write_text(
        json.dumps(coordinated_axis_spec, indent=2),
        encoding="utf-8",
    )
    coverage_document_path.write_text(
        axis_label_document_text,
        encoding="utf-8",
    )
    coordinated_axis_forgery_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            coverage_result,
            mapping_application=coverage_application,
            request=coverage_request,
        )
    )
    coverage_spec_path.write_text(original_spec_text, encoding="utf-8")
    coverage_document_path.write_text(
        original_document_text,
        encoding="utf-8",
    )

    arbitrary_label_document_text = (
        original_document_text
        + "\nTo('/page1/graph1')\n"
        + "Add('label', name='attacker_label', autoadd=False)\n"
        + "To('attacker_label')\n"
        + "Set('positioning', 'relative')\n"
        + "Set('xPos', [0.5])\n"
        + "Set('yPos', [0.5])\n"
        + "Set('label', 'Sample A is Sample B')\n"
        + "To('/')\n"
    )
    arbitrary_label_materialized = (
        arbitrary_label_document_text != original_document_text
    )
    coverage_document_path.write_text(
        arbitrary_label_document_text,
        encoding="utf-8",
    )
    arbitrary_visible_label_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            coverage_result,
            mapping_application=coverage_application,
            request=coverage_request,
        )
    )
    coverage_document_path.write_text(
        original_document_text,
        encoding="utf-8",
    )

    reordered_spec = json.loads(original_spec_text)
    reordered_spec["series"] = list(reversed(reordered_spec["series"]))
    coverage_spec_path.write_text(
        json.dumps(reordered_spec, indent=2),
        encoding="utf-8",
    )
    _save_veusz_document_from_spec(
        coverage_document_path,
        reordered_spec,
        spec_path=coverage_spec_path,
    )
    series_order_forgery_materialized = [
        item["name"] for item in reordered_spec["series"]
    ] == ["series_2", "series_1"]
    coordinated_series_order_forgery_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            coverage_result,
            mapping_application=coverage_application,
            request=coverage_request,
        )
    )
    coverage_spec_path.write_text(original_spec_text, encoding="utf-8")
    coverage_document_path.write_text(
        original_document_text,
        encoding="utf-8",
    )

    extra_curve_document_text = (
        original_document_text
        + "\nImportString('attacker_x(numeric)','''\\n0\\n1\\n''')\n"
        + "ImportString('attacker_y(numeric)','''\\n8\\n9\\n''')\n"
        + "To('/page1/graph1')\n"
        + "Add('xy', name='attacker_series', autoadd=False)\n"
        + "To('attacker_series')\n"
        + "Set('xData', 'attacker_x')\n"
        + "Set('yData', 'attacker_y')\n"
        + "Set('marker', 'circle')\n"
        + "To('..')\n"
    )
    coverage_document_path.write_text(
        extra_curve_document_text,
        encoding="utf-8",
    )
    try:
        verify_rendered_mapping_source_coverage(
            coverage_result,
            mapping_application=coverage_application,
            request=coverage_request,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        extra_curve_rejected = any(
            message in str(exc).casefold()
            for message in (
                "unapproved visible xy data binding",
                "xy object and legend-key order differs",
            )
        )
    else:
        extra_curve_rejected = False
    finally:
        coverage_document_path.write_text(
            original_document_text,
            encoding="utf-8",
        )
    extra_precision_document_text = original_document_text.replace(
        "1.000000e+00",
        "1.0000004e+00",
        1,
    )
    extra_precision_materialized = (
        extra_precision_document_text != original_document_text
    )
    coverage_document_path.write_text(
        extra_precision_document_text,
        encoding="utf-8",
    )
    extra_precision_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            coverage_result,
            mapping_application=coverage_application,
            request=coverage_request,
        )
    )
    coverage_document_path.write_text(
        original_document_text,
        encoding="utf-8",
    )

    forged_spec = json.loads(original_spec_text)
    forged_series = forged_spec["series"][0]
    forged_y_name = str(forged_series["y_name"])
    original_forged_value = float(forged_series["y_values"][0])
    replacement_forged_value = original_forged_value + 8.0
    forged_series["y_values"][0] = replacement_forged_value
    dataset_marker = f"ImportString('{forged_y_name}(numeric)','''"
    dataset_start = original_document_text.find(dataset_marker)
    dataset_end = original_document_text.find("''')", dataset_start)
    forged_document_text = original_document_text
    if dataset_start >= 0 and dataset_end > dataset_start:
        dataset_block = original_document_text[dataset_start:dataset_end]
        forged_block = dataset_block.replace(
            f"{original_forged_value:.6e}",
            f"{replacement_forged_value:.6e}",
            1,
        )
        forged_document_text = (
            original_document_text[:dataset_start]
            + forged_block
            + original_document_text[dataset_end:]
        )
    coordinated_forgery_materialized = (
        forged_document_text != original_document_text
    )
    coverage_spec_path.write_text(
        json.dumps(forged_spec, indent=2),
        encoding="utf-8",
    )
    coverage_document_path.write_text(
        forged_document_text,
        encoding="utf-8",
    )
    coordinated_spec_vsz_forgery_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            coverage_result,
            mapping_application=coverage_application,
            request=coverage_request,
        )
    )
    coverage_spec_path.write_text(original_spec_text, encoding="utf-8")
    coverage_document_path.write_text(
        original_document_text,
        encoding="utf-8",
    )

    invisible_series_document_text = (
        original_document_text
        + "\nTo('/page1/graph1/series_1')\n"
        + "Set('PlotLine/hide', True)\n"
        + "Set('marker', 'none')\n"
        + "Set('MarkerFill/hide', True)\n"
        + "Set('MarkerLine/hide', True)\n"
        + "Set('FillBelow/hide', True)\n"
        + "Set('FillAbove/hide', True)\n"
        + "To('/')\n"
    )
    coverage_document_path.write_text(
        invisible_series_document_text,
        encoding="utf-8",
    )
    invisible_series_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            coverage_result,
            mapping_application=coverage_application,
            request=coverage_request,
        )
    )
    coverage_document_path.write_text(
        original_document_text,
        encoding="utf-8",
    )

    extra_function_document_text = (
        original_document_text
        + "\nTo('/page1/graph1')\n"
        + "Add('function', name='attacker_function', autoadd=False)\n"
        + "To('attacker_function')\n"
        + "Set('function', 'x')\n"
        + "To('/')\n"
    )
    coverage_document_path.write_text(
        extra_function_document_text,
        encoding="utf-8",
    )
    extra_data_widget_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            coverage_result,
            mapping_application=coverage_application,
            request=coverage_request,
        )
    )
    coverage_document_path.write_text(
        original_document_text,
        encoding="utf-8",
    )

    import sciplot_core.source_coverage as source_coverage_module

    real_subprocess_run = source_coverage_module.subprocess.run

    def mutate_original_during_private_audit(*args: Any, **kwargs: Any) -> Any:
        coverage_document_path.write_text(
            original_document_text + "\n# concurrent mutation\n",
            encoding="utf-8",
        )
        return real_subprocess_run(*args, **kwargs)

    try:
        with patch(
            "sciplot_core.source_coverage.subprocess.run",
            side_effect=mutate_original_during_private_audit,
        ):
            audit_race_rejected = _raises_value_error(
                lambda: verify_rendered_mapping_source_coverage(
                    coverage_result,
                    mapping_application=coverage_application,
                    request=coverage_request,
                )
            )
    finally:
        coverage_document_path.write_text(
            original_document_text,
            encoding="utf-8",
        )

    import sciplot_core.studio as studio_module

    real_terminal_derivation = (
        studio_module.derive_terminal_render_data_contract
    )
    original_terminal_text = coverage_source_a.read_text(encoding="utf-8")
    swapped_terminal_text = original_terminal_text.replace(
        "1.0",
        "91.0",
        1,
    )
    terminal_derivation_used_private_snapshots = False

    def swap_original_during_terminal_derivation(
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        nonlocal terminal_derivation_used_private_snapshots
        terminal_sources = kwargs.get("terminal_sources")
        terminal_derivation_used_private_snapshots = (
            isinstance(terminal_sources, list)
            and bool(terminal_sources)
            and all(
                Path(path).resolve()
                not in {
                    coverage_source_a.resolve(),
                    coverage_source_b.resolve(),
                }
                for path in terminal_sources
            )
        )
        coverage_source_a.write_text(
            swapped_terminal_text,
            encoding="utf-8",
        )
        try:
            return real_terminal_derivation(*args, **kwargs)
        finally:
            coverage_source_a.write_text(
                original_terminal_text,
                encoding="utf-8",
            )

    terminal_swap_error: str | None = None
    terminal_swap_status: str | None = None
    try:
        with patch(
            "sciplot_core.studio.derive_terminal_render_data_contract",
            side_effect=swap_original_during_terminal_derivation,
        ):
            terminal_swap_coverage = verify_rendered_mapping_source_coverage(
                coverage_result,
            mapping_application=coverage_application,
            request=coverage_request,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        terminal_swap_error = f"{type(exc).__name__}: {exc}"
        terminal_swap_race_rejected = (
            "changed during exact-current audit" in str(exc)
        )
    else:
        terminal_swap_status = str(terminal_swap_coverage.get("status"))
        terminal_swap_race_rejected = False
    finally:
        coverage_source_a.write_text(
            original_terminal_text,
            encoding="utf-8",
        )
    terminal_swap_restored = (
        coverage_source_a.read_text(encoding="utf-8")
        == original_terminal_text
    )

    categorical_root = coverage_root / "categorical"
    categorical_root.mkdir(parents=True, exist_ok=True)
    categorical_source = categorical_root / "impact.csv"
    pd.DataFrame(
        {
            "Impact strength": ["kJ/m2", "A", 10.0, 11.0, 12.0],
            "Impact strength.1": ["kJ/m2", "B", 20.0, 21.0, 22.0],
        }
    ).to_csv(categorical_source, index=False)
    categorical_request = {
        "template": "box",
        "render_options": {
            "show_legend": False,
            "summary_statistic": "median_iqr",
        },
    }
    categorical_series, categorical_axis_info = _series_from_frame_records(
        categorical_request,
        frames=_read_source_frame_records(
            categorical_source,
            request=categorical_request,
        ),
    )
    categorical_document = categorical_root / "document.vsz"
    categorical_spec = _write_veusz_document(
        categorical_document,
        request=categorical_request,
        series=categorical_series,
        axis_info=categorical_axis_info,
    )
    categorical_application = {
        "proposal_id": "categorical-coverage-probe",
        "mapped_outputs": [
            {
                "path": str(categorical_source.resolve()),
                "sha256": file_sha256(categorical_source),
            }
        ],
    }
    categorical_result = {
        "veusz_specs": [str(categorical_spec)],
        "veusz_documents": [str(categorical_document)],
        "data_snapshot_source": str(categorical_source.resolve()),
    }
    categorical_baseline = verify_rendered_mapping_source_coverage(
        categorical_result,
        mapping_application=categorical_application,
        request=categorical_request,
    )
    categorical_document_text = categorical_document.read_text(
        encoding="utf-8"
    )
    categorical_spec_text = categorical_spec.read_text(encoding="utf-8")
    hidden_boxplot_commands = "\n".join(
        [
            f"To('/page1/graph1/categorical_boxplot_{index}')\n"
            "Set('Fill/hide', True)\n"
            "Set('Border/hide', True)\n"
            "Set('Whisker/hide', True)"
            for index in range(1, 3)
        ]
    )
    categorical_document.write_text(
        categorical_document_text
        + "\n"
        + hidden_boxplot_commands
        + "\nTo('/')\n",
        encoding="utf-8",
    )
    hidden_categorical_boxplots_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            categorical_result,
            mapping_application=categorical_application,
            request=categorical_request,
        )
    )
    categorical_document.write_text(
        categorical_document_text,
        encoding="utf-8",
    )
    forged_categorical_spec = json.loads(categorical_spec_text)
    forged_categorical_spec["series"][0]["label"] = "B"
    forged_categorical_spec["series"][1]["label"] = "A"
    forged_categorical_spec["categorical"]["groups"][0]["label"] = "B"
    forged_categorical_spec["categorical"]["groups"][1]["label"] = "A"
    forged_categorical_spec["axes"]["x"]["category_labels"] = ["B", "A"]
    forged_categorical_document = categorical_document_text.replace(
        "    'A',\n    'B',",
        "    'B',\n    'A',",
        1,
    )
    forged_categorical_document = forged_categorical_document.replace(
        "Set('key', 'A')",
        "Set('key', '__SCIPLOT_LABEL_SWAP__')",
        1,
    )
    forged_categorical_document = forged_categorical_document.replace(
        "Set('key', 'B')",
        "Set('key', 'A')",
        1,
    ).replace(
        "Set('key', '__SCIPLOT_LABEL_SWAP__')",
        "Set('key', 'B')",
        1,
    )
    coordinated_label_forgery_materialized = (
        forged_categorical_document != categorical_document_text
    )
    categorical_spec.write_text(
        json.dumps(forged_categorical_spec, indent=2),
        encoding="utf-8",
    )
    categorical_document.write_text(
        forged_categorical_document,
        encoding="utf-8",
    )
    coordinated_series_label_forgery_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            categorical_result,
            mapping_application=categorical_application,
            request=categorical_request,
        )
    )
    categorical_spec.write_text(categorical_spec_text, encoding="utf-8")
    categorical_document.write_text(
        categorical_document_text,
        encoding="utf-8",
    )

    split_root = coverage_root / "explicit_split"
    split_root.mkdir(parents=True, exist_ok=True)
    split_source = split_root / "stacked.csv"
    pd.DataFrame(
        [
            ["Time", "Signal", "Time", "Signal", "Time", "Signal"],
            ["s", "a.u.", "s", "a.u.", "s", "a.u."],
            ["A", "A", "B", "B", "C", "C"],
            [1.0, 1.0, 1.0, 2.0, 1.0, 3.0],
            [2.0, 1.5, 2.0, 2.5, 2.0, 3.5],
            [3.0, 2.0, 3.0, 3.0, 3.0, 4.0],
        ]
    ).to_csv(split_source, index=False, header=False)
    split_policy = {
        "mode": "series_chunks",
        "max_series_per_panel": 1,
        "preserve_shared_x_axis": True,
        "delivery": "multi_figure_same_metric",
        "trigger": "explicit_probe",
    }
    split_request = {
        "template": "stacked_curve",
        "render_options": {
            "baseline": "none",
            "show_legend": False,
        },
        "split_policy": split_policy,
    }
    split_result = render_to_dir(
        split_source,
        template="stacked_curve",
        output_dir=split_root / "rendered",
        options=split_request["render_options"],
        export_formats=("pdf",),
        split_policy=split_policy,
        request_context=split_request,
    )
    split_result["data_snapshot_source"] = str(split_source.resolve())
    split_application = {
        "proposal_id": "explicit-split-coverage-probe",
        "mapped_outputs": [
            {
                "path": str(split_source.resolve()),
                "sha256": file_sha256(split_source),
            }
        ],
    }
    explicit_split_coverage = verify_rendered_mapping_source_coverage(
        split_result,
        mapping_application=split_application,
        request=split_request,
    )
    tampered_split_result = json.loads(json.dumps(json_safe(split_result)))
    tampered_split_result["split_plan"]["chunks"][0]["series"] = ["C"]
    split_plan_tamper_rejected = _raises_value_error(
        lambda: verify_rendered_mapping_source_coverage(
            tampered_split_result,
            mapping_application=split_application,
            request=split_request,
        )
    )

    checks = [
        _check(
            "proposal_v2_roundtrip",
            "The closed DataMappingProposal v2 contract round-trips exactly",
            proposal_roundtrip.to_dict() == proposal.to_dict(),
        ),
        _check(
            "proposal_cannot_self_authorize",
            "A provider payload cannot mark its own proposal executable",
            proposal.executable is False and self_authorization_rejected,
        ),
        _check(
            "proposal_timestamp_is_hash_stable",
            "External proposal payloads must carry a stable timezone-aware creation timestamp",
            missing_proposal_timestamp_rejected,
        ),
        _check(
            "confirmation_timestamp_is_immutable",
            "External confirmation receipts must carry their original timezone-aware confirmation timestamp",
            missing_confirmation_timestamp_rejected,
        ),
        _check(
            "transformation_identity_is_hash_stable",
            "External transformations must carry stable IDs instead of receiving a new UUID on every parse",
            missing_transformation_id_rejected,
        ),
        _check(
            "source_paths_are_confined",
            "Source references cannot escape the declared immutable root",
            unsafe_path_rejected,
        ),
        _check(
            "transformation_schema_is_closed",
            "Declarative transformations reject executable or undeclared fields",
            executable_key_rejected,
        ),
        _check(
            "text_fields_are_strictly_typed",
            "Closed proposal fields reject booleans, numbers, and numeric strings instead of coercing them into text or comparator values",
            non_string_contract_fields_rejected,
        ),
        _check(
            "invalid_numeric_outputs_are_rejected",
            "Category-only, empty, or nonnumeric primary plotting outputs stop before confirmation",
            invalid_numeric_outputs_rejected,
        ),
        _check(
            "preview_is_zero_write",
            "Preview validates and executes in memory without changing the workspace",
            preview["writes_performed"] is False and preview_tree == initial_tree,
        ),
        _check(
            "preview_excludes_raw_values",
            "Preview exposes shape, columns, units, and transforms but no raw values",
            preview["raw_values_in_preview"] is False
            and not ({"values", "records", "data"} & set(preview["sources"][0])),
        ),
        _check(
            "confirmation_binds_proposal",
            "User confirmation binds the exact proposal, request, source hashes, and normalized read/write paths",
            confirmation.proposal_sha256 == result["proposal_sha256"]
            and confirmation.base_request_sha256 == proposal.base_request_sha256
            and confirmation.source_hashes == proposal.source_hashes
            and confirmation.source_root == str(source.resolve())
            and confirmation.request_path == str(request.resolve())
            and confirmation.output_root == str((root / "mappings").resolve()),
        ),
        _check(
            "confirmation_source_root_is_bound",
            "An identical source tree at another path cannot reuse the confirmation receipt",
            source_root_rebind_rejected,
        ),
        _check(
            "confirmation_request_path_is_bound",
            "Identical request bytes at another path cannot reuse the confirmation receipt",
            request_path_rebind_rejected,
        ),
        _check(
            "confirmation_output_root_is_bound",
            "A confirmed execution cannot be redirected to another write root",
            output_root_rebind_rejected and rebound_paths_zero_write,
        ),
        _check(
            "legacy_v1_confirmation_is_inspection_only",
            "A committed-format v1 receipt remains inspectable but cannot execute, render, or hand off",
            legacy_execution_inspectable
            and legacy_execution_rejected
            and legacy_handoff_rejected,
            {
                "fixture": str(legacy_fixture_path),
                "execution": legacy_execution,
            },
        ),
        _check(
            "legacy_v1_requires_explicit_v2_reconfirmation",
            "A fresh explicit v2 receipt restores normalized-path execution authority in a new output root",
            legacy_reconfirmation_restores_authority,
            {
                "legacy_confirmation_id": legacy_confirmation.confirmation_id,
                "current_confirmation_id": reconfirmed.confirmation_id,
                "execution": reconfirmed_execution,
            },
        ),
        _check(
            "forged_confirmation_rejected",
            "A mismatched confirmation receipt cannot authorize execution",
            forged_confirmation_rejected,
        ),
        _check(
            "stale_request_rejected",
            "Request edits invalidate proposal preview before any write",
            stale_request_rejected,
        ),
        _check(
            "source_tamper_rejected",
            "Raw source edits invalidate proposal preview before any write",
            source_tamper_rejected,
        ),
        _check(
            "explicit_exclusion_only",
            "Only the explicitly confirmed bad-quality row is removed",
            mapped.shape[0] == 3 and mapped["time_ms"].tolist() == [0.0, 1.0, 3.0],
        ),
        _check(
            "unit_conversion_is_deterministic",
            "The declared ms-to-s conversion is reproducible",
            mapped["time_ms"].tolist() == [0.0, 1.0, 3.0],
        ),
        _check(
            "ratio_derivation_is_deterministic",
            "The declared ratio is recomputed from mapped columns",
            mapped["ratio"].tolist() == [5.0, 4.0, 4.0],
        ),
        _check(
            "baseline_normalization_is_deterministic",
            "The declared first-finite baseline normalization is reproducible",
            mapped["signal_norm"].round(8).tolist() == [1.0, 1.2, 1.6],
        ),
        _check(
            "raw_source_is_immutable",
            "Successful execution leaves the original source byte-for-byte unchanged",
            file_sha256(primary_source) == primary_hash
            and result["raw_inputs_unchanged"] is True,
        ),
        _check(
            "execution_is_complete",
            "Atomic execution writes proposal, receipt, preview, confirmed base-request snapshot, seed, ledger, data, and candidate request",
            all(
                Path(path).exists()
                for path in (
                    result["proposal"],
                    result["confirmation"],
                    result["preview"],
                    result["transform_ledger"],
                    result["request_candidate"],
                    Path(result["output_root"]) / DATA_MAPPING_REQUEST_SEED_FILENAME,
                    Path(result["output_root"]) / DATA_MAPPING_BASE_REQUEST_FILENAME,
                    superseded_ledger_path,
                )
            ),
        ),
        _check(
            "base_request_snapshot_is_confirmed",
            "The transaction carries the exact base-request bytes anchored by the proposal and confirmation hash",
            file_sha256(
                Path(result["output_root"]) / DATA_MAPPING_BASE_REQUEST_FILENAME
            )
            == proposal.base_request_sha256
            == result["base_request_snapshot_sha256"],
        ),
        _check(
            "candidate_preserves_raw_input",
            "The mapped request retains raw input authority and references the verified execution separately",
            candidate["input"] == str(source)
            and candidate["data_mapping_execution"]
            == str(Path(result["output_root"]) / "execution.json"),
        ),
        _check(
            "candidate_is_standard_project_entrypoint",
            "The isolated mapping transaction exposes the canonical project request name for Studio lifecycle commands",
            Path(result["request_candidate"]).name == "plot_request.json",
        ),
        _check(
            "ledger_records_mapping",
            "The candidate transform ledger records the confirmed mapping and no false identity step",
            [step.get("operation") for step in candidate["transform_ledger"]["steps"]]
            == ["execute_confirmed_data_mapping_proposal"]
            and all(
                step.get("id") != "identity_source"
                for step in candidate["transform_ledger"]["steps"]
            ),
        ),
        _check(
            "prior_ledger_is_archived_not_activated",
            "A previous branch ledger is hash-preserved as superseded evidence and cannot appear before the new mapping step",
            result.get("superseded_base_transform_ledger")
            == str(superseded_ledger_path)
            and [step.get("operation") for step in superseded_ledger.get("steps", [])]
            == ["legacy_semantic_preparation"],
        ),
        _check(
            "execution_is_idempotent",
            "Repeating the same confirmed execution reuses the verified result",
            execution_reuse.get("idempotent_reuse") is True
            and execution_reuse["proposal_sha256"] == result["proposal_sha256"],
        ),
        _check(
            "candidate_can_evolve",
            "Studio may enrich the working request without invalidating the immutable request seed",
            evolving_candidate_valid,
        ),
        _check(
            "candidate_raw_authority_is_immutable",
            "A mutable working request cannot relabel another path as the confirmed mapping's raw input authority",
            raw_authority_tamper_rejected,
        ),
        _check(
            "candidate_proposal_identity_is_immutable",
            "A mutable working request cannot detach itself from the proposal ID bound by its execution",
            proposal_identity_tamper_rejected,
        ),
        _check(
            "output_tamper_is_rejected",
            "Mapped output hash changes are rejected before consumption",
            output_tamper_rejected,
        ),
        _check(
            "request_seed_tamper_is_rejected",
            "The immutable request seed remains hash-verified",
            seed_tamper_rejected,
        ),
        _check(
            "coordinated_seed_tamper_is_rejected",
            "Changing raw authority in both the seed and its manifest hashes is rejected against the confirmed base-request snapshot",
            coordinated_seed_tamper_rejected,
        ),
        _check(
            "superseded_ledger_tamper_is_rejected",
            "Archived base lineage remains hash-verified even though it is not active in the new branch",
            superseded_ledger_tamper_rejected,
        ),
        _check(
            "coordinated_superseded_redirect_is_rejected",
            "Changing the archived-ledger path together with its hashes and seed link cannot redirect confirmed lineage",
            coordinated_superseded_redirect_rejected,
        ),
        _check(
            "active_ledger_tamper_is_rejected",
            "The active confirmed mapping lineage is hash-verified before consumption",
            active_ledger_tamper_rejected,
        ),
        _check(
            "coordinated_lineage_tamper_is_rejected",
            "Changing active lineage together with manifest and seed hashes is rejected against the confirmed proposal",
            coordinated_lineage_tamper_rejected,
        ),
        _check(
            "manifest_request_patch_tamper_is_rejected",
            "An execution manifest cannot silently change the confirmed scientific request patch",
            manifest_request_patch_tamper_rejected,
        ),
        _check(
            "manifest_effective_input_tamper_is_rejected",
            "An execution manifest cannot redirect rendering away from deterministic mapped outputs",
            manifest_effective_input_tamper_rejected,
        ),
        _check(
            "replicate_aggregation_is_explicit",
            "Confirmed replicate aggregation records arithmetic means and counts",
            aggregate_frame.to_dict(orient="records")
            == [
                {"sample": "A", "x": 0, "value": 2, "n": 2},
                {"sample": "A", "x": 1, "value": 6, "n": 2},
            ],
        ),
        _check(
            "decimal_comma_is_deterministic",
            "Declared comma-decimal numeric columns are normalized without changing semicolon-delimited structure",
            decimal_frame.to_dict(orient="records")
            == [
                {"x": 1.25, "y": 2.5},
                {"x": 2.5, "y": 5.0},
                {"x": 10.0, "y": 20.0},
            ],
        ),
        _check(
            "partial_execution_is_cleaned",
            "Injected multi-output failure leaves neither a final result nor a temporary transaction",
            atomic_failure_rejected and atomic_final_absent and atomic_temps_absent,
        ),
        _check(
            "case_insensitive_output_names_do_not_collide",
            "Mapped sources whose labels differ only by case receive distinct deterministic filenames on macOS",
            len(collision_output_names) == 2
            and len({name.casefold() for name in collision_output_names}) == 2,
            {"output_names": collision_output_names},
        ),
        _check(
            "ledger_merges_prior_and_runtime_steps",
            "Callers record mapping and later deterministic semantic preparation as one explicit causal chain",
            merged_ids == ["mapping_step", "semantic_step"],
            {"step_ids": merged_ids},
        ),
        _check(
            "request_only_project_has_complete_semantics",
            "A standard mapping project recovers complete axis and analysis semantics from its persisted rule without an intake manifest",
            request_only_semantic.get("rule_id") == "ftir_spectrum"
            and set(request_only_semantic.get("axis_plan") or {}) == {"x", "y"}
            and isinstance(request_only_semantic.get("analysis_plan"), list),
        ),
        _check(
            "numeric_sample_labels_survive_unit_rows",
            "Numeric-looking sample IDs remain labels when a semantic table stores unit metadata first",
            numeric_sample_label == "8",
        ),
        _check(
            "unit_like_sample_labels_survive_unit_rows",
            "Sample labels such as PA remain labels even when their case-folded spelling matches the following Pa unit",
            unit_like_sample_label == "PA",
        ),
        _check(
            "numeric_sample_labels_never_become_data",
            "Unit and sample metadata rows are excluded from numeric curve values",
            numeric_sample_frame.to_dict(orient="records")
            == [
                {
                    "Elution time": 14.5,
                    "Detector response": 0.1,
                },
                {
                    "Elution time": 15.0,
                    "Detector response": 0.2,
                },
            ],
        ),
        _check(
            "ordinary_leading_ones_are_preserved",
            "Ordinary numeric data beginning with dimensionless ones is not mistaken for a unit metadata prefix",
            ordinary_numeric_frame.to_dict(orient="records")
            == [
                {"x": 1.0, "y": 1.0},
                {"x": 2.0, "y": 4.0},
                {"x": 3.0, "y": 9.0},
            ],
        ),
        _check(
            "ambiguous_metadata_roles_fail_closed",
            "Two unit-like metadata rows stop instead of guessing which row contains sample labels",
            ambiguous_metadata_roles_rejected,
        ),
        _check(
            "series_selection_fails_closed",
            "Unknown or fully hidden series selections stop instead of silently restoring every curve",
            unknown_series_include_rejected and all_series_hidden_rejected,
        ),
        _check(
            "duplicate_label_routing_fails_closed",
            "Duplicate display labels cannot overwrite label-based series selection or split-panel routing",
            duplicate_series_label_rejected
            and duplicate_split_label_rejected,
            {
                "series_selection_rejected": (
                    duplicate_series_label_rejected
                ),
                "split_plan_rejected": duplicate_split_label_rejected,
            },
        ),
        _check(
            "mapped_series_coverage_is_enforced",
            "Studio independently rederives terminal data, audits private exact-current VSZ snapshots, and requires real visible consumers",
            complete_coverage.get("status") == "passed"
            and complete_coverage.get("coverage_mode") == "exact_per_output"
            and plural_snapshot_sources
            == [
                coverage_source_a.resolve(),
                coverage_source_b.resolve(),
            ]
            and incomplete_coverage_rejected
            and unexpected_coverage_rejected
            and rendered_coverage.get("coverage_mode") == "exact_per_output"
            and rendered_coverage.get("terminal_output_count") == 2
            and rendered_coverage.get("document_count") == 1
            and coordinated_terminal_request_forgery_materialized
            and coordinated_terminal_request_forgery_rejected
            and rendered_omission_rejected
            and terminal_substitution_rejected
            and document_mutation_materialized
            and vsz_data_mismatch_rejected
            and style_edit_materialized
            and style_only_edit_accepted
            and axis_label_mutation_materialized
            and axis_label_mutation_rejected
            and all(axis_contract_mutation_results.values())
            and coordinated_axis_forgery_rejected
            and arbitrary_label_materialized
            and arbitrary_visible_label_rejected
            and series_order_forgery_materialized
            and coordinated_series_order_forgery_rejected
            and extra_curve_rejected
            and extra_precision_materialized
            and extra_precision_rejected
            and coordinated_forgery_materialized
            and coordinated_spec_vsz_forgery_rejected
            and invisible_series_rejected
            and extra_data_widget_rejected
            and audit_race_rejected
            and terminal_derivation_used_private_snapshots
            and terminal_swap_race_rejected
            and terminal_swap_restored
            and reserved_terminal_flag_rejected
            and categorical_baseline.get("status") == "passed"
            and hidden_categorical_boxplots_rejected
            and coordinated_label_forgery_materialized
            and coordinated_series_label_forgery_rejected
            and explicit_split_coverage.get("status") == "passed"
            and explicit_split_coverage.get("document_count") == 3
            and split_plan_tamper_rejected,
            {
                "complete_coverage": complete_coverage.get("status")
                == "passed",
                "exact_per_output": complete_coverage.get("coverage_mode")
                == "exact_per_output",
                "plural_snapshot_sources": plural_snapshot_sources
                == [
                    coverage_source_a.resolve(),
                    coverage_source_b.resolve(),
                ],
                "incomplete_coverage_rejected": (
                    incomplete_coverage_rejected
                ),
                "unexpected_coverage_rejected": (
                    unexpected_coverage_rejected
                ),
                "rendered_coverage": rendered_coverage.get("coverage_mode")
                == "exact_per_output",
                "terminal_output_count": (
                    rendered_coverage.get("terminal_output_count") == 2
                ),
                "document_count": (
                    rendered_coverage.get("document_count") == 1
                ),
                "coordinated_terminal_request_forgery_materialized": (
                    coordinated_terminal_request_forgery_materialized
                ),
                "coordinated_terminal_request_forgery_rejected": (
                    coordinated_terminal_request_forgery_rejected
                ),
                "rendered_omission_rejected": rendered_omission_rejected,
                "terminal_substitution_rejected": (
                    terminal_substitution_rejected
                ),
                "document_mutation_materialized": (
                    document_mutation_materialized
                ),
                "vsz_data_mismatch_rejected": vsz_data_mismatch_rejected,
                "style_edit_materialized": style_edit_materialized,
                "style_only_edit_accepted": style_only_edit_accepted,
                "axis_label_mutation_materialized": (
                    axis_label_mutation_materialized
                ),
                "axis_label_mutation_rejected": (
                    axis_label_mutation_rejected
                ),
                "axis_contract_mutation_results": (
                    axis_contract_mutation_results
                ),
                "coordinated_axis_forgery_rejected": (
                    coordinated_axis_forgery_rejected
                ),
                "arbitrary_label_materialized": (
                    arbitrary_label_materialized
                ),
                "arbitrary_visible_label_rejected": (
                    arbitrary_visible_label_rejected
                ),
                "series_order_forgery_materialized": (
                    series_order_forgery_materialized
                ),
                "coordinated_series_order_forgery_rejected": (
                    coordinated_series_order_forgery_rejected
                ),
                "extra_curve_rejected": extra_curve_rejected,
                "extra_precision_materialized": (
                    extra_precision_materialized
                ),
                "extra_precision_rejected": extra_precision_rejected,
                "coordinated_forgery_materialized": (
                    coordinated_forgery_materialized
                ),
                "coordinated_spec_vsz_forgery_rejected": (
                    coordinated_spec_vsz_forgery_rejected
                ),
                "invisible_series_rejected": invisible_series_rejected,
                "extra_data_widget_rejected": extra_data_widget_rejected,
                "audit_race_rejected": audit_race_rejected,
                "terminal_derivation_used_private_snapshots": (
                    terminal_derivation_used_private_snapshots
                ),
                "terminal_swap_race_rejected": terminal_swap_race_rejected,
                "terminal_swap_restored": terminal_swap_restored,
                "terminal_swap_status": terminal_swap_status,
                "terminal_swap_error": terminal_swap_error,
                "reserved_terminal_flag_rejected": (
                    reserved_terminal_flag_rejected
                ),
                "categorical_baseline": (
                    categorical_baseline.get("status") == "passed"
                ),
                "hidden_categorical_boxplots_rejected": (
                    hidden_categorical_boxplots_rejected
                ),
                "coordinated_label_forgery_materialized": (
                    coordinated_label_forgery_materialized
                ),
                "coordinated_series_label_forgery_rejected": (
                    coordinated_series_label_forgery_rejected
                ),
                "explicit_split_coverage": (
                    explicit_split_coverage.get("status") == "passed"
                ),
                "explicit_split_document_count": (
                    explicit_split_coverage.get("document_count") == 3
                ),
                "split_plan_tamper_rejected": split_plan_tamper_rejected,
            },
        ),
    ]
    failed = [check["id"] for check in checks if check["status"] != "passed"]
    payload = {
        "kind": "sciplot_data_mapping_probe",
        "version": 1,
        "status": "passed" if not failed else "failed",
        "summary": {
            "check_count": len(checks),
            "passed_count": len(checks) - len(failed),
            "failed_ids": failed,
        },
        "checks": checks,
        "artifacts": {
            "root": str(root),
            "execution": str(Path(result["output_root"]) / "execution.json"),
            "request_candidate": result["request_candidate"],
            "aggregate_execution": str(
                Path(aggregate_result["output_root"]) / "execution.json"
            ),
            "summary": str(root / "data_mapping_probe.json"),
        },
        "limitations": [
            "This probe uses synthetic contract fixtures and does not count as authorized real-data evidence.",
            "It validates deterministic execution, not AI scientific interpretation quality.",
        ],
    }
    _summary_path = root / "data_mapping_probe.json"
    _summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


__all__ = ["run_data_mapping_probe"]
