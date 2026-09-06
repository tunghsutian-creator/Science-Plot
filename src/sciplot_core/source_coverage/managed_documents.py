"""Bind every managed current VSZ to its prepared scientific data and CSVs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.source_coverage.artifacts import _result_path_list
from sciplot_core.source_coverage.document_audit import _audit_exact_document_data
from sciplot_core.source_coverage.evaluate import evaluate_mapping_source_coverage
from sciplot_core.source_coverage.file_snapshots import (
    _assert_snapshot_current,
    _stable_file_snapshot,
)
from sciplot_core.source_coverage.spec_units import (
    _spec_render_data_units,
    render_data_unit_signature,
)


def verify_managed_document_sources(
    result: dict[str, Any], *, mapping_application: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Verify current values and identities, permitting source-preserving styling.

    This gate applies to every managed Studio project, independent of whether
    its intake needed an explicit DataMapping. Standalone VSZ exports have no
    source-data claim and do not enter this project publication function.
    """

    documents = _result_path_list(
        result, plural="veusz_documents", singular="veusz_document", label="VSZ files"
    )
    roots = _result_path_list(
        result,
        plural="data_snapshot_sources",
        singular="data_snapshot_source",
        label="prepared source files",
    )
    audits: list[dict[str, Any]] = []
    rendered_units = []
    artifact_inventory = {}
    for document in documents:
        spec_path = (
            document.with_name("spec.json")
            if document.name == "document.vsz"
            else document.with_suffix(".spec.json")
        )
        audit, spec = _audit_exact_document_data(
            document_path=document, spec_path=spec_path, check_presentation=False
        )
        source_records = _source_records(spec)
        snapshots = []
        for path, digest in source_records.items():
            if not any(
                path == root or root.is_dir() and path.is_relative_to(root)
                for root in roots
            ):
                raise ValueError(
                    f"Managed Veusz data cite a source outside the delivery data inventory: {path}"
                )
            snapshot = _stable_file_snapshot(path, label="managed prepared source")
            if snapshot["sha256"] != digest:
                raise ValueError(
                    f"Managed prepared source changed after rendering: {path}"
                )
            snapshots.append(snapshot)
        audit["prepared_source_derivation"] = _verify_prepared_data(spec, snapshots)
        inventory = {str(item["path"]): str(item["sha256"]) for item in snapshots}
        artifact_inventory.update(inventory)
        for index, unit in enumerate(
            _spec_render_data_units(spec, artifact_inventory=inventory)
        ):
            rendered_units.append(
                {
                    "identity": f"document_{len(audits)}:unit_{index}",
                    "kind": unit["kind"],
                    "source_artifacts": unit["source_artifacts"],
                }
            )
        for snapshot in snapshots:
            _assert_snapshot_current(snapshot, label="managed prepared source")
        audits.append(audit)
    payload = {
        "kind": "sciplot_managed_document_source_verification",
        "version": 1,
        "status": "passed",
        "document_count": len(audits),
        "documents": audits,
    }
    if mapping_application is not None:
        payload["mapping_source_coverage"] = evaluate_mapping_source_coverage(
            rendered_units,
            mapping_application=mapping_application,
            template=str(result.get("template") or ""),
            allow_downstream_sources=True,
            artifact_inventory=artifact_inventory,
        )
    return payload


def _source_records(spec: dict[str, Any]) -> dict[Path, str]:
    units = list(spec.get("series") or [])
    if isinstance(spec.get("scalar_field"), dict):
        units.append(spec["scalar_field"])
    records: dict[Path, str] = {}
    for unit in units:
        artifacts = unit.get("source_artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError(
                "Managed scientific data require source artifacts for every series."
            )
        for artifact in artifacts:
            if not isinstance(artifact, dict) or not artifact.get("path"):
                raise ValueError(
                    "Managed scientific data contain an invalid source artifact."
                )
            path = Path(artifact["path"]).expanduser().resolve()
            digest = str(artifact.get("sha256") or "")
            if path in records and records[path] != digest:
                raise ValueError(
                    "Managed scientific data repeat conflicting source hashes."
                )
            records[path] = digest
    if not records:
        raise ValueError("Managed scientific data have no prepared source inventory.")
    return records


def _verify_prepared_data(
    spec: dict[str, Any], snapshots: list[dict[str, Any]]
) -> dict[str, Any]:
    """Re-derive the immutable generated data spec from exact private tables."""

    import os
    import tempfile

    from sciplot_core.source_coverage.derivation import _remap_derived_source_artifacts
    from sciplot_core.source_coverage.file_snapshots import _write_private_snapshot

    request = spec.get("source_request")
    if not isinstance(request, dict):
        raise ValueError("Managed scientific data have no prepared source request.")
    inventory = {str(item["path"]): item["sha256"] for item in snapshots}
    expected = _spec_render_data_units(spec, artifact_inventory=inventory)
    with tempfile.TemporaryDirectory(prefix="sciplot_managed_source_audit_") as temp:
        private_root = Path(temp)
        os.chmod(private_root, 0o700)
        private_sources = []
        mapping = {}
        for index, snapshot in enumerate(snapshots):
            source = Path(snapshot["path"])
            parent = private_root / str(index)
            parent.mkdir(mode=0o700)
            private = parent / source.name
            _write_private_snapshot(private, snapshot["bytes"])
            private_sources.append(private)
            mapping[str(private.resolve())] = {
                "path": str(source),
                "sha256": snapshot["sha256"],
            }
        derived = _derive_prepared_data(
            request=request, private_sources=private_sources
        )
        units = derived.get("units")
        if (
            derived.get("status") != "passed"
            or not isinstance(units, list)
            or not units
        ):
            raise ValueError("Managed prepared data derivation did not pass.")
        for unit in units:
            unit["source_artifacts"] = _remap_derived_source_artifacts(
                unit.get("source_artifacts"),
                private_to_original=mapping,
                label="managed prepared data",
            )
    signatures = [render_data_unit_signature(unit) for unit in units]
    if signatures != [render_data_unit_signature(unit) for unit in expected]:
        raise ValueError(
            "Managed specification values, axes, or sample identities do not "
            "reproduce from the exact prepared source tables."
        )
    return {"status": "passed", "unit_count": len(units), "unit_signatures": signatures}


def _derive_prepared_data(
    *, request: dict[str, Any], private_sources: list[Path]
) -> dict[str, Any]:
    from sciplot_core.studio_render import derive_terminal_render_data_contract

    if request.get("rule_id") != "performance_comparison":
        return derive_terminal_render_data_contract(
            request=request, terminal_sources=private_sources
        )
    from sciplot_core.performance_comparison import prepare_performance_comparison
    from sciplot_core.performance_veusz.spec_builder import build_performance_veusz_spec

    if len(private_sources) != 1:
        raise ValueError(
            "Performance scientific data require one confirmed long table."
        )
    payload = prepare_performance_comparison(
        private_sources[0], template_id=str(request["template"])
    )
    derived_spec = build_performance_veusz_spec(payload=payload, request=request)
    units = _spec_render_data_units(
        derived_spec,
        artifact_inventory={str(payload["source"]): str(payload["source_sha256"])},
    )
    return {"status": "passed", "units": units, "unit_count": len(units)}
