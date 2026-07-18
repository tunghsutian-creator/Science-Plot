from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Callable
from uuid import uuid4

from sciplot_core.canvas.operations import CanvasOperationBatch
from sciplot_core.canvas.persistence import load_canvas_session
from sciplot_core.data_mapping import (
    create_data_mapping_confirmation,
    execute_data_mapping_proposal,
    load_data_mapping_execution,
    load_data_mapping_proposal,
)
from sciplot_core._utils import file_sha256
from sciplot_core import promotion as promotion_module
from sciplot_core.promotion import (
    OWNER_DECISION_ATTESTATION,
    PROMOTION_DECISION_RECEIPT_KIND,
    PROMOTION_SIGNATURE_ALGORITHM,
    PROMOTION_TRUST_REGISTRY_KIND,
    PROMOTION_VERIFICATION_RECEIPT_KIND,
    VERIFICATION_ATTESTATION,
    _bind_artifact,
    _batch_matches_final_document,
    _batch_was_later_superseded,
    _candidate_rows,
    _clean_git_state,
    _decide_promotion_candidate,
    _git,
    _git_environment,
    _load_owner_decision_receipt,
    _load_plan_decision_snapshot,
    _load_verification_receipt,
    _promotion_observation_exclusion_reason,
    _protected_registry_snapshot,
    _session_records,
    _trusted_git_executable,
    _validate_candidate_specific_contract,
    _validate_implementation_contract,
    _validate_decision_state_binding,
    _verify_lifecycle_assertions,
    _verify_probe_artifacts,
    _verify_signed_session_reference,
    build_promotion_candidates,
    build_promotion_session_binding,
    canonicalize_canvas_batch,
    canonicalize_data_mapping_execution,
    collect_promotion_observations,
    promotion_schema,
    promotion_status,
)
from sciplot_core.session_evidence import (
    canonical_sha256,
    session_evidence_schema,
    verified_session_evidence_snapshot,
)
from sciplot_core.session_evidence_artifacts import artifact_content_record

def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _generate_probe_key() -> tuple[BinaryIO, str]:
    private_key: BinaryIO | None = None
    try:
        generated = subprocess.run(
            ["/usr/bin/openssl", "genrsa", "2048"],
            check=False,
            capture_output=True,
        )
        if generated.returncode != 0:
            raise ValueError(
                "Synthetic probe RSA generation failed: "
                f"{generated.stderr.decode('utf-8', errors='replace').strip()}"
            )
        private_key = tempfile.TemporaryFile(mode="w+b")
        os.fchmod(private_key.fileno(), 0o600)
        private_key.write(generated.stdout)
        private_key.flush()
        private_key.seek(0)
        modulus_result = subprocess.run(
            [
                "/usr/bin/openssl",
                "rsa",
                "-in",
                f"/dev/fd/{private_key.fileno()}",
                "-noout",
                "-modulus",
            ],
            check=False,
            capture_output=True,
            text=True,
            pass_fds=(private_key.fileno(),),
        )
        if modulus_result.returncode != 0:
            raise ValueError(
                "Synthetic probe RSA inspection failed: "
                f"{modulus_result.stderr.strip()}"
            )
        prefix, separator, modulus = modulus_result.stdout.strip().partition("=")
        if prefix != "Modulus" or not separator or not modulus:
            raise ValueError("Synthetic probe RSA modulus output is malformed.")
        private_key.seek(0)
        return private_key, modulus.casefold()
    except BaseException:
        if private_key is not None:
            private_key.close()
        raise


def _sign_probe_receipt(
    payload: dict[str, Any],
    key_id: str,
    *,
    private_key: BinaryIO,
) -> dict[str, Any]:
    signed = dict(payload)
    signed["owner_key_id"] = key_id
    signed["signature_algorithm"] = PROMOTION_SIGNATURE_ALGORITHM
    private_key.seek(0)
    result = subprocess.run(
        [
            "/usr/bin/openssl",
            "dgst",
            "-sha256",
            "-sign",
            f"/dev/fd/{private_key.fileno()}",
        ],
        input=_canonical_bytes(signed),
        check=False,
        capture_output=True,
        pass_fds=(private_key.fileno(),),
    )
    if result.returncode != 0:
        raise ValueError(
            "Synthetic probe receipt signing failed: "
            f"{result.stderr.decode('utf-8', errors='replace').strip()}"
        )
    signature = result.stdout
    signed["signature"] = base64.b64encode(signature).decode("ascii")
    return signed


def _check(
    check_id: str,
    label: str,
    passed: bool,
    *,
    detail: Any = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": detail,
    }


def _expect_failure(
    operation: Callable[[], object],
    *needles: str,
) -> tuple[bool, str | None]:
    try:
        operation()
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        return all(needle.casefold() in message.casefold() for needle in needles), (
            message
        )
    return False, None


def _simulated_observation(
    *,
    decision: dict[str, Any],
    session_id: str,
    task_fingerprint: str,
    eligible: bool,
    owner: str = "simulated_contract_owner",
) -> dict[str, Any]:
    decision_hash = canonical_sha256(decision)
    observation_id = canonical_sha256(
        {
            "simulated_contract_fixture": True,
            "session_id": session_id,
            "task_fingerprint": task_fingerprint,
            "decision_sha256": decision_hash,
        }
    )
    return {
        "observation_id": observation_id,
        "decision_kind": decision["decision_kind"],
        "canonical_decision": decision,
        "canonical_decision_sha256": decision_hash,
        "evidence": {
            "ledger_sha256": canonical_sha256(
                {"simulated_ledger": session_id}
            ),
            "session_id": session_id,
            "task_fingerprint": task_fingerprint,
            "lane": "simulated_contract_lane",
            "owner_attestation_sha256": hashlib.sha256(
                owner.encode("utf-8")
            ).hexdigest(),
        },
        "artifact_sha256": canonical_sha256(
            {"simulated_artifact": session_id}
        ),
        "eligible_for_threshold": eligible,
    }


