"""Probe one mapped-data Studio lifecycle."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256

from sciplot_core.smoke.contracts import (
    EXPECTED_RULE_ID,
)


def _write_synthetic_ftir(path: Path) -> dict[str, Any]:
    """Write a deterministic contract fixture; this is never real-data evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[float, float]] = []
    for wavenumber in range(4000, 399, -50):
        transmittance = (
            97.5
            - 30.0 * math.exp(-(((wavenumber - 3300.0) / 145.0) ** 2))
            - 18.0 * math.exp(-(((wavenumber - 1715.0) / 75.0) ** 2))
            - 12.0 * math.exp(-(((wavenumber - 1250.0) / 95.0) ** 2))
            - 8.0 * math.exp(-(((wavenumber - 760.0) / 65.0) ** 2))
        )
        rows.append((float(wavenumber), transmittance))
    path.write_text(
        "\n".join(f"{x_value:.1f},{y_value:.6f}" for x_value, y_value in rows) + "\n",
        encoding="utf-8",
    )
    return {
        "kind": "sciplot_generated_contract_fixture",
        "semantic_family": EXPECTED_RULE_ID,
        "path": str(path),
        "sha256": file_sha256(path),
        "point_count": len(rows),
        "real_data_evidence": False,
        "evidence_tier": "generated_synthetic_contract_fixture",
    }


def _data_mapping_studio_lifecycle_probe(
    *,
    run_root: Path,
    source_path: Path,
    base_request_path: Path,
) -> dict[str, Any]:
    from sciplot_core.mapping_contract import (
        DataColumnMapping,
        DataMappingProposal,
        DataSourceReference,
    )
    from sciplot_core.data_mapping import (
        create_data_mapping_confirmation,
        execute_data_mapping_proposal,
        preview_data_mapping_proposal,
    )
    from sciplot_core.studio import (
        export_studio_document,
        prepare_studio_document,
        publish_studio_export_run,
    )

    raw_hash_before = file_sha256(source_path)
    proposal = DataMappingProposal(
        proposal_id="runtime-smoke-mapping",
        base_request_sha256=file_sha256(base_request_path),
        provider="runtime_smoke_typed_provider",
        sources=(
            DataSourceReference(
                source_id="runtime_ftir",
                relative_path=source_path.name,
                sha256=raw_hash_before,
                header_row=None,
                delimiter=",",
            ),
        ),
        columns=(
            DataColumnMapping(
                source_id="runtime_ftir",
                source_column_index=0,
                output_column="wavenumber",
                role="x",
            ),
            DataColumnMapping(
                source_id="runtime_ftir",
                source_column_index=1,
                output_column="transmittance",
                role="y",
            ),
        ),
        sample_labels={"runtime_ftir": "runtime_ftir"},
        unit_overrides={
            "wavenumber": "cm^-1",
            "transmittance": "%",
        },
        request_patch={
            "recipe": "auto",
            "rule_id": "ftir_spectrum",
            "template": "stacked_curve",
            "series_order": ["runtime_ftir"],
        },
        confidence=1.0,
        rationale="Synthetic runtime mapping lifecycle fixture.",
    )
    preview = preview_data_mapping_proposal(
        proposal,
        source_root=source_path.parent,
        request_path=base_request_path,
    )
    confirmation = create_data_mapping_confirmation(
        proposal,
        source_root=source_path.parent,
        request_path=base_request_path,
        output_root=run_root / "mapped_projects",
        confirmed_by="runtime_smoke_noninteractive_operator",
    )
    execution = execute_data_mapping_proposal(
        proposal,
        confirmation,
        source_root=source_path.parent,
        request_path=base_request_path,
        output_root=run_root / "mapped_projects",
    )
    project_dir = Path(str(execution["output_root"]))
    prepared = prepare_studio_document(project_dir)
    document_path = Path(str(prepared["document"]))
    exported = export_studio_document(
        document_path,
        formats=["pdf", "tiff_300"],
    )
    published = publish_studio_export_run(
        project_dir=project_dir,
        request_path=Path(str(prepared["request"])),
        document_path=document_path,
        exports=list(exported.get("exports") or []),
        export_document_sha256=str(exported["document_sha256"]),
    )
    manifest_path = Path(str(published["manifest"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    coverage = (
        manifest.get("data_mapping_coverage")
        if isinstance(manifest.get("data_mapping_coverage"), dict)
        else {}
    )
    transform = (
        manifest.get("transform_ledger")
        if isinstance(manifest.get("transform_ledger"), dict)
        else {}
    )
    operations = [
        str(step.get("operation") or "")
        for step in transform.get("steps", [])
        if isinstance(step, dict)
    ]
    raw_hash_after = file_sha256(source_path)
    passed = bool(
        preview.get("writes_performed") is False
        and execution.get("raw_inputs_unchanged") is True
        and raw_hash_before == raw_hash_after
        and Path(str(execution["request_candidate"])).name == "plot_request.json"
        and int(prepared.get("series_count") or 0) == 1
        and coverage.get("status") == "passed"
        and coverage.get("actual_series_labels") == ["runtime_ftir"]
        and operations[:2]
        == [
            "execute_confirmed_data_mapping_proposal",
            "extract_wavenumber_spectral_response_curve",
        ]
        and manifest.get("ready_to_use") is True
        and (manifest.get("qa") or {}).get("status") == "passed"
        and (manifest.get("delivery_package") or {}).get("complete") is True
    )
    return {
        "passed": passed,
        "preview_status": preview.get("status"),
        "execution": str(project_dir / "execution.json"),
        "request_candidate": execution.get("request_candidate"),
        "document": str(document_path),
        "manifest": str(manifest_path),
        "raw_hash_before": raw_hash_before,
        "raw_hash_after": raw_hash_after,
        "series_count": prepared.get("series_count"),
        "coverage": coverage,
        "operations": operations,
        "qa_status": (manifest.get("qa") or {}).get("status"),
        "publication_status": ((manifest.get("qa") or {}).get("publication") or {}).get(
            "status"
        ),
        "delivery_complete": (manifest.get("delivery_package") or {}).get("complete"),
        "ready_to_use": manifest.get("ready_to_use"),
        "real_data_evidence": False,
    }


def _transform_parameters(result: dict[str, Any]) -> dict[str, Any]:
    steps = (
        result.get("transform_steps")
        if isinstance(result.get("transform_steps"), list)
        else []
    )
    first = steps[0] if steps and isinstance(steps[0], dict) else {}
    parameters = first.get("parameters")
    return parameters if isinstance(parameters, dict) else {}
