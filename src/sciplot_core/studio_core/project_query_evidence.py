"""Compact saved-byte indicators; these are not a new scientific readiness gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.delivery.package_validation import verify_delivery_package
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.source_coverage.managed_documents import _source_records
from sciplot_core.studio_core.project_query_paths import (
    bound_delivery_project,
    canonical_path,
    read_object,
)


def _indicator(current: bool | None, **fields: Any) -> dict[str, Any]:
    return {
        "status": "unknown" if current is None else "current" if current else "stale",
        "current": current,
        **fields,
    }


def _tree_hash(path: Path) -> str | None:
    canonical_path(path)
    if path.is_dir():
        for member in path.rglob("*"):
            canonical_path(member)
    return source_tree_sha256(path)


def source_indicators(
    project: Path, request: dict[str, Any], figures: list[dict[str, Any]]
) -> dict[str, Any]:
    value = request.get("input")
    source = Path(value).expanduser() if isinstance(value, str) and value else None
    if source is not None and not source.is_absolute():
        source = project / source
    plan = request.get("resolved_figure_plan") or {}
    expected = plan.get("source_sha256")
    actual = _tree_hash(source) if source is not None else None
    input_state = _indicator(
        actual == expected if expected else None,
        path=str(source) if source else None,
        sha256=actual,
        expected_sha256=expected,
    )
    prepared: dict[str, str] = {}
    prepared_error = None
    try:
        for figure in figures:
            if figure["status"] != "ready":
                raise ValueError(
                    "Some selected figures have no prepared specification."
                )
            spec = read_object(Path(figure["spec"]))
            units = [*spec.get("series", []), spec.get("scalar_field") or {}]
            for unit in units:
                for record in unit.get("source_artifacts", []):
                    canonical_path(Path(record["path"]))
            for path, digest in _source_records(spec).items():
                canonical_path(path)
                if str(path) in prepared and prepared[str(path)] != digest:
                    raise ValueError("Prepared figures disagree about a source hash.")
                prepared[str(path)] = digest
    except (OSError, ValueError, TypeError, KeyError) as exc:
        prepared_error = str(exc)
    mismatches = [
        path
        for path, digest in prepared.items()
        if existing_file_sha256(Path(path)) != digest
    ]
    prepared_state = _indicator(
        None if prepared_error or not prepared else not mismatches,
        file_count=len(prepared),
        changed_paths=mismatches,
        error=prepared_error,
    )
    raw: dict[str, str] = {}
    model = request.get("study_model") or {}
    for sample in model.get("samples", []):
        for replicate in sample.get("replicates", []):
            record = replicate.get("source_file") or {}
            value, raw_digest = record.get("raw_path"), record.get("sha256")
            if isinstance(value, str) and isinstance(raw_digest, str):
                path = canonical_path(Path(value))
                raw[str(path)] = raw_digest
    raw_mismatches = [
        path
        for path, digest in raw.items()
        if existing_file_sha256(Path(path)) != digest
    ]
    raw_state = _indicator(
        not raw_mismatches if raw else None,
        file_count=len(raw),
        changed_paths=raw_mismatches,
    )
    values = [input_state["current"], prepared_state["current"]]
    if raw:
        values.append(raw_state["current"])
    current = (
        False if False in values else True if all(v is True for v in values) else None
    )
    return _indicator(
        current,
        scope="recorded_source_file_hashes",
        scientific_audit_evaluated=False,
        input=input_state,
        prepared=prepared_state,
        raw=raw_state,
    )


def latest_run(project: Path) -> tuple[Path | None, dict[str, Any], str | None]:
    candidates = sorted(
        (project / "runs").glob("studio_*/manifest.json"),
        key=lambda p: (
            int(p.parent.name[7:]) if p.parent.name[7:].isdigit() else -1,
            p.parent.name,
        ),
        reverse=True,
    )
    if not candidates:
        return None, {}, None
    path = candidates[0]
    try:
        return path, read_object(path), None
    except (OSError, ValueError) as exc:
        return path, {}, str(exc)


def _documents_match(
    project: Path, run: Path, manifest: dict[str, Any], figures: list[dict[str, Any]]
) -> bool:
    recorded = manifest.get("veusz_document_hashes")
    if not isinstance(recorded, dict) or len(recorded) != len(figures):
        return False
    expected_paths = set()
    for figure in figures:
        document = canonical_path(run / Path(figure["document"]).relative_to(project))
        spec = canonical_path(run / Path(figure["spec"]).relative_to(project))
        expected_paths.add(str(document))
        if (
            figure["document_sha256"] is None
            or recorded.get(str(document)) != figure["document_sha256"]
            or existing_file_sha256(document) != figure["document_sha256"]
            or existing_file_sha256(spec) != figure["spec_sha256"]
        ):
            return False
    return set(recorded) == expected_paths


def _exports_match(
    run: Path, manifest: dict[str, Any], figures: list[dict[str, Any]]
) -> bool:
    qa = manifest.get("qa") or {}
    exports = (manifest.get("result") or {}).get("exports")
    if qa.get("status") != "passed" or not isinstance(exports, list) or not exports:
        return False
    qa_hashes = {
        item.get("path"): item.get("sha256")
        for category in ("pdfs", "tiffs")
        for item in qa.get(category, [])
        if isinstance(item, dict)
    }
    document_formats: dict[str, set[str]] = {}
    seen = set()
    for item in exports:
        if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
            return False
        path = canonical_path(Path(item["path"]))
        fmt, digest = item.get("format"), item["sha256"]
        if not isinstance(fmt, str):
            return False
        if not path.is_relative_to(run) or str(path) in seen:
            return False
        seen.add(str(path))
        if existing_file_sha256(path) != digest:
            return False
        if fmt in {"pdf", "tiff_300"} and qa_hashes.get(str(path)) != digest:
            return False
        document_formats.setdefault(str(item.get("document")), set()).add(fmt)
    for figure in figures:
        relative = Path(figure["document"]).relative_to(run.parent.parent)
        if not {"pdf", "tiff_300"}.issubset(
            document_formats.get(str(run / relative), set())
        ):
            return False
    return True


def publication_indicators(
    project: Path,
    request: dict[str, Any],
    figures: list[dict[str, Any]],
    source: dict[str, Any],
) -> dict[str, Any]:
    manifest_path, manifest, error = latest_run(project)
    last = (
        None
        if manifest_path is None
        else {
            "manifest": str(manifest_path),
            "recorded_ready_to_use": manifest.get("ready_to_use"),
            "recorded_qa_status": (manifest.get("qa") or {}).get("status"),
            "error": error,
        }
    )
    request_current = documents_current = artifacts_current = False
    evidence_error = error
    if manifest_path is not None and manifest:
        try:
            run = manifest_path.parent
            request_current = (
                request
                == read_object(run / "request_snapshot.json")
                == manifest.get("request")
            )
            documents_current = _documents_match(project, run, manifest, figures)
            artifacts_current = _exports_match(run, manifest, figures)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            evidence_error = str(exc)
    qa_current = request_current and documents_current and artifacts_current
    qa = _indicator(
        qa_current if manifest_path is not None else None,
        scope="saved_documents_and_exported_artifact_hashes",
        request_current=request_current,
        documents_current=documents_current,
        artifacts_current=artifacts_current,
        error=evidence_error,
    )
    value = request.get("delivery_output")
    delivery = _indicator(
        None,
        path=value,
        binding_current=False,
        package_current=None,
        source_current=source["current"],
        qa_current=qa["current"],
    )
    if isinstance(value, str) and value:
        try:
            root = Path(value).expanduser()
            if not root.is_absolute():
                root = project / root
            root = canonical_path(root)
            binding_current = bound_delivery_project(root) == project
            for member in root.rglob("*"):
                canonical_path(member)
            verification = verify_delivery_package(
                manifest.get("delivery_package"),
                expected_root=root,
                expected_manifest=manifest,
            )
            package_current = verification["passed"] is True
            current_values = (
                binding_current,
                package_current,
                qa["current"],
                source["current"],
            )
            current = (
                False
                if any(item is False for item in current_values)
                else True
                if all(item is True for item in current_values)
                else None
            )
            delivery = _indicator(
                current,
                path=str(root),
                binding_current=binding_current,
                package_current=package_current,
                source_current=source["current"],
                qa_current=qa["current"],
                failed_checks=verification["failed_checks"],
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            delivery = _indicator(
                False,
                path=value,
                binding_current=False,
                package_current=False,
                source_current=source["current"],
                qa_current=qa["current"],
                error=str(exc),
            )
    return {"last_run": last, "qa": qa, "delivery": delivery}
