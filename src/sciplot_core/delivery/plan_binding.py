"""Bind resolved tasks to exact source artifacts and delivery records."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.policy import canonical_figure_stem


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
        for role in ("pdf", "tiff_300"):
            path = Path(next(iter(role_paths[role])))
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
        if Path(path).suffix.casefold() in {".pdf", ".tif", ".tiff"}
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
    return {
        "pdf": {
            str(Path(path).expanduser().resolve())
            for path in artifacts
            if Path(path).suffix.casefold() == ".pdf"
        },
        "tiff_300": {
            str(Path(path).expanduser().resolve())
            for path in artifacts
            if Path(path).name.casefold().endswith("_300dpi.tiff")
        },
        "vsz": {
            str(Path(path).expanduser().resolve())
            for path in artifacts
            if Path(path).suffix.casefold() == ".vsz"
        },
    }


def _vsz_path_matches_task(
    path: Path,
    *,
    allowed_stems: set[str],
    primary: bool,
    single: bool,
    run_root: Path,
) -> bool:
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(run_root)
    except ValueError:
        return False
    if resolved.stem.casefold() in allowed_stems:
        return True
    if resolved.stem.casefold() != "document":
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
    pdf_parent = pdf_path.expanduser().resolve().parent
    tiff_parent = tiff_path.expanduser().resolve().parent
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
        source = str(Path(str(item.get("source") or "")).expanduser().resolve())
        destination = str(Path(str(item.get("path") or "")).expanduser().resolve())
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
        source_hash = existing_file_sha256(source)
        delivery_hash = existing_file_sha256(delivery)
        recorded_source_hash = str(item.get("source_sha256") or "").strip()
        expected_hash = str(item.get("expected_sha256") or "").strip()
        recorded_delivery_hash = str(item.get("delivery_sha256") or "").strip()
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
    """Verify exact source/delivery hashes for plan-bound PDF/TIFF artifacts."""

    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if not isinstance(item, dict):
            return False
        source = Path(str(item.get("source") or "")).expanduser()
        delivery = Path(str(item.get("path") or "")).expanduser()
        source_hash = existing_file_sha256(source)
        delivery_hash = existing_file_sha256(delivery)
        recorded_source_hash = str(item.get("source_sha256") or "").strip()
        recorded_delivery_hash = str(item.get("delivery_sha256") or "").strip()
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
