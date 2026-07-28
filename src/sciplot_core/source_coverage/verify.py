"""Verify a rendered result against its mapping application."""

from __future__ import annotations

from typing import Any

from sciplot_core.source_coverage.artifacts import (
    _result_path_list,
    _terminal_file_snapshots,
)

from sciplot_core.source_coverage.file_snapshots import (
    _assert_snapshot_current,
)

from sciplot_core.source_coverage.document_audit import (
    _audit_exact_document_data,
)

from sciplot_core.source_coverage.spec_units import (
    _spec_render_data_units,
)

from sciplot_core.source_coverage.terminal_requests import (
    _declared_terminal_render_requests,
)

from sciplot_core.source_coverage.derivation import (
    _terminal_render_derivation,
)

from sciplot_core.source_coverage.evaluate import (
    evaluate_mapping_source_coverage,
)


def verify_rendered_mapping_source_coverage(
    result: dict[str, Any],
    *,
    mapping_application: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError(
            "Mapped render source verification requires the authoritative request."
        )
    spec_paths = _result_path_list(
        result,
        plural="veusz_specs",
        singular="veusz_spec",
        label="Veusz specification files",
    )
    document_paths = _result_path_list(
        result,
        plural="veusz_documents",
        singular="veusz_document",
        label="exact-current Veusz document files",
    )
    if len(document_paths) != len(spec_paths):
        raise ValueError("Mapped render Veusz document/specification counts disagree.")
    terminal_snapshots = _terminal_file_snapshots(result)
    terminal_outputs = [
        {
            "path": str(snapshot["path"]),
            "sha256": str(snapshot["sha256"]),
        }
        for snapshot in terminal_snapshots
    ]
    terminal_artifact_inventory = {
        record["path"]: record["sha256"] for record in terminal_outputs
    }
    declared_terminal_requests = _declared_terminal_render_requests(
        result,
        spec_count=len(spec_paths),
    )

    spec_artifacts: list[dict[str, Any]] = []
    document_artifacts: list[dict[str, Any]] = []
    document_data_audits: list[dict[str, Any]] = []
    rendered_units: list[dict[str, Any]] = []
    spec_unit_groups: list[list[dict[str, Any]]] = []
    templates: set[str] = set()
    for spec_index, (spec_path, document_path) in enumerate(
        zip(spec_paths, document_paths, strict=True),
        start=1,
    ):
        if not spec_path.is_file():
            raise FileNotFoundError(
                f"Mapped render Veusz specification not found: {spec_path}"
            )
        if not document_path.is_file():
            raise FileNotFoundError(
                f"Mapped render Veusz document not found: {document_path}"
            )
        document_audit, spec = _audit_exact_document_data(
            document_path=document_path,
            spec_path=spec_path,
        )
        template = str(spec.get("template") or result.get("template") or "")
        templates.add(template)
        spec_artifacts.append(dict(document_audit["spec"]))
        document_artifacts.append(dict(document_audit["document"]))
        document_data_audits.append(document_audit)
        spec_unit_groups.append(
            _spec_render_data_units(
                spec,
                artifact_inventory=terminal_artifact_inventory,
            )
        )
        series = spec.get("series")
        if not isinstance(series, list):
            raise ValueError(
                f"Mapped render Veusz specification has no series list: {spec_path}"
            )
        for series_index, raw_series in enumerate(series, start=1):
            if not isinstance(raw_series, dict):
                raise ValueError(
                    f"Mapped render series {series_index} is not an object."
                )
            rendered_units.append(
                {
                    "identity": (
                        f"spec_{spec_index}:series:"
                        f"{str(raw_series.get('name') or series_index)}"
                    ),
                    "kind": "series",
                    "source_artifacts": raw_series.get("source_artifacts"),
                }
            )
        scalar = spec.get("scalar_field")
        if isinstance(scalar, dict):
            rendered_units.append(
                {
                    "identity": f"spec_{spec_index}:scalar_field",
                    "kind": "scalar_field",
                    "source_artifacts": scalar.get("source_artifacts"),
                }
            )
    coverage = evaluate_mapping_source_coverage(
        rendered_units,
        mapping_application=mapping_application,
        template=",".join(sorted(templates)),
        allow_downstream_sources=True,
        artifact_inventory=terminal_artifact_inventory,
    )
    terminal_data_derivation = _terminal_render_derivation(
        result=result,
        authoritative_request=request,
        declared_requests=declared_terminal_requests,
        terminal_snapshots=terminal_snapshots,
        spec_unit_groups=spec_unit_groups,
    )
    terminal_keys = {(record["path"], record["sha256"]) for record in terminal_outputs}
    rendered_keys = {
        (record["path"], record["sha256"])
        for unit in coverage["rendered_units"]
        for record in unit["source_artifacts"]
    }
    if rendered_keys - terminal_keys:
        paths = ", ".join(path for path, _ in sorted(rendered_keys - terminal_keys))
        raise ValueError(
            "Rendered Veusz data cite sources outside the terminal plotted "
            f"snapshot inventory: {paths}"
        )
    terminal_contribution_counts: list[dict[str, Any]] = []
    for record in terminal_outputs:
        key = (record["path"], record["sha256"])
        count = sum(
            key
            in {
                (artifact["path"], artifact["sha256"])
                for artifact in unit["source_artifacts"]
            }
            for unit in coverage["rendered_units"]
        )
        if count < 1:
            raise ValueError(
                "A terminal plotted data snapshot has no exact-current Veusz "
                f"consumer: {record['path']}"
            )
        terminal_contribution_counts.append({**record, "rendered_unit_count": count})
    for index, snapshot in enumerate(terminal_snapshots, start=1):
        _assert_snapshot_current(
            snapshot,
            label=f"terminal plotted data snapshot {index}",
        )
    return {
        **coverage,
        "terminal_outputs": terminal_outputs,
        "terminal_output_count": len(terminal_outputs),
        "terminal_contribution_counts": terminal_contribution_counts,
        "spec_artifacts": sorted(
            spec_artifacts,
            key=lambda record: (record["path"], record["sha256"]),
        ),
        "spec_count": len(spec_artifacts),
        "document_artifacts": sorted(
            document_artifacts,
            key=lambda record: (record["path"], record["sha256"]),
        ),
        "document_count": len(document_artifacts),
        "document_data_audits": document_data_audits,
        "terminal_data_derivation": terminal_data_derivation,
    }
