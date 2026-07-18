from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sciplot_core._utils import file_sha256
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.qa import run_qa
from sciplot_core.source_coverage import (
    verify_rendered_mapping_source_coverage,
)
from sciplot_core.veusz_runtime import veusz_worker_environment


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def require_within(root: Path, candidate: Path, *, label: str) -> Path:
    resolved_root = root.expanduser().resolve()
    resolved = candidate.expanduser().resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            f"{label} must stay inside the preregistered project."
        ) from exc
    return resolved


def artifact_content_record(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Lineage artifact not found: {resolved}")
    if resolved.is_file():
        return {
            "kind": "file",
            "path": str(resolved),
            "size_bytes": resolved.stat().st_size,
            "sha256": file_sha256(resolved),
        }
    if not resolved.is_dir():
        raise ValueError(f"Lineage artifact is not a file or directory: {resolved}")
    digest = hashlib.sha256()
    members: list[dict[str, Any]] = []
    total_size = 0
    for member in sorted(
        candidate for candidate in resolved.rglob("*") if candidate.is_file()
    ):
        if member.is_symlink():
            raise ValueError(f"Lineage directory contains a symlink: {member}")
        relative = member.relative_to(resolved).as_posix()
        member_hash = file_sha256(member)
        size = member.stat().st_size
        digest.update(relative.encode("utf-8"))
        digest.update(member_hash.encode("ascii"))
        total_size += size
        members.append(
            {
                "relative_path": relative,
                "size_bytes": size,
                "sha256": member_hash,
            }
        )
    if not members:
        raise ValueError(f"Lineage directory contains no files: {resolved}")
    return {
        "kind": "directory",
        "path": str(resolved),
        "size_bytes": total_size,
        "sha256": digest.hexdigest(),
        "member_count": len(members),
        "members": members,
    }


def _source_lineage_record(record: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(record.get("path") or "")).expanduser().resolve()
    kind = str(record.get("kind") or "")
    if kind == "file":
        digest = str(record.get("sha256") or "")
        members = [
            {
                "relative_path": path.name,
                "size_bytes": int(record.get("size_bytes") or 0),
                "sha256": digest,
            }
        ]
    elif kind == "directory":
        digest = str(record.get("artifact_sha256") or "")
        members = [
            dict(value)
            for value in record.get("members", [])
            if isinstance(value, dict)
        ]
    else:
        raise ValueError(f"Unsupported preregistered source kind: {kind!r}.")
    current = artifact_content_record(path)
    if current["kind"] != kind or current["sha256"] != digest:
        raise ValueError(f"Preregistered source lineage changed: {path}")
    return {
        "kind": kind,
        "path": str(path),
        "sha256": digest,
        "members": members,
    }


def _verify_transform_artifact(record: dict[str, Any], *, label: str) -> dict[str, Any]:
    if record.get("exists") is not True:
        raise ValueError(f"{label} is not marked as existing.")
    path = Path(str(record.get("path") or "")).expanduser().resolve()
    current = artifact_content_record(path)
    if (
        current["kind"] != record.get("kind")
        or current["sha256"] != record.get("sha256")
        or current["size_bytes"] != int(record.get("size_bytes") or -1)
    ):
        raise ValueError(f"{label} no longer matches its transform-ledger hash.")
    if current["kind"] == "directory" and current["member_count"] != int(
        record.get("member_count") or -1
    ):
        raise ValueError(f"{label} directory inventory changed.")
    return {
        "kind": current["kind"],
        "path": current["path"],
        "sha256": current["sha256"],
    }


def _artifact_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record["kind"]),
        str(Path(str(record["path"])).expanduser().resolve()),
        str(record["sha256"]),
    )


