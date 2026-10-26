"""Recover exact registered FigureTask tables for managed data delivery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.source_locations import literal_source_path, resolve_source_path
from sciplot_core.data_mapping.source_projection import verified_mapping_source_groups
from sciplot_core.figure_plan import resolved_figure_plan_from_payload
from sciplot_core.source_coverage.inventory_paths import source_inventory_contains
from sciplot_core.source_coverage.file_snapshots import (
    _assert_snapshot_current,
    _stable_file_snapshot,
)
from sciplot_core.source_coverage.managed_documents import (
    _source_records,
    _verify_prepared_data,
)
from sciplot_core.studio_core.figure_task_evidence import (
    validate_veusz_spec_figure_task,
)


def registered_task_snapshot_sources(
    *,
    request: dict[str, Any],
    project_dir: Path,
    documents: list[Path],
    existing_sources: list[Path],
    data_mapping_application: dict[str, Any] | None = None,
    source_versions: dict[Path, str] | None = None,
) -> list[Path]:
    """Include task tables only after their persisted task and data checks.

    Preparation's private worker seal is not a persisted certificate. Here the
    evidence is the validated FigurePlan, recorded source hash, and reproducible
    prepared table -> spec data contract. The caller separately verifies raw
    source fingerprints and preparation lineage.
    """

    plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    additions: list[Path] = []
    verified_versions: dict[Path, str] = {}
    root = Path(literal_source_path(project_dir))
    for document in documents:
        spec_path = (
            document.with_name("spec.json")
            if document.name == "document.vsz"
            else document.with_suffix(".spec.json")
        )
        spec_snapshot = _stable_file_snapshot(spec_path, label="registered task spec")
        spec = json.loads(spec_snapshot["bytes"])
        records = _source_records(spec)
        for path, digest in records.items():
            if path in verified_versions and verified_versions[path] != digest:
                raise ValueError("Registered task documents disagree on a prepared source version.")
            verified_versions[path] = digest
        extra = [
            path
            for path in records
            if not source_inventory_contains(path, existing_sources)
        ]
        if not extra:
            _assert_snapshot_current(spec_snapshot, label="registered task spec", expected_sha256=spec_snapshot["sha256"])
            continue
        source_request = spec.get("source_request")
        if plan is None or not isinstance(source_request, dict):
            raise ValueError(
                "Additional plotted tables require a registered FigureTask."
            )
        task_payload = source_request.get("resolved_figure_task")
        task = next(
            (task for task in plan.tasks if task.to_payload() == task_payload), None
        )
        if task is None:
            raise ValueError(
                "Additional plotted table task does not match the selected FigurePlan."
            )
        validate_veusz_spec_figure_task(
            spec, expected=task, source="managed plotted table"
        )
        input_value = source_request.get("input")
        if not isinstance(input_value, str) or not input_value:
            raise ValueError("Registered task table has no exact source input.")
        input_path = Path(input_value).expanduser()
        if input_path.resolve() != input_path or not resolve_source_path(input_path).is_file():
            raise ValueError("Registered task table input is not a canonical file.")
        groups = verified_mapping_source_groups(
            {"data_mapping_application": data_mapping_application}, replicates=True,
        ) if data_mapping_application else []
        if data_mapping_application and groups:
            _verify_registered_mapping_sources(
                spec=spec,
                application=data_mapping_application,
                input_path=input_path,
                records=records,
                groups=groups,
            )
            _assert_snapshot_current(spec_snapshot, label="registered task spec", expected_sha256=spec_snapshot["sha256"])
            additions.extend(extra)
            continue
        if len(records) != 1 or len(extra) != 1:
            raise ValueError(
                "Registered task table and rendered source inventory disagree."
            )
        source_path = extra[0]
        for path in (input_path, source_path):
            if not path.is_relative_to(root / "studio" / "processed"):
                raise ValueError(
                    "Registered task table is outside its private processed directory."
                )
            candidate = path
            while candidate != root:
                if candidate.is_symlink():
                    raise ValueError(
                        "Registered task table cannot traverse a symbolic link."
                    )
                candidate = candidate.parent
        input_snapshot = _stable_file_snapshot(
            input_path, label="registered task input"
        )
        snapshot = _stable_file_snapshot(source_path, label="registered task table", expected_sha256=records[source_path])
        if snapshot["sha256"] != records[source_path]:
            raise ValueError("Registered task table changed after rendering.")
        # Some semantic preparation writes an identical canonical table under
        # another filename. Permit that exact copy, not an unproved transform.
        if input_snapshot["sha256"] != snapshot["sha256"]:
            raise ValueError(
                "Registered task input and plotted table are not identical; "
                "a derived-table source proof is required."
            )
        _verify_prepared_data(spec, [snapshot])
        _assert_snapshot_current(snapshot, label="registered task table", expected_sha256=records[source_path])
        _assert_snapshot_current(input_snapshot, label="registered task input", expected_sha256=input_snapshot["sha256"])
        _assert_snapshot_current(spec_snapshot, label="registered task spec", expected_sha256=spec_snapshot["sha256"])
        additions.append(source_path)
    if source_versions is not None:
        source_versions.update(verified_versions)
    return list(dict.fromkeys([*existing_sources, *additions]))


def _verify_registered_mapping_sources(
    *,
    spec: dict[str, Any],
    application: dict[str, Any],
    input_path: Path,
    records: dict[Path, str],
    groups: list[dict[str, Any]],
) -> None:
    """Admit only this execution's complete, original-domain raw group tables."""
    from sciplot_core.data_mapping.execution_loading import load_data_mapping_execution

    source_request = spec["source_request"]
    if source_request.get("data_mapping_application") != application:
        raise ValueError("Registered task mapping differs from the current verified mapping.")
    # The existing execution owner reproduces raw physical selectors, complete
    # rows/null masks, mapped bytes and the composite adapter input. Display
    # labels or an unverified source_artifacts list cannot grant source access.
    execution = load_data_mapping_execution(application["execution"])
    from sciplot_core.data_mapping.execution_inputs import mapping_read_json

    seed = mapping_read_json(Path(execution["request_seed"]))
    effective_input = Path(execution["effective_input"]).resolve()
    if execution.get("handoff_allowed") is not True or any((
        input_path != Path(seed["input"]).resolve(),
        str(input_path) != application.get("original_input"),
        str(effective_input) != application.get("effective_input"),
    )):
        raise ValueError("Registered task input differs from its confirmed mapping.")
    expected = {Path(group["path"]).resolve(): group["sha256"] for group in groups}
    if not expected or records != expected:
        raise ValueError("Registered task sources differ from the complete verified mapping groups.")
    input_snapshot = _stable_file_snapshot(input_path, label="registered mapping input")
    effective_snapshot = _stable_file_snapshot(effective_input, label="registered mapping composite")
    snapshots = []
    for path, digest in records.items():
        snapshot = _stable_file_snapshot(path, label="registered mapping group", expected_sha256=digest)
        if snapshot["sha256"] != digest:
            raise ValueError("Registered mapping group changed after rendering.")
        snapshots.append(snapshot)
    _verify_prepared_data(spec, snapshots)
    for snapshot, digest in zip(snapshots, records.values(), strict=True):
        _assert_snapshot_current(snapshot, label="registered mapping group", expected_sha256=digest)
    _assert_snapshot_current(input_snapshot, label="registered mapping input", expected_sha256=input_snapshot["sha256"])
    _assert_snapshot_current(effective_snapshot, label="registered mapping composite", expected_sha256=effective_snapshot["sha256"])
