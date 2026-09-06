"""Read the independently bound evidence for a single visible VSZ recovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import resolved_figure_plan_from_payload
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.launchers.delivery_binding import delivery_binding_from_content
from sciplot_core.launchers.delivery_inspection import (
    inspect_delivery_launcher_contract,
)
from sciplot_core.source_coverage.managed_documents import _source_records
from sciplot_core.studio_core.delivery_target import _managed_project
from sciplot_core.studio_core.figure_set_state import _read_studio_figure_set


class RecoveryBlocked(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def canonical_path(value: Path) -> Path:
    path = value.expanduser().absolute()
    if any(member.is_symlink() for member in (path, *path.parents)):
        raise RecoveryBlocked(
            "symbolic_link", f"Recovery cannot follow a symlink: {path}"
        )
    return path.resolve()


def _object(path: Path) -> dict[str, Any]:
    canonical_path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RecoveryBlocked("invalid_metadata", f"Expected a JSON object: {path}")
    return payload


def _files(root: Path) -> list[Path]:
    canonical_path(root)
    if root.is_file():
        return [root]
    if not root.is_dir():
        raise RecoveryBlocked("missing_source", f"Required source is missing: {root}")
    files = []
    for path in sorted(root.rglob("*")):
        canonical_path(path)
        if path.is_file():
            files.append(path)
    return files


def _last_bound_delivery(
    project: Path, root: Path, primary: str, baseline: str
) -> tuple[Path, dict[str, Any]]:
    # Bind by the visible document's exact last-delivered hash, never by a
    # merely newer failed run or an arbitrary last_run pointer.
    for path in sorted((project / "runs").glob("studio_*/manifest.json"), reverse=True):
        try:
            manifest = _object(path)
        except (OSError, ValueError):
            continue
        delivery = manifest.get("delivery_package")
        if (
            manifest.get("ready_to_use") is not True
            or not isinstance(delivery, dict)
            or delivery.get("complete") is not True
            or delivery.get("path") != str(root)
            or manifest.get("request_path") != str(project / "plot_request.json")
        ):
            continue
        documents = delivery.get("project_documents")
        if not isinstance(documents, list) or len(documents) != 1:
            continue
        document = documents[0]
        if (
            isinstance(document, dict)
            and document.get("path") == str(root / "project" / primary)
            and document.get("delivery_sha256") == baseline
            and document.get("source_sha256") == baseline
            and document.get("source") == str(path.parent / "studio" / "document.vsz")
        ):
            return path, manifest
    raise RecoveryBlocked(
        "delivery_evidence_missing",
        "No successful project run binds this visible document's delivery baseline.",
    )


def _raw_inventory(project: Path, request: dict[str, Any]) -> dict[str, str]:
    model = request.get("study_model")
    samples = model.get("samples", []) if isinstance(model, dict) else []
    expected: dict[str, str] = {}
    for sample in samples:
        for replicate in sample.get("replicates", []):
            source = replicate.get("source_file")
            if not isinstance(source, dict):
                continue
            value, digest = source.get("raw_path"), source.get("sha256")
            if not isinstance(value, str) or not isinstance(digest, str):
                continue
            path = canonical_path(Path(value))
            if not path.is_relative_to(project / "raw"):
                raise RecoveryBlocked(
                    "raw_source_unbound", "Raw source is outside its project archive."
                )
            expected[str(path)] = digest
    actual = {str(path): file_sha256(path) for path in _files(project / "raw")}
    if not expected or actual != expected:
        raise RecoveryBlocked(
            "raw_source_changed",
            "The project's raw source archive changed since delivery.",
        )
    return actual


def capture_recovery_state(project_dir: Path, candidate: Path | None) -> dict[str, Any]:
    """Require current ownership, one figure and unchanged delivery/source evidence."""
    project = canonical_path(project_dir)
    request_path = project / "plot_request.json"
    request = _object(request_path)
    root_value = request.get("delivery_output")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        raise RecoveryBlocked(
            "delivery_unbound", "This project has no absolute visible delivery binding."
        )
    root = canonical_path(Path(root_value))
    launcher = root / "Open_in_Veusz.command"
    canonical_path(launcher)
    if inspect_delivery_launcher_contract(root).get("ready") is not True:
        raise RecoveryBlocked(
            "invalid_launcher",
            "The visible delivery launcher is not a valid SciPlot launcher.",
        )
    binding = delivery_binding_from_content(launcher.read_text(encoding="utf-8"))
    if binding is None or _managed_project(root, binding) != project:
        raise RecoveryBlocked(
            "foreign_delivery",
            "The visible delivery no longer belongs to this project.",
        )
    if len(binding.documents) != 1 or binding.documents[0][0] != binding.primary:
        raise RecoveryBlocked(
            "multiple_figures", "Recovery currently requires a single-figure delivery."
        )
    visible = canonical_path(root / "project" / binding.primary)
    if candidate is not None and canonical_path(candidate) != visible:
        raise RecoveryBlocked(
            "foreign_candidate", "Select only this delivery's bound primary VSZ."
        )
    if _files(root / "project") != [visible]:
        raise RecoveryBlocked(
            "unrecorded_document",
            "The visible project directory contains unrecorded files.",
        )
    document = canonical_path(project / "studio" / "document.vsz")
    spec_path = canonical_path(project / "studio" / "spec.json")
    baseline = binding.documents[0][1]
    manifest_path, manifest = _last_bound_delivery(
        project, root, binding.primary, baseline
    )
    run = manifest_path.parent
    baseline_request_path = run / "request_snapshot.json"
    baseline_request = _object(baseline_request_path)
    if baseline_request != manifest.get("request") or request != baseline_request:
        raise RecoveryBlocked(
            "request_changed",
            "The project request changed since this delivery; recovery is blocked.",
        )
    plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    if plan is None or len(plan.tasks) != 1 or not plan.source_sha256:
        raise RecoveryBlocked(
            "source_evidence_missing",
            "Recovery requires a single prepared FigurePlan with source evidence.",
        )
    registry = _read_studio_figure_set(
        project, expected_plan=plan, require_ready_artifacts=True
    )
    if registry is None or len(registry.get("figures", [])) != 1:
        raise RecoveryBlocked(
            "figure_registry_changed",
            "The project's single-figure registry is missing or inconsistent.",
        )
    source = canonical_path(Path(str(binding.source)))
    _files(source)
    source_hash = source_tree_sha256(source)
    archive_value = manifest.get("raw_archive")
    archive = archive_value.get("path") if isinstance(archive_value, dict) else None
    if not isinstance(archive, str) or not canonical_path(Path(archive)).is_relative_to(
        run / "raw"
    ):
        raise RecoveryBlocked(
            "source_evidence_missing",
            "The delivered run has no private source snapshot.",
        )
    _files(Path(archive))
    if (
        source_hash != plan.source_sha256
        or source_tree_sha256(Path(archive)) != source_hash
    ):
        raise RecoveryBlocked(
            "source_changed",
            "The source differs from the prepared and delivered source snapshot.",
        )
    raw = _raw_inventory(project, baseline_request)
    archived_document = canonical_path(run / "studio" / "document.vsz")
    archived_spec = canonical_path(run / "studio" / "spec.json")
    if file_sha256(archived_document) != baseline or file_sha256(
        spec_path
    ) != file_sha256(archived_spec):
        raise RecoveryBlocked(
            "prepared_evidence_changed",
            "The delivered document or current prepared specification changed.",
        )
    spec = _object(spec_path)
    prepared: dict[str, str] = {}
    for path, expected in _source_records(spec).items():
        canonical_path(path)
        actual = file_sha256(path)
        if actual != expected:
            raise RecoveryBlocked(
                "prepared_source_changed", f"A prepared source changed: {path}"
            )
        prepared[str(path)] = actual
    registry_path = project / "studio" / "figure_set.json"
    return {
        "project": str(project),
        "document": str(document),
        "candidate": str(visible),
        "delivery": str(root),
        "evidence": str(manifest_path),
        "hashes": {
            "baseline": baseline,
            "document": file_sha256(document),
            "candidate": file_sha256(visible),
        },
        "fingerprints": {
            "request": file_sha256(request_path),
            "launcher": file_sha256(launcher),
            "registry": file_sha256(registry_path),
            "spec": file_sha256(spec_path),
            "evidence": file_sha256(manifest_path),
            "evidence_request": file_sha256(baseline_request_path),
            "evidence_spec": file_sha256(archived_spec),
            "source": source_hash,
            "raw_files": raw,
            "prepared_files": prepared,
        },
    }