def _verify_mapping_lineage(
    application: dict[str, Any],
    *,
    preregistered_sources: list[dict[str, Any]],
    witnessed_mapping: dict[str, Any],
    final_ledger: dict[str, Any],
) -> None:
    execution_path = (
        Path(str(application.get("execution") or "")).expanduser().resolve()
    )
    witnessed_execution = (
        Path(str(witnessed_mapping.get("path") or "")).expanduser().resolve()
    )
    if execution_path != witnessed_execution or file_sha256(
        execution_path
    ) != witnessed_mapping.get("sha256"):
        raise ValueError(
            "Final manifest data-mapping application does not match the "
            "witnessed execution."
        )
    execution = load_data_mapping_execution(execution_path)
    identity_fields = (
        "provider",
        "proposal_id",
        "proposal_sha256",
        "confirmation_id",
    )
    for field in identity_fields:
        if application.get(field) != witnessed_mapping.get(field) or application.get(
            field
        ) != execution.get(field):
            raise ValueError(
                "Final manifest data-mapping identity does not match the "
                f"verified execution: {field}."
            )
    if witnessed_mapping.get("transform_ledger_sha256") != execution.get(
        "transform_ledger_sha256"
    ):
        raise ValueError(
            "Witnessed data-mapping transform ledger does not match the "
            "verified execution."
        )
    execution_ledger_path = (
        Path(str(execution.get("transform_ledger") or "")).expanduser().resolve()
    )
    execution_ledger = json.loads(execution_ledger_path.read_text(encoding="utf-8"))
    mapping_steps = execution.get("transform_steps")
    final_steps = final_ledger.get("steps")
    if (
        application.get("transform_steps") != mapping_steps
        or application.get("transform_ledger") != execution_ledger
        or not isinstance(mapping_steps, list)
        or not mapping_steps
        or not isinstance(final_steps, list)
        or final_steps[: len(mapping_steps)] != mapping_steps
    ):
        raise ValueError(
            "Final transform ledger does not begin with the exact confirmed "
            "data-mapping derivation."
        )
    expected_outputs = [
        {
            "source_id": str(record.get("source_id") or ""),
            "path": str(Path(str(record.get("path") or "")).expanduser().resolve()),
            "sha256": str(record.get("sha256") or ""),
            "rows": int(record.get("rows") or 0),
            "columns": [str(value) for value in record.get("columns", [])],
            "sample_label": (
                str(record["sample_label"])
                if record.get("sample_label") is not None
                else None
            ),
        }
        for record in execution.get("outputs", [])
        if isinstance(record, dict)
    ]
    if (
        application.get("mapped_outputs") != expected_outputs
        or Path(str(application.get("effective_input") or "")).expanduser().resolve()
        != Path(str(execution.get("effective_input") or "")).expanduser().resolve()
        or application.get("raw_inputs_preserved") is not True
        or application.get("outputs_verified") is not True
    ):
        raise ValueError(
            "Final data-mapping application output inventory does not match "
            "the verified execution."
        )
    source_root = Path(str(application.get("source_root") or "")).expanduser().resolve()
    if source_root != Path(
        str(execution.get("source_root") or "")
    ).expanduser().resolve() or application.get("source_hashes") != execution.get(
        "source_hashes"
    ):
        raise ValueError(
            "Final data-mapping source evidence does not match the verified execution."
        )
    source_hashes = application.get("source_hashes")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise ValueError("Data-mapping application has no source hashes.")
    matching = [
        record
        for record in preregistered_sources
        if Path(record["path"]) == source_root
    ]
    if len(matching) != 1 or matching[0]["kind"] != "directory":
        raise ValueError(
            "Data-mapping source_root must equal one preregistered source directory."
        )
    registered_members = {
        str(member.get("relative_path") or ""): str(member.get("sha256") or "")
        for member in matching[0]["members"]
    }
    if registered_members != {
        str(key): str(value) for key, value in source_hashes.items()
    }:
        raise ValueError(
            "Data-mapping source hashes differ from preregistered raw evidence."
        )


