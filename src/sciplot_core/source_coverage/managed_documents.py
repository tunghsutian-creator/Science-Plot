"""Bind every managed current VSZ to its prepared scientific data and CSVs."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_hashing import canonical_json_sha256

from sciplot_core.source_tables.parsing import (
    DECIMAL_ROUND_TRIP_ENCODING,
    DECIMAL_ROUND_TRIP_ENCODING_V1,
    SOURCE_NUMERIC_ENCODING_KEY,
)

from sciplot_core.source_coverage.artifacts import _result_path_list
from sciplot_core.source_coverage.inventory_paths import source_inventory_contains
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
    result: dict[str, Any], *, mapping_application: dict[str, Any] | None = None,
    native_audits: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify current values and identities, permitting source-preserving styling.

    This gate applies to every managed Studio project, independent of whether
    its intake needed an explicit DataMapping. Standalone VSZ exports have no
    source-data claim and do not enter this project publication function.
    """

    documents = _result_path_list(
        result, plural="veusz_documents", singular="veusz_document", label="VSZ files"
    )
    if native_audits is not None and set(native_audits) - {str(path.resolve()) for path in documents}:
        raise ValueError("Native scientific audits include a document outside this publication.")
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
            document_path=document, spec_path=spec_path, check_presentation=False,
            native_audit=native_audits.get(str(document.resolve())) if native_audits is not None else None,
        )
        source_records = _source_records(spec)
        snapshots = []
        for path, digest in source_records.items():
            if not source_inventory_contains(path, roots):
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


def source_records(spec: dict[str, Any]) -> dict[Path, str]:
    """Return the exact declared source inventory, rejecting missing/conflicting evidence."""
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


# Retained for source-coverage callers and documented test monkeypatches.
_source_records = source_records


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
    from sciplot_core.source_coverage.replicate_disclosure import verify_replicate_summary_request

    replicate_audit = verify_replicate_summary_request(request)
    encoding = spec.get(SOURCE_NUMERIC_ENCODING_KEY)
    if encoding not in (None, DECIMAL_ROUND_TRIP_ENCODING_V1, DECIMAL_ROUND_TRIP_ENCODING):
        raise ValueError("Unknown managed source numeric encoding.")
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
        origins = mapping if ((request.get("data_mapping_application") or {}).get("source_groups")
            or (request.get("categorical_binding") or {}).get("source_identity_version")) else None
        def candidate_signatures(candidate: dict[str, Any]) -> list[str] | None:
            rows = candidate.get("units")
            if candidate.get("status") != "passed" or not isinstance(rows, list) or not rows:
                return None
            if "performance_selection" in request:
                from sciplot_core.performance_comparison.selected_scatter import selected_source_evidence
                performance = spec.get("performance_comparison")
                if not isinstance(performance, dict) or canonical_json_sha256(selected_source_evidence(performance), allow_nan=False) != canonical_json_sha256(candidate.get("performance_selection_evidence"), allow_nan=False):
                    return None
            return [render_data_unit_signature({**unit, "source_artifacts": _remap_derived_source_artifacts(
                unit.get("source_artifacts"), private_to_original=mapping, label="managed prepared data",
            )}) for unit in rows]
        expected_signatures = [render_data_unit_signature(unit) for unit in expected]
        if encoding == DECIMAL_ROUND_TRIP_ENCODING_V1:
            # Only v1's actual old pandas parts vary: component coercion and
            # nonstandard accepted-text fallback. Ordinary valid decimals keep
            # round-trip parsing in every candidate; this is no legacy downgrade.
            for order in (True, False, None):
                try:
                    derived = _derive_prepared_data(request=request, private_sources=private_sources,
                        source_numeric_encoding=encoding, legacy_fused_digits=order, source_artifact_origins=origins)
                except ValueError:
                    continue
                if candidate_signatures(derived) == expected_signatures:
                    break
            else:
                raise ValueError("Managed specification values, axes, or sample identities do not reproduce from the exact prepared source tables.")
        else:
            derived = _derive_prepared_data(request=request, private_sources=private_sources,
                source_numeric_encoding=encoding or DECIMAL_ROUND_TRIP_ENCODING_V1, source_artifact_origins=origins)
        if "performance_selection" in request:
            from sciplot_core.performance_comparison.selected_scatter import selected_source_evidence
            performance = spec.get("performance_comparison")
            if not isinstance(performance, dict) or canonical_json_sha256(selected_source_evidence(performance), allow_nan=False) != canonical_json_sha256(derived.get("performance_selection_evidence"), allow_nan=False):
                raise ValueError("Selected performance source rows, missing masks, Metric IDs or unit declarations do not reproduce from the exact original table.")
        # Historical specs predate source-parser versioning. Reproduce their
        # original parser exactly, never relax the complete data signature or
        # rewrite their saved scientific authority. Versioned specs cannot
        # downgrade to this compatibility parser.
        if encoding is None and request.get("rule_id") != "performance_comparison":
            current_units = derived.get("units")
            if derived.get("status") == "passed" and isinstance(current_units, list) and current_units:
                if candidate_signatures(derived) != expected_signatures:
                    for fused_digits in (True, False):
                        derived = _derive_prepared_data(
                            request=request, private_sources=private_sources,
                            legacy_numeric_parser=True, legacy_fused_digits=fused_digits,
                            source_artifact_origins=origins,
                        )
                        if candidate_signatures(derived) == expected_signatures:
                            break
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
    return {"status": "passed", "unit_count": len(units), "unit_signatures": signatures,
            **({"replicate_disclosure_verification": replicate_audit} if replicate_audit is not None else {})}


def _derive_prepared_data(
    *, request: dict[str, Any], private_sources: list[Path],
    legacy_numeric_parser: bool = False,
    source_numeric_encoding: str = DECIMAL_ROUND_TRIP_ENCODING,
    legacy_fused_digits: bool | None = True,
    source_artifact_origins: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    from sciplot_core.studio_render import derive_terminal_render_data_contract

    if request.get("rule_id") != "performance_comparison":
        return derive_terminal_render_data_contract(
            request=request, terminal_sources=private_sources,
            legacy_numeric_parser=legacy_numeric_parser,
            source_numeric_encoding=source_numeric_encoding,
            legacy_fused_digits=legacy_fused_digits,
            **({"source_artifact_origins": source_artifact_origins} if source_artifact_origins is not None else {}),
        )
    from sciplot_core.performance_comparison import prepare_performance_comparison
    from sciplot_core.performance_comparison.selection import performance_selection_from_request
    from sciplot_core.performance_veusz.spec_builder import build_performance_veusz_spec

    if len(private_sources) != 1:
        raise ValueError(
            "Performance scientific data require one confirmed long table."
        )
    payload = prepare_performance_comparison(
        private_sources[0], template_id=str(request["template"]),
        selection=performance_selection_from_request(request),
        source_numeric_encoding=source_numeric_encoding,
        compatibility_fused_digits=legacy_fused_digits,
    )
    derived_spec = build_performance_veusz_spec(payload=payload, request=request)
    units = _spec_render_data_units(
        derived_spec,
        artifact_inventory={str(payload["source"]): str(payload["source_sha256"])},
    )
    result: dict[str, Any] = {"status": "passed", "units": units, "unit_count": len(units)}
    if "performance_selection" in request:
        from sciplot_core.performance_comparison.selected_scatter import selected_source_evidence
        result["performance_selection_evidence"] = selected_source_evidence(payload)
    return result
