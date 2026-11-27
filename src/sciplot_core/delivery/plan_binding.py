"""Bind resolved tasks to exact source artifacts and delivery records."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.artifact_locations import artifact_path_key
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.policy import canonical_figure_stem
from sciplot_core.policy.frame_export import CANONICAL_EXPORT_FORMATS
from sciplot_core.policy.export_formats import export_format_from_path


class RecordSourceMismatchPayload(TypedDict):
    reason: str
    source: NotRequired[str]
    expected_figure_id: NotRequired[str | None]
    actual_figure_id: NotRequired[str | None]


class MissingRecordSourceCheckPayload(TypedDict):
    passed: Literal[False]
    reason: Literal["records_missing"]


class DetailedRecordSourceCheckPayload(TypedDict):
    passed: bool
    expected_sources: list[str]
    recorded_sources: list[str]
    mismatches: list[RecordSourceMismatchPayload]


RecordSourceCheckPayload = (
    MissingRecordSourceCheckPayload | DetailedRecordSourceCheckPayload
)


class DeliveryRecordsMatchFailurePayload(TypedDict):
    passed: Literal[False]
    reason: str


class DeliveryRecordsMatchResultPayload(TypedDict):
    passed: bool
    figure_records: RecordSourceCheckPayload
    project_records: RecordSourceCheckPayload


DeliveryRecordsMatchPlanPayload = (
    DeliveryRecordsMatchFailurePayload | DeliveryRecordsMatchResultPayload
)


def plan_source_figure_ids(plan: ResolvedFigurePlan) -> dict[str, str]:
    """Return the unique authoritative source-artifact owner for every task."""

    task_by_id = {task.figure_id: task for task in plan.tasks}
    bindings: dict[str, str] = {}
    for outcome in plan.outcomes:
        task = task_by_id[outcome.figure_id]
        role_paths = _outcome_role_paths(outcome.artifacts)
        if any(len(paths) != 1 for paths in role_paths.values()):
            raise ValueError(
                "Each completed FigureOutcome must bind exactly one VSZ, PDF, "
                f"and 300-dpi TIFF: {outcome.figure_id}"
            )
        current_paths = set().union(*role_paths.values())
        if current_paths & set(bindings):
            raise ValueError("Resolved figure outcomes cannot share artifacts.")
        pdf_path = Path(next(iter(role_paths["pdf"])))
        tiff_path = Path(next(iter(role_paths["tiff_300"])))
        run_root = _outcome_run_root(pdf_path, tiff_path)
        if run_root is None:
            raise ValueError(
                "Resolved PDF and TIFF artifacts must share one run-local "
                f"figure directory: {outcome.figure_id}"
            )
        allowed_stems = {
            task.figure_id.casefold(),
            task.artifact_stem.casefold(),
            task.document_stem.casefold(),
        }
        primary = outcome.figure_id == plan.primary_figure_id
        single = len(plan.tasks) == 1
        for role in set(role_paths) - {"vsz"}:
            path = Path(next(iter(role_paths[role])))
            if path.parent != pdf_path.parent:
                raise ValueError("All rendered artifacts for a selected figure must share its run-local directory.")
            artifact_stem = canonical_figure_stem(path)
            if artifact_stem not in allowed_stems and not (
                artifact_stem == "document" and (primary or single)
            ):
                raise ValueError(
                    "Resolved figure artifact stem does not match its selected "
                    f"task: {outcome.figure_id}"
                )
        vsz_path = Path(next(iter(role_paths["vsz"])))
        if not _vsz_path_matches_task(
            vsz_path,
            allowed_stems=allowed_stems,
            primary=primary,
            single=single,
            run_root=run_root,
        ):
            raise ValueError(
                "Resolved VSZ path does not match its selected task: "
                f"{outcome.figure_id}"
            )
        for artifact_path in current_paths:
            bindings[artifact_path] = outcome.figure_id
    return bindings


def studio_outcome_exports_verified(
    plan: ResolvedFigurePlan, manifest: dict[str, Any],
) -> bool:
    """Separate structural outcome paths from the Studio run's decoded exports."""
    from sciplot_core.delivery.publication_evidence import qa_artifact_observations

    qa = manifest.get("qa")
    result = manifest["result"]
    exports = result.get("exports")
    documents = result.get("veusz_document_hashes")
    if (not isinstance(qa, dict) or qa.get("kind") != "sciplot_artifact_qa"
            or qa.get("status") != "passed" or not isinstance(exports, list)
            or not isinstance(documents, dict)):
        return False
    try:
        bindings = plan_source_figure_ids(plan)
    except ValueError:
        return False
    expected = {path: figure_id for path, figure_id in bindings.items()
                if export_format_from_path(path) in CANONICAL_EXPORT_FORMATS}
    document_by_figure = {figure_id: path for path, figure_id in bindings.items()
                          if Path(path).suffix.casefold() == ".vsz"}
    document_hashes = {artifact_path_key(path): digest for path, digest in documents.items()}
    observations = qa_artifact_observations(manifest)
    if set(observations) != set(expected) or len(exports) != len(expected):
        return False
    seen: set[str] = set()
    for record in exports:
        if not isinstance(record, dict) or not all(
            isinstance(record.get(key), str) and record[key]
            for key in ("path", "document", "sha256", "document_sha256")
        ):
            return False
        size = record.get("size_bytes")
        if type(size) is not int or size <= 0:
            return False
        path = artifact_path_key(record["path"])
        figure_id = record.get("figure_id")
        if len(plan.tasks) == 1 and figure_id == "primary":
            # The current single-document Studio exporter labels it primary.
            figure_id = plan.primary_figure_id
        document = artifact_path_key(record["document"])
        observed = observations.get(path, {})
        if (path in seen or path not in expected or figure_id != expected[path]
                or document != document_by_figure.get(figure_id)
                or record["document_sha256"] != document_hashes.get(document)
                or record.get("format") != export_format_from_path(path)
                or record.get("format") != observed.get("export_format")
                or record["sha256"] != observed.get("sha256")
                or size != observed.get("size_bytes")):
            return False
        seen.add(path)
    return True