def _verify_terminal_data_snapshots(
    result: dict[str, Any],
    *,
    final_outputs: set[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    values = result.get("data_snapshot_sources")
    scalar = result.get("data_snapshot_source")
    if values is None:
        if not isinstance(scalar, str) or not scalar.strip():
            raise ValueError(
                "Final manifest does not identify the plotted data snapshot."
            )
        raw_paths = [scalar]
    else:
        if (
            not isinstance(values, list)
            or not values
            or any(
                not isinstance(value, str) or not value.strip()
                for value in values
            )
        ):
            raise ValueError(
                "Final manifest plotted data snapshots must be a non-empty "
                "path list."
            )
        raw_paths = list(values)
        if scalar is not None:
            if (
                not isinstance(scalar, str)
                or len(raw_paths) != 1
                or Path(scalar).expanduser().resolve()
                != Path(raw_paths[0]).expanduser().resolve()
            ):
                raise ValueError(
                    "Scalar and plural plotted data snapshot identities disagree."
                )
    resolved_paths = [
        Path(value).expanduser().resolve()
        for value in raw_paths
    ]
    if len(set(resolved_paths)) != len(resolved_paths):
        raise ValueError("Final manifest repeats a plotted data snapshot.")
    snapshots = sorted(
        (artifact_content_record(path) for path in resolved_paths),
        key=lambda record: (
            str(record["kind"]),
            str(record["path"]),
            str(record["sha256"]),
        ),
    )
    snapshot_keys = {_artifact_key(record) for record in snapshots}
    if not snapshot_keys <= final_outputs:
        raise ValueError(
            "A final plotted data snapshot is not a terminal transform output."
        )
    if len(final_outputs) > 1 and snapshot_keys != final_outputs:
        raise ValueError(
            "A multi-table plot must bind every terminal transform output; "
            "silent source omission is forbidden."
        )
    return snapshots


def verify_regular_source_lineage(
    payload: dict[str, Any],
    *,
    preregistration: dict[str, Any],
    witnessed_mapping: dict[str, Any] | None,
) -> dict[str, Any]:
    source_records = [
        _source_lineage_record(value)
        for value in preregistration.get("sources", [])
        if isinstance(value, dict)
    ]
    if not source_records:
        raise ValueError("No preregistered source lineage is available.")
    ledger = payload.get("transform_ledger")
    if not isinstance(ledger, dict):
        raise ValueError("Final manifest has no transform ledger.")
    if (
        ledger.get("kind") != "sciplot_transform_ledger"
        or ledger.get("version") != 1
        or ledger.get("status") not in {"runtime_recorded", "confirmed"}
    ):
        raise ValueError("Final transform ledger is not complete and current.")
    policy = ledger.get("policy")
    if not isinstance(policy, dict) or (
        policy.get("raw_sources_preserved") is not True
        or policy.get("silent_data_omission_allowed") is not False
        or policy.get("selection_must_be_recorded") is not True
        or policy.get("unit_conversion_must_be_recorded") is not True
    ):
        raise ValueError("Final transform-ledger policy is incomplete or unsafe.")
    steps = ledger.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Final transform ledger must contain at least one step.")
    known_outputs: set[tuple[str, str, str]] = set()
    initial_inputs: set[tuple[str, str, str]] = set()
    final_outputs: set[tuple[str, str, str]] = set()
    step_ids: set[str] = set()
    for step_index, raw_step in enumerate(steps):
        if not isinstance(raw_step, dict):
            raise ValueError("Transform-ledger steps must be objects.")
        step_id = str(raw_step.get("id") or "")
        if not step_id or step_id in step_ids:
            raise ValueError("Transform-ledger step IDs must be unique and non-empty.")
        step_ids.add(step_id)
        inputs = raw_step.get("input_artifacts")
        outputs = raw_step.get("output_artifacts")
        if not isinstance(inputs, list) or not inputs:
            raise ValueError(f"Transform step {step_id!r} has no inputs.")
        if not isinstance(outputs, list) or not outputs:
            raise ValueError(f"Transform step {step_id!r} has no outputs.")
        verified_inputs = [
            _verify_transform_artifact(
                value,
                label=f"transform step {step_id} input",
            )
            for value in inputs
            if isinstance(value, dict)
        ]
        verified_outputs = [
            _verify_transform_artifact(
                value,
                label=f"transform step {step_id} output",
            )
            for value in outputs
            if isinstance(value, dict)
        ]
        if len(verified_inputs) != len(inputs) or len(verified_outputs) != len(outputs):
            raise ValueError("Transform artifact inventories contain non-objects.")
        input_ids = [str(value.get("id") or "") for value in inputs]
        output_ids = [str(value.get("id") or "") for value in outputs]
        if (
            raw_step.get("input_refs") != input_ids
            or raw_step.get("output_refs") != output_ids
        ):
            raise ValueError(f"Transform step {step_id!r} reference IDs are stale.")
        for record in verified_inputs:
            key = _artifact_key(record)
            if key not in known_outputs:
                initial_inputs.add(key)
        known_outputs.update(_artifact_key(record) for record in verified_outputs)
        final_outputs = {_artifact_key(record) for record in verified_outputs}
        if raw_step.get("silent_omission_allowed") is not False:
            raise ValueError(f"Transform step {step_id!r} permits silent omission.")
        if str(raw_step.get("confirmation_status") or "") not in {
            "runtime_recorded",
            "confirmed",
            "not_applicable",
        }:
            raise ValueError(f"Transform step {step_id!r} is unresolved.")
    preregistered_keys = {
        (record["kind"], record["path"], record["sha256"]) for record in source_records
    }
    if initial_inputs != preregistered_keys:
        raise ValueError(
            "Transform-ledger initial inputs do not equal preregistered source evidence."
        )
    source_root = Path(str(ledger.get("source_root") or "")).expanduser().resolve()
    if source_root not in {Path(record["path"]) for record in source_records}:
        raise ValueError("Transform-ledger source_root was not preregistered.")
    expected = set(preregistration.get("expected_evidence") or [])
    mapping_application = payload.get("data_mapping_application")
    mapping_application = (
        mapping_application if isinstance(mapping_application, dict) else None
    )
    if "data_mapping" in expected:
        if mapping_application is None or witnessed_mapping is None:
            raise ValueError(
                "Preregistered data-mapping evidence is absent from the final manifest."
            )
        _verify_mapping_lineage(
            mapping_application,
            preregistered_sources=source_records,
            witnessed_mapping=witnessed_mapping,
            final_ledger=ledger,
        )
    elif mapping_application is not None:
        raise ValueError(
            "A data-mapped final project must preregister data_mapping evidence."
        )
    if mapping_application is None:
        raw_archive = payload.get("raw_archive")
        if not isinstance(raw_archive, dict):
            raise ValueError("Final manifest has no raw archive.")
        raw_source = Path(str(raw_archive.get("source") or "")).expanduser().resolve()
        raw_copy = Path(str(raw_archive.get("path") or "")).expanduser().resolve()
        matching = [
            record for record in source_records if Path(record["path"]) == raw_source
        ]
        if len(matching) != 1:
            raise ValueError(
                "Raw archive source does not equal one preregistered source."
            )
        archived = artifact_content_record(raw_copy)
        if (
            archived["kind"] != matching[0]["kind"]
            or archived["sha256"] != matching[0]["sha256"]
        ):
            raise ValueError(
                "Raw archive is not a byte-faithful copy of preregistered source evidence."
            )
    result = payload.get("result")
    result = result if isinstance(result, dict) else {}
    rendered_source_coverage: dict[str, Any] | None = None
    if mapping_application is not None:
        request = payload.get("request")
        if not isinstance(request, dict):
            raise ValueError(
                "Final mapped manifest has no authoritative request."
            )
        rendered_source_coverage = verify_rendered_mapping_source_coverage(
            result,
            mapping_application=mapping_application,
            request=request,
        )
        if result.get("rendered_source_coverage") != rendered_source_coverage:
            raise ValueError(
                "Final manifest renderer-source coverage is stale or "
                "self-attested rather than replayable."
            )
    snapshots = _verify_terminal_data_snapshots(
        result,
        final_outputs=final_outputs,
    )
    return {
        "kind": "sciplot_verified_source_lineage",
        "version": 1,
        "source_count": len(source_records),
        "initial_input_count": len(initial_inputs),
        "step_count": len(steps),
        "terminal_snapshot": snapshots[0],
        "terminal_snapshots": snapshots,
        "terminal_snapshot_count": len(snapshots),
        "transform_ledger_sha256": _canonical_sha256(ledger),
        "mapping_bound": mapping_application is not None,
        "rendered_source_coverage": rendered_source_coverage,
        "raw_archive_bound": mapping_application is None,
    }


def _qa_hashes(report: dict[str, Any], key: str) -> list[str]:
    values = report.get(key)
    if not isinstance(values, list):
        raise ValueError(f"Recomputed QA has no {key} list.")
    return sorted(
        str(value.get("sha256") or "") for value in values if isinstance(value, dict)
    )


def _expected_export_hashes(
    exports: dict[str, Any],
    export_format: str,
) -> list[str]:
    values = exports.get(export_format)
    if not isinstance(values, list):
        raise ValueError(f"Witness has no {export_format} exports.")
    return sorted(
        str(value.get("sha256") or "") for value in values if isinstance(value, dict)
    )


def _verify_pdf_tiff_physical_pair(
    report: dict[str, Any],
    *,
    expected_size_mm: tuple[float, float] | None,
) -> None:
    pdfs = [value for value in report.get("pdfs", []) if isinstance(value, dict)]
    tiffs = [value for value in report.get("tiffs", []) if isinstance(value, dict)]
    pdf_by_stem = {
        Path(str(value.get("path") or "")).stem.casefold(): value for value in pdfs
    }
    for tiff in tiffs:
        stem = Path(str(tiff.get("path") or "")).stem.casefold()
        if stem.endswith("_300dpi"):
            stem = stem[: -len("_300dpi")]
        pdf = pdf_by_stem.get(stem)
        if pdf is None:
            raise ValueError("Recomputed QA found an unpaired TIFF artifact.")
        dpi = tiff.get("dpi")
        if (
            not isinstance(dpi, list)
            or len(dpi) < 2
            or max(abs(float(dpi[0]) - 300.0), abs(float(dpi[1]) - 300.0)) > 1.0
        ):
            raise ValueError("Canonical TIFF is not a physical 300 dpi artifact.")
        pdf_size = pdf.get("physical_size_mm")
        tiff_size = tiff.get("physical_size_mm")
        if (
            not isinstance(pdf_size, list)
            or not isinstance(tiff_size, list)
            or len(pdf_size) != 2
            or len(tiff_size) != 2
            or any(value is None for value in tiff_size)
        ):
            raise ValueError("PDF/TIFF physical-size evidence is incomplete.")
        if (
            max(
                abs(float(pdf_size[index]) - float(tiff_size[index]))
                for index in range(2)
            )
            > 0.35
        ):
            raise ValueError("PDF/TIFF physical sizes do not match.")
        if (
            expected_size_mm is not None
            and max(
                abs(float(pdf_size[index]) - expected_size_mm[index])
                for index in range(2)
            )
            > 0.35
        ):
            raise ValueError("Exported artifact does not match the declared size.")


def verify_regular_production_qa(
    payload: dict[str, Any],
    *,
    document: Path,
    witnessed_exports: dict[str, Any],
) -> dict[str, Any]:
    output_root = Path(str(payload.get("output") or "")).expanduser().resolve()
    profile = payload.get("journal_profile")
    if not isinstance(profile, dict):
        raise ValueError("Final manifest has no publication QA profile.")
    request = payload.get("request")
    request = request if isinstance(request, dict) else {}
    fresh = run_qa(
        output_root,
        publication_profile=profile,
        strict_publication=bool(request.get("publication_strict")),
        veusz_documents=[document],
    )
    if fresh.get("status") != "passed":
        raise ValueError("Recomputed production artifact QA did not pass.")
    if _qa_hashes(fresh, "pdfs") != _expected_export_hashes(
        witnessed_exports,
        "pdf",
    ):
        raise ValueError("Recomputed PDF QA differs from witnessed exports.")
    if _qa_hashes(fresh, "tiffs") != _expected_export_hashes(
        witnessed_exports,
        "tiff_300",
    ):
        raise ValueError("Recomputed TIFF QA differs from witnessed exports.")
    publication = fresh.get("publication")
    if (
        not isinstance(publication, dict)
        or not isinstance(publication.get("veusz_document_audit"), dict)
        or publication.get("veusz_document_audit_error")
    ):
        raise ValueError("Exact-current VSZ could not be audited by Veusz.")
    _verify_pdf_tiff_physical_pair(fresh, expected_size_mm=None)
    return {
        "kind": "sciplot_recomputed_artifact_qa",
        "version": 1,
        "status": "passed",
        "report_sha256": _canonical_sha256(fresh),
        "pdfs": [
            {
                "path": value["path"],
                "sha256": value["sha256"],
                "size_bytes": value["size_bytes"],
                "physical_size_mm": value["physical_size_mm"],
            }
            for value in fresh["pdfs"]
        ],
        "tiffs": [
            {
                "path": value["path"],
                "sha256": value["sha256"],
                "size_bytes": value["size_bytes"],
                "dpi": value["dpi"],
                "physical_size_mm": value["physical_size_mm"],
            }
            for value in fresh["tiffs"]
        ],
        "veusz_document_audited": True,
    }


def verify_composition_production_qa(
    payload: dict[str, Any],
    *,
    document: Path,
    source_exports: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    paths = [
        Path(str(record["path"])).expanduser().resolve()
        for export_format in ("pdf", "tiff_300")
        for record in source_exports[export_format]
    ]
    parents = {path.parent for path in paths}
    if len(parents) != 1:
        raise ValueError("Composition source exports must share one artifact root.")
    fresh = run_qa(next(iter(parents)), veusz_documents=[document])
    if fresh.get("status") != "passed":
        raise ValueError("Recomputed composition artifact QA did not pass.")
    if _qa_hashes(fresh, "pdfs") != sorted(
        record["sha256"] for record in source_exports["pdf"]
    ):
        raise ValueError("Recomputed composition PDF QA hash mismatch.")
    if _qa_hashes(fresh, "tiffs") != sorted(
        record["sha256"] for record in source_exports["tiff_300"]
    ):
        raise ValueError("Recomputed composition TIFF QA hash mismatch.")
    size = payload.get("page_size_mm")
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(
            isinstance(value, bool) or not isinstance(value, int | float)
            for value in size
        )
    ):
        raise ValueError("Composition manifest has no valid physical page size.")
    _verify_pdf_tiff_physical_pair(
        fresh,
        expected_size_mm=(float(size[0]), float(size[1])),
    )
    return {
        "kind": "sciplot_recomputed_composition_qa",
        "version": 1,
        "status": "passed",
        "report_sha256": _canonical_sha256(fresh),
        "pdfs": fresh["pdfs"],
        "tiffs": fresh["tiffs"],
    }


def audit_native_composition_runtime(
    workspace_root: Path,
    *,
    variant_id: str,
) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "sciplot_core.veusz_worker",
            "audit-native-composition",
            str(workspace_root.expanduser().resolve()),
            "--variant",
            variant_id,
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
        env=veusz_worker_environment(),
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        raise RuntimeError(
            "Native Composition audit worker failed: "
            f"{detail[-1] if detail else completed.returncode}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Native Composition audit worker returned invalid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            "Native Composition audit worker returned a non-object payload."
        )
    return payload


__all__ = [
    "audit_native_composition_runtime",
    "artifact_content_record",
    "require_within",
    "verify_composition_production_qa",
    "verify_regular_production_qa",
    "verify_regular_source_lineage",
]