def _find_committed_batch(
    canvas_project: Path,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    project = canvas_project.expanduser().resolve()
    journal = project / ".sciplot_canvas" / "operation_journal.jsonl"
    session_path = project / ".sciplot_canvas" / "canvas_session.json"
    for line in journal.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if (
            entry.get("event") == "assistant_batch_applied"
            and isinstance(entry.get("batch"), dict)
        ):
            batch = CanvasOperationBatch.from_dict(entry["batch"])
            if any(
                operation.operation_type == "set_setting"
                for operation in batch.operations
            ):
                return entry, entry["batch"], session_path
    raise ValueError("Canvas probe project lacks an applied Assistant batch.")


def run_promotion_probe(
    *,
    output_root: Path,
    synthetic_session_ledger: Path,
    mapping_execution: Path,
    canvas_project: Path,
) -> dict[str, Any]:
    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="promotion_probe_", dir=resolved_output)
    )
    summary_path = run_root / "promotion_probe.json"
    collection_path = run_root / "collection.json"
    candidates_path = run_root / "candidates.json"
    trust_registry_path = run_root / "trusted_promotion_owners.json"
    checks: list[dict[str, Any]] = []
    error: dict[str, str] | None = None
    probe_private_key: BinaryIO | None = None

    try:
        probe_private_key, probe_modulus_hex = _generate_probe_key()
        public_key = {
            "signature_algorithm": PROMOTION_SIGNATURE_ALGORITHM,
            "modulus_hex": probe_modulus_hex,
            "exponent": 65537,
        }
        owner_key_id = canonical_sha256(public_key)
        trust_registry = {
            "kind": PROMOTION_TRUST_REGISTRY_KIND,
            "version": 1,
            "owners": [
                {
                    "owner": "simulated_contract_owner",
                    "key_id": owner_key_id,
                    **public_key,
                    "public_key_sha256": owner_key_id,
                    "state": "active",
                }
            ],
        }
        trust_registry_path.write_text(
            json.dumps(trust_registry, indent=2),
            encoding="utf-8",
        )
        schema = promotion_schema()
        checks.append(
            _check(
                "schema_powerless",
                "The reviewed-learning schema grants no runtime authority",
                schema.get("status") == "ready"
                and schema.get("runtime_authority") == "none"
                and schema.get("threshold", {}).get(
                    "distinct_real_sessions"
                )
                == 3,
                detail=schema,
            )
        )
        rejected, rejection = _expect_failure(
            lambda: _protected_registry_snapshot(trust_registry_path),
            "fixed to the OS account",
        )
        checks.append(
            _check(
                "production_trust_root_is_fixed",
                "The production trust registry cannot be redirected to a writable probe path",
                rejected,
                detail=rejection,
            )
        )
        session_schema = session_evidence_schema()
        preregistration_fields = set(
            session_schema.get("event_contract", {}).get(
                "preregistration_fields",
                [],
            )
        )
        checks.append(
            _check(
                "real_lifecycle_is_preregistered_to_candidate",
                "The formal session contract exposes an immutable promotion binding and every bound verification session is explicitly non-voting",
                "promotion_binding" in preregistration_fields
                and _promotion_observation_exclusion_reason(
                    {
                        "promotion_binding": {
                            "candidate_id": "a" * 64,
                        }
                    }
                )
                == "promotion_verification_session_non_voting"
                and _promotion_observation_exclusion_reason({}) is None,
                detail={
                    "promotion_binding_field": (
                        "promotion_binding" in preregistration_fields
                    ),
                    "verification_session_reason_code": (
                        _promotion_observation_exclusion_reason(
                            {"promotion_binding": {"candidate_id": "a" * 64}}
                        )
                    ),
                },
            )
        )
        package_root = Path(__file__).resolve().parent
        allowed_importers = {
            "cli.py",
            "promotion.py",
            "promotion_probe.py",
            "smoke.py",
        }
        unexpected_importers: list[str] = []
        for source_path in package_root.rglob("*.py"):
            relative_source = source_path.relative_to(package_root).as_posix()
            if relative_source in allowed_importers:
                continue
            source = source_path.read_text(encoding="utf-8")
            if (
                "from sciplot_core.promotion import" in source
                or "import sciplot_core.promotion" in source
            ):
                unexpected_importers.append(relative_source)
        checks.append(
            _check(
                "runtime_import_isolation",
                "Plotting, rules, policy, readiness, QA, and delivery do not import promotion artifacts",
                not unexpected_importers,
                detail={"unexpected_importers": unexpected_importers},
            )
        )

        mapping = canonicalize_data_mapping_execution(mapping_execution)
        mapping_text = json.dumps(mapping, ensure_ascii=False, sort_keys=True)
        forbidden_mapping_literals = [
            str(mapping_execution.expanduser().resolve()),
            "typed_provider_stub",
            "probe_user",
            "bad",
        ]
        checks.append(
            _check(
                "mapping_canonicalization",
                "Mapping decisions omit paths, provider identity, owner identity, and raw condition values",
                mapping.get("decision_kind") == "data_mapping"
                and all(
                    literal not in mapping_text
                    for literal in forbidden_mapping_literals
                )
                and '"value_class": "text"' in mapping_text,
                detail=mapping,
            )
        )
        mapping_candidate_id = canonical_sha256(mapping)
        mapping_effect_basis = {
            "candidate_id": mapping_candidate_id,
            "lane": "simulated_contract_lane",
            "kind": "candidate_effect_manifest_equals",
            "path": ["promotion_effect"],
        }
        mapping_execution_basis = {
            "candidate_id": mapping_candidate_id,
            "lane": "simulated_contract_lane",
            "kind": "mapping_execution_matches_candidate",
        }
        mapping_contract = {
            "candidate_id": mapping_candidate_id,
            "source_files": ["src/sciplot_core/materials_rules.py"],
            "probe_files": [
                "src/sciplot_core/materials_rules_promotion_probe.py"
            ],
            "probe_kinds": ["sciplot_materials_rule_promotion_probe"],
            "lifecycle_lanes": ["simulated_contract_lane"],
            "lifecycle_assertions": [
                {
                    "assertion_id": canonical_sha256(
                        mapping_effect_basis
                    ),
                    **mapping_effect_basis,
                },
                {
                    "assertion_id": canonical_sha256(
                        mapping_execution_basis
                    ),
                    **mapping_execution_basis,
                },
            ],
        }
        mapping_contract["lifecycle_assertions"].sort(
            key=lambda item: item["assertion_id"]
        )
        validated_mapping_contract = _validate_candidate_specific_contract(
            mapping_contract,
            {
                "candidate_id": mapping_candidate_id,
                "canonical_decision": mapping,
            },
        )
        hollow_contract = json.loads(json.dumps(mapping_contract))
        hollow_basis = {
            "candidate_id": mapping_candidate_id,
            "lane": "simulated_contract_lane",
            "kind": "canvas_session_field_equals",
            "path": ["state"],
        }
        hollow_contract["lifecycle_assertions"] = [
            {
                "assertion_id": canonical_sha256(hollow_basis),
                **hollow_basis,
            }
        ]
        rejected, rejection = _expect_failure(
            lambda: _validate_implementation_contract(hollow_contract),
            "unsupported lifecycle assertion kind",
        )
        checks.append(
            _check(
                "candidate_effect_contract_rejects_health_only_assertions",
                "A lifecycle must expose the whole canonical candidate instead of repeating state=ready",
                validated_mapping_contract["candidate_id"]
                == mapping_candidate_id
                and rejected,
                detail=rejection,
            )
        )

        evidence_snapshot = verified_session_evidence_snapshot(
            synthetic_session_ledger
        )
        evidence_sessions = _session_records(evidence_snapshot["events"])
        signed_session_id = next(
            session_id
            for session_id, record in evidence_sessions.items()
            if {
                "preregistration",
                "witness",
                "completion",
            }
            <= set(record)
            and record["witness"]["payload"].get("authority_mode")
            == "canvas"
        )
        signed_session_binding = build_promotion_session_binding(
            synthetic_session_ledger,
            signed_session_id,
        )
        _verified_snapshot, _verified_session, verified_binding = (
            _verify_signed_session_reference(signed_session_binding)
        )
        tampered_binding = json.loads(json.dumps(signed_session_binding))
        tampered_binding["completion_event_sha256"] = "f" * 64
        rejected, rejection = _expect_failure(
            lambda: _verify_signed_session_reference(tampered_binding),
            "binding changed",
        )
        checks.append(
            _check(
                "verification_receipt_binds_session_bytes_and_authority",
                "Signed lifecycle facts bind the ledger prefix, all three events, and current authority artifacts",
                verified_binding == signed_session_binding and rejected,
                detail={
                    "ledger_prefix_sha256": verified_binding[
                        "ledger_prefix_sha256"
                    ],
                    "authority_artifact_count": len(
                        verified_binding["authority_artifacts"]
                    ),
                    "tamper_rejection": rejection,
                },
            )
        )

        from sciplot_core.workflow import run_request

        original_execution = load_data_mapping_execution(mapping_execution)
        original_proposal = load_data_mapping_proposal(
            Path(str(original_execution["proposal"]))
        )
        stable_mapping_root = run_root / "stable_mapping_lifecycle"
        stable_source_root = stable_mapping_root / "source"
        stable_source_root.mkdir(parents=True)
        stable_sources = []
        for source_reference in original_proposal.sources:
            original_source = (
                Path(str(original_execution["source_root"]))
                / source_reference.relative_path
            )
            stable_source = (
                stable_source_root / source_reference.relative_path
            )
            stable_source.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original_source, stable_source)
            stable_sources.append(
                replace(
                    source_reference,
                    sha256=file_sha256(stable_source),
                )
            )
        stable_request = stable_mapping_root / "plot_request.json"
        stable_request.write_text(
            json.dumps(
                {
                    "input": str(stable_source_root),
                    "output": str(stable_mapping_root / "baseline_run"),
                    "template": "curve",
                    "exports": ["pdf", "tiff_300"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        stable_proposal = replace(
            original_proposal,
            proposal_id="promotion-probe-stable",
            base_request_sha256=file_sha256(stable_request),
            sources=tuple(stable_sources),
        )
        stable_confirmation = create_data_mapping_confirmation(
            stable_proposal,
            source_root=stable_source_root,
            request_path=stable_request,
            output_root=stable_mapping_root / "mappings",
            confirmed_by="promotion_probe_user",
        )
        mapping_execution_payload = execute_data_mapping_proposal(
            stable_proposal,
            stable_confirmation,
            source_root=stable_source_root,
            request_path=stable_request,
            output_root=stable_mapping_root / "mappings",
        )
        stable_mapping_execution = (
            Path(str(mapping_execution_payload["output_root"]))
            / "execution.json"
        )
        if canonicalize_data_mapping_execution(
            stable_mapping_execution
        ) != mapping:
            raise ValueError(
                "Stable mapping lifecycle fixture changed the canonical candidate."
            )
        mapping_run_manifest = run_request(
            Path(str(mapping_execution_payload["request_candidate"]))
        )
        mapping_manifest_path = (
            Path(str(mapping_run_manifest["output"])) / "manifest.json"
        )
        stable_source_record = artifact_content_record(stable_source_root)
        mapping_preregistration = {
            "sources": [
                {
                    "kind": stable_source_record["kind"],
                    "path": stable_source_record["path"],
                    "artifact_sha256": stable_source_record["sha256"],
                    "members": stable_source_record["members"],
                }
            ],
            "expected_evidence": ["data_mapping"],
        }
        mapping_witness_record = {
            "path": str(stable_mapping_execution),
            "sha256": file_sha256(stable_mapping_execution),
            "proposal_id": mapping_execution_payload["proposal_id"],
            "proposal_sha256": mapping_execution_payload["proposal_sha256"],
            "provider": mapping_execution_payload["provider"],
            "confirmation_id": mapping_execution_payload["confirmation_id"],
            "transform_ledger_sha256": mapping_execution_payload[
                "transform_ledger_sha256"
            ],
            "raw_inputs_unchanged": True,
            "handoff_allowed": True,
        }
        mapping_witness = {
            "optional_evidence": {
                "data_mapping": mapping_witness_record,
            }
        }
        mapping_completion = {
            "manifest": {
                "path": str(mapping_manifest_path),
                "sha256": file_sha256(mapping_manifest_path),
                "transform_ledger_sha256": canonical_sha256(
                    mapping_run_manifest["transform_ledger"]
                ),
            }
        }
        mapping_assertion_basis = {
            "candidate_id": mapping_candidate_id,
            "lane": "simulated_contract_lane",
            "kind": "mapping_execution_matches_candidate",
        }
        mapping_assertion = {
            "assertion_id": canonical_sha256(mapping_assertion_basis),
            **mapping_assertion_basis,
        }
        mapping_assertion_results = _verify_lifecycle_assertions(
            assertions=[mapping_assertion],
            canonical_decision=mapping,
            document=None,
            canvas_session=None,
            preregistration=mapping_preregistration,
            witness=mapping_witness,
            completion=mapping_completion,
            project_root=stable_mapping_execution.parent,
        )
        wrong_mapping = json.loads(json.dumps(mapping))
        wrong_mapping["source_count"] = int(
            wrong_mapping.get("source_count") or 0
        ) + 1
        rejected, rejection = _expect_failure(
            lambda: _verify_lifecycle_assertions(
                assertions=[mapping_assertion],
                canonical_decision=wrong_mapping,
                document=None,
                canvas_session=None,
                preregistration=mapping_preregistration,
                witness=mapping_witness,
                completion=mapping_completion,
                project_root=stable_mapping_execution.parent,
            ),
            "candidate-effect assertion failed",
        )
        checks.append(
            _check(
                "mapping_effect_is_independently_replayed",
                "A data-mapping promotion must reproduce its proposal, outputs, transforms, and final source lineage",
                len(mapping_assertion_results) == 1 and rejected,
                detail={
                    "passing_results": mapping_assertion_results,
                    "mismatch_rejection": rejection,
                },
            )
        )

        applied_entry, batch_payload, session_path = _find_committed_batch(
            canvas_project
        )
        session = load_canvas_session(session_path)
        canvas = canonicalize_canvas_batch(batch_payload, session=session)
        canvas_text = json.dumps(canvas, ensure_ascii=False, sort_keys=True)
        raw_batch = CanvasOperationBatch.from_dict(batch_payload)
        forbidden_canvas_literals = [
            raw_batch.provider,
            raw_batch.batch_id,
            raw_batch.operations[0].target_id,
            str(raw_batch.operations[0].arguments.get("value") or ""),
        ]
        checks.append(
            _check(
                "canvas_canonicalization",
                "Canvas decisions omit provider, transaction IDs, object IDs, and free-text values",
                canvas.get("decision_kind") == "canvas_operation_batch"
                and all(
                    literal not in canvas_text
                    for literal in forbidden_canvas_literals
                ),
                detail=canvas,
            )
        )
        batch = CanvasOperationBatch.from_dict(batch_payload)
        set_operation = next(
            operation
            for operation in batch.operations
            if operation.operation_type == "set_setting"
        )
        set_change = next(
            change
            for change in applied_entry.get("changes", [])
            if isinstance(change, dict)
            and change.get("operation_id") == set_operation.operation_id
        )

        class ProbeSetting:
            def __init__(self, value: Any) -> None:
                self.value = value

            def get(self) -> Any:
                return self.value

        class ProbeDocument:
            def __init__(self, value: Any) -> None:
                self.value = value

            def resolveSettingPath(
                self,
                _base: object,
                _path: str,
            ) -> ProbeSetting:
                return ProbeSetting(self.value)

        final_match = _batch_matches_final_document(
            document=ProbeDocument(set_change.get("new_value")),
            batch_payload=batch_payload,
            applied_entry=applied_entry,
        )
        final_mismatch = _batch_matches_final_document(
            document=ProbeDocument("__later_manual_value__"),
            batch_payload=batch_payload,
            applied_entry=applied_entry,
        )
        later_batch = json.loads(json.dumps(batch_payload))
        later_batch["batch_id"] = str(uuid4())
        for operation in later_batch["operations"]:
            operation["operation_id"] = str(uuid4())
        applied_gap_superseded = _batch_was_later_superseded(
            [
                applied_entry,
                {
                    "event": "assistant_batch_applied",
                    "batch": later_batch,
                },
                {"event": "assistant_transaction_committed"},
            ],
            applied_index=0,
            batch_payload=batch_payload,
        )
        checks.append(
            _check(
                "final_document_effect_is_authority",
                "Applied-to-commit supersession and a mismatching final VSZ setting both prevent an observation",
                final_match
                and not final_mismatch
                and applied_gap_superseded,
                detail={
                    "matching_final_effect": final_match,
                    "mismatching_final_effect": final_mismatch,
                    "applied_commit_gap_superseded": applied_gap_superseded,
                },
            )
        )
        canvas_candidate_id = canonical_sha256(canvas)
        candidate_effect_manifest = run_root / "candidate_effect_manifest.json"
        candidate_effect_manifest.write_text(
            json.dumps({"promotion_effect": canvas}, indent=2),
            encoding="utf-8",
        )
        candidate_effect_basis = {
            "candidate_id": canvas_candidate_id,
            "lane": "simulated_contract_lane",
            "kind": "candidate_effect_manifest_equals",
            "path": ["promotion_effect"],
        }
        operation_index = next(
            index
            for index, operation in enumerate(batch.operations)
            if operation.operation_id == set_operation.operation_id
        )
        setting_effect_basis = {
            "candidate_id": canvas_candidate_id,
            "lane": "simulated_contract_lane",
            "kind": "veusz_setting_matches_operation",
            "path": str(set_operation.arguments["setting_path"]),
            "operation_index": operation_index,
        }
        lifecycle_assertions = [
            {
                "assertion_id": canonical_sha256(candidate_effect_basis),
                **candidate_effect_basis,
            },
            {
                "assertion_id": canonical_sha256(setting_effect_basis),
                **setting_effect_basis,
            },
        ]
        lifecycle_assertions.sort(key=lambda item: item["assertion_id"])
        completion = {
            "manifest": {
                "path": str(candidate_effect_manifest),
                "sha256": file_sha256(candidate_effect_manifest),
            }
        }
        assertion_results = _verify_lifecycle_assertions(
            assertions=lifecycle_assertions,
            canonical_decision=canvas,
            document=ProbeDocument(set_change.get("new_value")),
            canvas_session=session,
            preregistration={},
            witness={},
            completion=completion,
            project_root=run_root,
        )
        rejected, rejection = _expect_failure(
            lambda: _verify_lifecycle_assertions(
                assertions=lifecycle_assertions,
                canonical_decision=canvas,
                document=ProbeDocument("__not_the_candidate_effect__"),
                canvas_session=session,
                preregistration={},
                witness={},
                completion=completion,
                project_root=run_root,
            ),
            "candidate-effect assertion failed",
        )
        checks.append(
            _check(
                "real_lifecycle_requires_observable_behavior",
                "Candidate-bound lifecycle assertions require the whole canonical decision and its final VSZ effect",
                len(assertion_results) == 2 and rejected,
                detail={
                    "passing_results": assertion_results,
                    "mismatch_rejection": rejection,
                },
            )
        )

        collection = collect_promotion_observations(
            [synthetic_session_ledger],
            output_path=collection_path,
        )
        candidates = build_promotion_candidates(
            collection_path,
            output_path=candidates_path,
        )
        status = promotion_status(candidates_path)
        status_validator_paths: list[Path] = []
        original_candidate_validator = (
            promotion_module._validate_candidate_set
        )

        def record_status_validator_path(path: Path) -> dict[str, Any]:
            status_validator_paths.append(path.resolve())
            return original_candidate_validator(path)

        promotion_module._validate_candidate_set = (
            record_status_validator_path
        )
        try:
            snapshot_status = promotion_status(candidates_path)
        finally:
            promotion_module._validate_candidate_set = (
                original_candidate_validator
            )
        checks.append(
            _check(
                "synthetic_never_promotes",
                "A replayed synthetic evidence ledger produces zero review-ready candidates",
                collection.get("status") == "passed"
                and candidates.get("summary", {}).get(
                    "ready_for_review_count"
                )
                == 0
                and status.get("runtime_effect") is False,
                detail={
                    "collection": collection.get("summary"),
                    "candidates": candidates.get("summary"),
                    "status": status,
                },
            )
        )
        checks.append(
            _check(
                "status_validator_consumes_captured_snapshot",
                "learning status dispatches and validates from the same private byte snapshot",
                snapshot_status.get("status") == "passed"
                and len(status_validator_paths) == 1
                and status_validator_paths[0] != candidates_path.resolve()
                and ".promotion-snapshot." in status_validator_paths[0].name,
                detail={
                    "validator_paths": [
                        str(path) for path in status_validator_paths
                    ]
                },
            )
        )

        simulated = [
            _simulated_observation(
                decision=mapping,
                session_id=f"simulated_real_{index}",
                task_fingerprint=canonical_sha256(
                    {"simulated_task": index}
                ),
                eligible=True,
            )
            for index in range(3)
        ]
        simulated_candidate = _candidate_rows(simulated)[0]
        checks.append(
            _check(
                "three_distinct_contract",
                "The pure grouping contract reaches review only at three distinct real-shaped sessions and tasks",
                simulated_candidate["state"] == "ready_for_review"
                and simulated_candidate["threshold_count"] == 3,
                detail={
                    "simulated_contract_fixture": True,
                    "candidate": simulated_candidate,
                },
            )
        )

        duplicate_task = [
            _simulated_observation(
                decision=mapping,
                session_id=f"duplicate_task_{index}",
                task_fingerprint=canonical_sha256(
                    {"same_simulated_task": True}
                ),
                eligible=True,
            )
            for index in range(3)
        ]
        duplicate_candidate = _candidate_rows(duplicate_task)[0]
        checks.append(
            _check(
                "duplicate_task_resists_vote_stuffing",
                "Three sessions repeating one task fingerprint cannot stuff the review threshold",
                duplicate_candidate["state"] == "observed"
                and duplicate_candidate["threshold_count"] == 1,
                detail={
                    "simulated_contract_fixture": True,
                    "candidate": duplicate_candidate,
                },
            )
        )

        mixed_owner = [
            _simulated_observation(
                decision=mapping,
                session_id=f"mixed_owner_{index}",
                task_fingerprint=canonical_sha256(
                    {"mixed_owner_task": index}
                ),
                eligible=True,
                owner=f"simulated_owner_{index}",
            )
            for index in range(3)
        ]
        mixed_owner_candidate = _candidate_rows(mixed_owner)[0]
        checks.append(
            _check(
                "mixed_owners_cannot_combine_authority",
                "Three different owners cannot combine one observation each into approval authority",
                mixed_owner_candidate["state"] == "observed"
                and mixed_owner_candidate["threshold_count"] == 1
                and not mixed_owner_candidate[
                    "ready_owner_attestation_sha256s"
                ],
                detail={
                    "simulated_contract_fixture": True,
                    "candidate": mixed_owner_candidate,
                },
            )
        )

        synthetic_votes = [
            _simulated_observation(
                decision=mapping,
                session_id=f"synthetic_vote_{index}",
                task_fingerprint=canonical_sha256(
                    {"synthetic_task": index}
                ),
                eligible=False,
            )
            for index in range(3)
        ]
        synthetic_candidate = _candidate_rows(synthetic_votes)[0]
        checks.append(
            _check(
                "synthetic_votes_are_zero",
                "Three synthetic observations still count as zero threshold votes",
                synthetic_candidate["state"] == "observed"
                and synthetic_candidate["threshold_count"] == 0,
                detail={
                    "simulated_contract_fixture": True,
                    "candidate": synthetic_candidate,
                },
            )
        )

        tampered_collection_path = run_root / "tampered_collection.json"
        tampered = json.loads(collection_path.read_text(encoding="utf-8"))
        tampered["summary"]["observation_count"] += 1
        tampered_collection_path.write_text(
            json.dumps(tampered, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        rejected, rejection = _expect_failure(
            lambda: build_promotion_candidates(tampered_collection_path),
            "hash",
            "stale",
        )
        checks.append(
            _check(
                "tampered_collection_rejected",
                "A modified collection with its old content hash is rejected",
                rejected,
                detail=rejection,
            )
        )

        decision_receipt_path = run_root / "owner_decision_receipt.json"
        lifecycle_assertion_basis = {
            "candidate_id": "0" * 64,
            "lane": "rheology_dma_torque",
            "kind": "candidate_effect_manifest_equals",
            "path": ["promotion_effect"],
        }
        implementation_contract = {
            "candidate_id": "0" * 64,
            "source_files": ["src/sciplot_core/materials_rules.py"],
            "probe_files": [
                "src/sciplot_core/materials_rules_promotion_probe.py"
            ],
            "probe_kinds": ["sciplot_materials_rule_promotion_probe"],
            "lifecycle_lanes": ["rheology_dma_torque"],
            "lifecycle_assertions": [
                {
                    "assertion_id": canonical_sha256(
                        lifecycle_assertion_basis
                    ),
                    **lifecycle_assertion_basis,
                }
            ],
        }
        decision_receipt = _sign_probe_receipt(
            {
                "kind": PROMOTION_DECISION_RECEIPT_KIND,
                "version": 1,
                "candidate_id": "0" * 64,
                "candidate_set_sha256": candidates["candidate_set_sha256"],
                "decision": "approve",
                "owner": "simulated_contract_owner",
                "rationale": "Exercise the signed owner-receipt parser.",
                "owner_attested": True,
                "attestation": OWNER_DECISION_ATTESTATION,
                "implementation_contract": implementation_contract,
                "recorded_at": datetime.now(UTC).isoformat(),
            },
            owner_key_id,
            private_key=probe_private_key,
        )
        decision_receipt_path.write_text(
            json.dumps(decision_receipt, indent=2),
            encoding="utf-8",
        )
        parsed_decision_receipt = _load_owner_decision_receipt(
            decision_receipt_path,
            trust_registry_path=trust_registry_path,
        )
        rejected, rejection = _expect_failure(
            lambda: _decide_promotion_candidate(
                candidates_path,
                decision_receipt_path,
                trust_registry_path=trust_registry_path,
            ),
            "absent",
        )
        checks.append(
            _check(
                "decision_receipt_cannot_invent_candidate",
                "A valid external owner receipt still cannot approve a candidate absent from replayed evidence",
                parsed_decision_receipt["owner_attested"] is True and rejected,
                detail=rejection,
            )
        )

        unsigned_decision_path = run_root / "unsigned_owner_decision.json"
        unsigned_decision = dict(decision_receipt)
        unsigned_decision.pop("signature")
        unsigned_decision_path.write_text(
            json.dumps(unsigned_decision, indent=2),
            encoding="utf-8",
        )
        rejected, rejection = _expect_failure(
            lambda: _load_owner_decision_receipt(
                unsigned_decision_path,
                trust_registry_path=trust_registry_path,
            ),
            "signature",
        )
        checks.append(
            _check(
                "owner_string_cannot_self_authorize",
                "Owner text and fixed attestation cannot authorize without an external trusted-key signature",
                rejected,
                detail=rejection,
            )
        )

        reject_receipt_path = run_root / "owner_reject_receipt.json"
        reject_receipt = _sign_probe_receipt(
            {
                "kind": PROMOTION_DECISION_RECEIPT_KIND,
                "version": 1,
                "candidate_id": simulated_candidate["candidate_id"],
                "candidate_set_sha256": candidates["candidate_set_sha256"],
                "decision": "reject",
                "owner": "simulated_contract_owner",
                "rationale": "Exercise signed decision-state binding.",
                "owner_attested": True,
                "attestation": OWNER_DECISION_ATTESTATION,
                "recorded_at": datetime.now(UTC).isoformat(),
            },
            owner_key_id,
            private_key=probe_private_key,
        )
        reject_receipt_path.write_text(
            json.dumps(reject_receipt, indent=2),
            encoding="utf-8",
        )
        parsed_reject_receipt = _load_owner_decision_receipt(
            reject_receipt_path,
            trust_registry_path=trust_registry_path,
        )
        rejected_decision = {"state": "rejected_by_owner"}
        _validate_decision_state_binding(
            rejected_decision,
            receipt=parsed_reject_receipt,
            candidate=simulated_candidate,
        )
        tampered_decision_path = run_root / "tampered_decision_state.json"
        tampered_decision = _bind_artifact(
            {
                "state": "deferred_by_owner",
                "runtime_effect": False,
            },
            hash_field="decision_sha256",
        )
        tampered_decision_path.write_text(
            json.dumps(tampered_decision, indent=2),
            encoding="utf-8",
        )
        rejected, rejection = _expect_failure(
            lambda: _validate_decision_state_binding(
                tampered_decision,
                receipt=parsed_reject_receipt,
                candidate=simulated_candidate,
            ),
            "state",
            "signed receipt",
        )
        checks.append(
            _check(
                "decision_state_is_receipt_derived",
                "Rehashing a decision cannot rewrite reject into another state",
                rejected,
                detail=rejection,
            )
        )

        decision_snapshot_path = run_root / "decision_snapshot_probe.json"
        decision_snapshot = {"decision_sha256": "7" * 64}
        decision_snapshot_path.write_text(
            json.dumps(decision_snapshot, indent=2),
            encoding="utf-8",
        )
        decision_snapshot_plan = {
            "decision": {
                "path": str(decision_snapshot_path),
                "file_sha256": file_sha256(decision_snapshot_path),
                "decision_sha256": decision_snapshot["decision_sha256"],
            }
        }
        decision_validator_paths: list[Path] = []
        original_decision_validator = promotion_module._validate_decision

        def load_probe_decision(path: Path) -> dict[str, Any]:
            decision_validator_paths.append(path.resolve())
            return json.loads(path.read_text(encoding="utf-8"))

        promotion_module._validate_decision = load_probe_decision
        try:
            loaded_snapshot, loaded_snapshot_sha256 = (
                _load_plan_decision_snapshot(decision_snapshot_plan)
            )
            changed_reference = json.loads(
                json.dumps(decision_snapshot_plan)
            )
            changed_reference["decision"]["file_sha256"] = "8" * 64
            snapshot_rejected, snapshot_rejection = _expect_failure(
                lambda: _load_plan_decision_snapshot(changed_reference),
                "decision file changed",
            )
        finally:
            promotion_module._validate_decision = (
                original_decision_validator
            )
        checks.append(
            _check(
                "verification_uses_plan_bound_decision_snapshot",
                "Verification consumes one private decision-byte snapshot and rejects any file hash that differs from the plan",
                loaded_snapshot == decision_snapshot
                and loaded_snapshot_sha256
                == decision_snapshot_plan["decision"]["file_sha256"]
                and len(decision_validator_paths) == 2
                and all(
                    path != decision_snapshot_path.resolve()
                    and ".promotion-snapshot." in path.name
                    for path in decision_validator_paths
                )
                and snapshot_rejected,
                detail={
                    "validator_paths": [
                        str(path) for path in decision_validator_paths
                    ],
                    "rejection": snapshot_rejection,
                },
            )
        )

        generic_probe_path = run_root / "generic_passing_probe.json"
        generic_probe_path.write_text(
            json.dumps(
                {
                    "kind": "sciplot_materials_rule_promotion_probe",
                    "version": 1,
                    "status": "passed",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        probe_lifecycle_basis = {
            "candidate_id": "4" * 64,
            "lane": "rheology_dma_torque",
            "kind": "candidate_effect_manifest_equals",
            "path": ["promotion_effect"],
        }
        probe_implementation_contract = {
            **implementation_contract,
            "candidate_id": "4" * 64,
            "lifecycle_assertions": [
                {
                    "assertion_id": canonical_sha256(
                        probe_lifecycle_basis
                    ),
                    **probe_lifecycle_basis,
                }
            ],
        }
        fake_plan = {
            "candidate_id": "4" * 64,
            "canonical_decision_sha256": "4" * 64,
            "plan_sha256": "5" * 64,
            "implementation_contract": probe_implementation_contract,
        }
        rejected, rejection = _expect_failure(
            lambda: _verify_probe_artifacts(
                [
                    {
                        "path": str(generic_probe_path),
                        "sha256": file_sha256(generic_probe_path),
                        "probe_file": implementation_contract[
                            "probe_files"
                        ][0],
                    }
                ],
                plan=fake_plan,
                expected_commit="6" * 40,
                repo_root=run_root,
            ),
            "promotion_verification",
        )
        checks.append(
            _check(
                "generic_probe_cannot_verify_candidate",
                "An unrelated passing JSON probe cannot verify a promotion candidate",
                rejected,
                detail=rejection,
            )
        )

        probe_repo = run_root / "reviewed_probe_repo"
        probe_source_path = (
            probe_repo
            / implementation_contract["probe_files"][0]
        )
        probe_source_path.parent.mkdir(parents=True, exist_ok=True)
        probe_source_path.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "import argparse",
                    "import json",
                    "from pathlib import Path",
                    "",
                    "parser = argparse.ArgumentParser()",
                    "parser.add_argument('--promotion-context', type=Path, required=True)",
                    "parser.add_argument('--json', action='store_true')",
                    "args = parser.parse_args()",
                    "context = json.loads(args.promotion_context.read_text(encoding='utf-8'))",
                    "binding_keys = (",
                    "    'candidate_id', 'canonical_decision_sha256',",
                    "    'plan_sha256', 'verified_commit', 'source_files',",
                    "    'probe_file', 'status',",
                    ")",
                    "payload = {",
                    "    'kind': 'sciplot_materials_rule_promotion_probe',",
                    "    'version': 1,",
                    "    'status': 'passed',",
                    "    'promotion_verification': {",
                    "        key: context[key] for key in binding_keys",
                    "    },",
                    "}",
                    "print(json.dumps(payload, sort_keys=True))",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        initialized = subprocess.run(
            [str(_trusted_git_executable()), "init", "-q"],
            cwd=probe_repo,
            env=_git_environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        if initialized.returncode != 0:
            raise ValueError(
                "Could not initialize the reviewed probe Git fixture: "
                f"{(initialized.stderr or initialized.stdout).strip()}"
            )
        _git(probe_repo, "add", "src")
        _git(
            probe_repo,
            "-c",
            "user.name=SciPlot Promotion Probe",
            "-c",
            "user.email=promotion-probe@invalid",
            "commit",
            "-q",
            "-m",
            "Create reviewed probe fixture",
        )
        reviewed_probe_commit = _git(probe_repo, "rev-parse", "HEAD")
        reproducible_binding = {
            "candidate_id": fake_plan["candidate_id"],
            "canonical_decision_sha256": fake_plan[
                "canonical_decision_sha256"
            ],
            "plan_sha256": fake_plan["plan_sha256"],
            "verified_commit": reviewed_probe_commit,
            "source_files": implementation_contract["source_files"],
            "probe_file": implementation_contract["probe_files"][0],
            "status": "passed",
        }
        reproducible_payload = {
            "kind": "sciplot_materials_rule_promotion_probe",
            "version": 1,
            "status": "passed",
            "promotion_verification": reproducible_binding,
        }
        reproducible_probe_path = run_root / "reproducible_probe.json"
        reproducible_probe_path.write_text(
            json.dumps(reproducible_payload, indent=2),
            encoding="utf-8",
        )
        reproduced = _verify_probe_artifacts(
            [
                {
                    "path": str(reproducible_probe_path),
                    "sha256": file_sha256(reproducible_probe_path),
                    "probe_file": implementation_contract[
                        "probe_files"
                    ][0],
                }
            ],
            plan=fake_plan,
            expected_commit=reviewed_probe_commit,
            repo_root=probe_repo,
        )
        checks.append(
            _check(
                "candidate_probe_reexecutes_reviewed_source",
                "Verification re-executes the approved probe source and reproduces the signed artifact",
                len(reproduced) == 1
                and reproduced[0]["reproduced_from_reviewed_commit"] is True,
                detail=reproduced,
            )
        )
        original_probe_source = probe_source_path.read_text(encoding="utf-8")
        _git(
            probe_repo,
            "update-index",
            "--assume-unchanged",
            implementation_contract["probe_files"][0],
        )
        try:
            probe_source_path.chmod(0o600)
            probe_source_path.write_text(
                "raise SystemExit('mutable worktree probe was executed')\n",
                encoding="utf-8",
            )
            rejected, substitution_rejection = _expect_failure(
                lambda: _verify_probe_artifacts(
                    [
                        {
                            "path": str(reproducible_probe_path),
                            "sha256": file_sha256(reproducible_probe_path),
                            "probe_file": implementation_contract[
                                "probe_files"
                            ][0],
                        }
                    ],
                    plan=fake_plan,
                    expected_commit=reviewed_probe_commit,
                    repo_root=probe_repo,
                ),
                "index flags",
            )
        finally:
            probe_source_path.write_text(
                original_probe_source,
                encoding="utf-8",
            )
            _git(
                probe_repo,
                "update-index",
                "--no-assume-unchanged",
                implementation_contract["probe_files"][0],
            )
        _git(
            probe_repo,
            "update-index",
            "--skip-worktree",
            implementation_contract["probe_files"][0],
        )
        try:
            skip_rejected, skip_rejection = _expect_failure(
                lambda: _clean_git_state(
                    probe_repo,
                    expected_commit=reviewed_probe_commit,
                ),
                "index flags",
            )
        finally:
            _git(
                probe_repo,
                "update-index",
                "--no-skip-worktree",
                implementation_contract["probe_files"][0],
            )
        restored_git_state = _clean_git_state(
            probe_repo,
            expected_commit=reviewed_probe_commit,
        )
        checks.append(
            _check(
                "hidden_worktree_substitution_is_rejected",
                "Assume-unchanged and skip-worktree cannot hide reviewed source from exact-clean verification",
                rejected
                and skip_rejected
                and restored_git_state["commit"] == reviewed_probe_commit,
                detail={
                    "assume_unchanged": substitution_rejection,
                    "skip_worktree": skip_rejection,
                },
            )
        )
        previous_path = os.environ.get("PATH")
        previous_git_dir = os.environ.get("GIT_DIR")
        previous_git_index = os.environ.get("GIT_INDEX_FILE")
        try:
            os.environ["PATH"] = str(run_root / "path_shadow")
            os.environ["GIT_DIR"] = str(run_root / "redirected_git_dir")
            os.environ["GIT_INDEX_FILE"] = str(
                run_root / "redirected_git_index"
            )
            poisoned_environment_state = _clean_git_state(
                probe_repo,
                expected_commit=reviewed_probe_commit,
            )
        finally:
            for key, value in (
                ("PATH", previous_path),
                ("GIT_DIR", previous_git_dir),
                ("GIT_INDEX_FILE", previous_git_index),
            ):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        sha256_repo = run_root / "reviewed_probe_repo_sha256"
        sha256_source = sha256_repo / "source.txt"
        sha256_repo.mkdir(parents=True, exist_ok=True)
        sha256_source.write_text("sha256 reviewed source\n", encoding="utf-8")
        sha256_initialized = subprocess.run(
            [
                str(_trusted_git_executable()),
                "init",
                "--object-format=sha256",
                "-q",
            ],
            cwd=sha256_repo,
            env=_git_environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        if sha256_initialized.returncode != 0:
            raise ValueError(
                "Could not initialize the SHA-256 Git fixture: "
                f"{(sha256_initialized.stderr or sha256_initialized.stdout).strip()}"
            )
        _git(sha256_repo, "add", "source.txt")
        _git(
            sha256_repo,
            "-c",
            "user.name=SciPlot Promotion Probe",
            "-c",
            "user.email=promotion-probe@invalid",
            "commit",
            "-q",
            "-m",
            "Create SHA-256 reviewed fixture",
        )
        sha256_commit = _git(sha256_repo, "rev-parse", "HEAD")
        sha256_git_state = _clean_git_state(
            sha256_repo,
            expected_commit=sha256_commit,
        )
        checks.append(
            _check(
                "git_authority_ignores_ambient_redirects",
                "Reviewed Git identity uses a trusted executable, explicit "
                "worktree metadata, a closed environment, and full SHA-1 or "
                "SHA-256 object identities",
                poisoned_environment_state["commit"]
                == reviewed_probe_commit
                and poisoned_environment_state["git_executable"]
                == str(_trusted_git_executable())
                and len(sha256_commit) == 64
                and sha256_git_state["commit"] == sha256_commit,
                detail={
                    "git_executable": poisoned_environment_state[
                        "git_executable"
                    ],
                    "git_dir": poisoned_environment_state["git_dir"],
                    "sha256_commit": sha256_commit,
                },
            )
        )

        verification_receipt_path = run_root / "verification_receipt.json"
        verification_receipt = _sign_probe_receipt(
            {
                "kind": PROMOTION_VERIFICATION_RECEIPT_KIND,
                "version": 1,
                "plan_sha256": "1" * 64,
                "candidate_id": "2" * 64,
                "owner": "simulated_contract_owner",
                "reviewed_by": "simulated_contract_reviewer",
                "rationale": "Exercise the signed verification-receipt parser.",
                "owner_attested": True,
                "attestation": VERIFICATION_ATTESTATION,
                "expected_commit": "3" * 40,
                "probe_artifacts": [
                    {
                        "path": str(mapping_execution.expanduser().resolve()),
                        "sha256": file_sha256(mapping_execution),
                        "probe_file": implementation_contract[
                            "probe_files"
                        ][0],
                    }
                ],
                "real_sessions": [signed_session_binding],
                "recorded_at": datetime.now(UTC).isoformat(),
            },
            owner_key_id,
            private_key=probe_private_key,
        )
        verification_receipt_path.write_text(
            json.dumps(verification_receipt, indent=2),
            encoding="utf-8",
        )
        parsed_verification_receipt = _load_verification_receipt(
            verification_receipt_path,
            trust_registry_path=trust_registry_path,
        )
        alias_receipt_payload = {
            key: json.loads(json.dumps(value))
            for key, value in verification_receipt.items()
            if key not in {
                "owner_key_id",
                "signature_algorithm",
                "signature",
            }
        }
        alias_target = mapping_execution.expanduser().resolve()
        alias_receipt_payload["probe_artifacts"][0]["path"] = str(
            alias_target.parent
            / ".."
            / alias_target.parent.name
            / alias_target.name
        )
        alias_receipt = _sign_probe_receipt(
            alias_receipt_payload,
            owner_key_id,
            private_key=probe_private_key,
        )
        alias_receipt_path = run_root / "aliased_probe_receipt.json"
        alias_receipt_path.write_text(
            json.dumps(alias_receipt, indent=2),
            encoding="utf-8",
        )
        alias_rejected, alias_rejection = _expect_failure(
            lambda: _load_verification_receipt(
                alias_receipt_path,
                trust_registry_path=trust_registry_path,
            ),
            "probe-artifact paths",
            "canonical",
        )
        checks.append(
            _check(
                "verification_receipt_contract",
                "The verification receipt binds a full commit, canonical "
                "probe paths, probe hashes, signed session bytes, authority "
                "hashes, and exact attestation",
                parsed_verification_receipt["owner_attested"] is True
                and parsed_verification_receipt["expected_commit"] == "3" * 40
                and parsed_verification_receipt["real_sessions"]
                == [signed_session_binding]
                and alias_rejected,
                detail={
                    "simulated_contract_fixture": True,
                    "expected_commit": parsed_verification_receipt[
                        "expected_commit"
                    ],
                    "alias_rejection": alias_rejection,
                },
            )
        )

        verification_receipt["attestation"] = "AI self-approved"
        invalid_verification_path = run_root / "invalid_verification_receipt.json"
        invalid_verification_path.write_text(
            json.dumps(verification_receipt, indent=2),
            encoding="utf-8",
        )
        rejected, rejection = _expect_failure(
            lambda: _load_verification_receipt(
                invalid_verification_path,
                trust_registry_path=trust_registry_path,
            ),
            "attestation",
            "invalid",
        )
        checks.append(
            _check(
                "verification_attestation_is_closed",
                "An arbitrary self-approval phrase cannot satisfy verification",
                rejected,
                detail=rejection,
            )
        )
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if probe_private_key is not None:
            probe_private_key.close()

    status = (
        "passed"
        if error is None
        and checks
        and all(item["status"] == "passed" for item in checks)
        else "failed"
    )
    payload = {
        "kind": "sciplot_promotion_probe",
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(
                item["status"] == "passed" for item in checks
            ),
            "failed_ids": [
                item["id"] for item in checks if item["status"] != "passed"
            ],
        },
        "artifacts": {
            "run_root": str(run_root),
            "summary": str(summary_path),
            "collection": str(collection_path),
            "candidate_set": str(candidates_path),
            "trusted_owner_registry": str(trust_registry_path),
            "tampered_collection": str(run_root / "tampered_collection.json"),
            "decision_receipt": str(run_root / "owner_decision_receipt.json"),
            "tampered_decision_state": str(
                run_root / "tampered_decision_state.json"
            ),
            "verification_receipt": str(
                run_root / "verification_receipt.json"
            ),
        },
        "error": error,
        "limitations": [
            "The three-session positive threshold case uses explicitly simulated in-memory contract records.",
            "The replayed ledger is synthetic and proves only that synthetic evidence cannot promote.",
            "The probe keeps its ephemeral RSA private key only in an anonymous file descriptor; no probe private key is shipped, named on disk, or trusted by production.",
            "This probe creates only a synthetic rejected decision; it creates no real owner approval, source implementation, or promotion.",
        ],
    }
    summary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


__all__ = ["run_promotion_probe"]