def delivery_records_match_plan(
    plan: ResolvedFigurePlan,
    *,
    figure_records: object,
    project_records: object,
) -> DeliveryRecordsMatchPlanPayload:
    """Verify persisted records against exact outcome source paths and IDs."""

    try:
        bindings = plan_source_figure_ids(plan)
    except ValueError as exc:
        return {"passed": False, "reason": str(exc)}
    expected_figure_sources = {
        path
        for path in bindings
        if export_format_from_path(path) in CANONICAL_EXPORT_FORMATS
    }
    expected_project_sources = {
        path for path in bindings if Path(path).suffix.casefold() == ".vsz"
    }
    figure_check = _record_sources_match(
        figure_records,
        expected_sources=expected_figure_sources,
        bindings=bindings,
    )
    project_check = _record_sources_match(
        project_records,
        expected_sources=expected_project_sources,
        bindings=bindings,
    )
    return {
        "passed": figure_check["passed"] and project_check["passed"],
        "figure_records": figure_check,
        "project_records": project_check,
    }


def _outcome_role_paths(artifacts: tuple[str, ...]) -> dict[str, set[str]]:
    roles: dict[str, set[str]] = {role: set() for role in ("pdf", "tiff_300", "vsz")}
    for path in artifacts:
        resolved = artifact_path_key(path)
        role = "vsz" if Path(path).suffix.casefold() == ".vsz" else export_format_from_path(path)
        if role is not None:
            roles.setdefault(role, set()).add(resolved)
    return roles


def _vsz_path_matches_task(
    path: Path,
    *,
    allowed_stems: set[str],
    primary: bool,
    single: bool,
    run_root: Path,
) -> bool:
    """Match a canonical role-path key against the selected native layout."""
    try:
        relative = path.relative_to(run_root)
    except ValueError:
        return False
    if path.stem.casefold() in allowed_stems:
        return True
    if path.stem.casefold() != "document":
        return False
    parts = tuple(part.casefold() for part in relative.parts)
    if (primary or single) and parts == ("studio", "document.vsz"):
        return True
    if (primary or single) and parts == (
        "figures",
        "_veusz",
        "single",
        "studio",
        "document.vsz",
    ):
        return True
    if len(parts) >= 3 and parts[-2:] == ("studio", "document.vsz"):
        if parts[-3] in allowed_stems:
            return True
    return bool(
        len(parts) >= 6
        and parts[:2] == ("figures", "_veusz")
        and parts[2] in allowed_stems
        and parts[-2:] == ("studio", "document.vsz")
    )


def _outcome_run_root(pdf_path: Path, tiff_path: Path) -> Path | None:
    pdf_parent = pdf_path.parent
    tiff_parent = tiff_path.parent
    if pdf_parent != tiff_parent:
        return None
    return pdf_parent.parent if pdf_parent.name.casefold() == "figures" else pdf_parent


def _record_sources_match(
    value: object,
    *,
    expected_sources: set[str],
    bindings: dict[str, str],
) -> RecordSourceCheckPayload:
    if not isinstance(value, list):
        return {"passed": False, "reason": "records_missing"}
    recorded_sources: list[str] = []
    delivery_paths: list[str] = []
    mismatches: list[RecordSourceMismatchPayload] = []
    for item in value:
        if not isinstance(item, dict):
            mismatches.append({"reason": "record_not_object"})
            continue
        source = artifact_path_key(str(item.get("source") or ""))
        destination = artifact_path_key(str(item.get("path") or ""))
        expected_id = bindings.get(source)
        actual_id = str(item.get("figure_id") or "").strip()
        recorded_sources.append(source)
        delivery_paths.append(destination)
        if expected_id is None or actual_id != expected_id:
            mismatches.append(
                {
                    "reason": "source_figure_id_mismatch",
                    "source": source,
                    "expected_figure_id": expected_id,
                    "actual_figure_id": actual_id or None,
                }
            )
    passed = bool(
        len(recorded_sources) == len(expected_sources)
        and len(set(recorded_sources)) == len(recorded_sources)
        and set(recorded_sources) == expected_sources
        and len(set(delivery_paths)) == len(delivery_paths)
        and not mismatches
    )
    return {
        "passed": passed,
        "expected_sources": sorted(expected_sources),
        "recorded_sources": sorted(recorded_sources),
        "mismatches": mismatches,
    }


def project_document_hashes_current(value: object) -> bool:
    """Verify exact source/delivery hashes for plan-bound editable documents."""

    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if not isinstance(item, dict):
            return False
        source = Path(str(item.get("source") or "")).expanduser()
        delivery = Path(str(item.get("path") or "")).expanduser()
        recorded_source_hash = str(item.get("source_sha256") or "").strip()
        expected_hash = str(item.get("expected_sha256") or "").strip()
        recorded_delivery_hash = str(item.get("delivery_sha256") or "").strip()
        source_hash = existing_file_sha256(resolve_source_path(source, expected_sha256=recorded_source_hash or None))
        delivery_hash = existing_file_sha256(resolve_source_path(delivery, expected_sha256=recorded_delivery_hash or None))
        if not (
            source_hash
            and source_hash == recorded_source_hash
            and source_hash == expected_hash
            and source_hash == delivery_hash
            and delivery_hash == recorded_delivery_hash
            and item.get("copy_hash_matches") is True
            and item.get("hash_matches_export") is True
        ):
            return False
    return True


def figure_artifact_hashes_current(value: object) -> bool:
    """Verify exact source/delivery hashes for plan-bound rendered artifacts."""

    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if not isinstance(item, dict):
            return False
        source = Path(str(item.get("source") or "")).expanduser()
        delivery = Path(str(item.get("path") or "")).expanduser()
        recorded_source_hash = str(item.get("source_sha256") or "").strip()
        recorded_delivery_hash = str(item.get("delivery_sha256") or "").strip()
        source_hash = existing_file_sha256(resolve_source_path(source, expected_sha256=recorded_source_hash or None))
        delivery_hash = existing_file_sha256(resolve_source_path(delivery, expected_sha256=recorded_delivery_hash or None))
        if not (
            source_hash
            and source_hash == recorded_source_hash
            and source_hash == delivery_hash
            and delivery_hash == recorded_delivery_hash
            and item.get("copy_hash_matches") is True
        ):
            return False
    return True


__all__ = [
    "DeliveryRecordsMatchPlanPayload",
    "RecordSourceCheckPayload",
    "RecordSourceMismatchPayload",
    "delivery_records_match_plan",
    "figure_artifact_hashes_current",
    "plan_source_figure_ids",
    "project_document_hashes_current",
]
