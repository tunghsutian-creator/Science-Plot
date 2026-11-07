"""Validate recorded delivery files against live paths and hashes."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.project_store.runtime import projected_runtime_artifact


def _recorded_file_set(
    records: object,
    *,
    directory: Path,
    suffixes: set[str],
    hash_field: str,
    required: bool = True,
) -> dict[str, Any]:
    live_files = (
        {
            path.resolve()
            for path in directory.iterdir()
            if path.is_file() and path.suffix.casefold() in suffixes
        }
        if directory.is_dir()
        else set()
    )
    recorded_files: set[Path] = set()
    invalid: list[dict[str, Any]] = []
    if not isinstance(records, list):
        return {
            "passed": False,
            "live_files": sorted(str(path) for path in live_files),
            "recorded_files": [],
            "invalid": [{"reason": "records_missing"}],
        }
    for record in records:
        if not isinstance(record, dict):
            invalid.append({"reason": "record_not_object"})
            continue
        path_value = record.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            invalid.append({"reason": "path_missing", "record": record})
            continue
        expected_hash = str(record.get(hash_field) or "").strip()
        declared = Path(path_value).expanduser()
        if (declared.suffix.casefold() not in suffixes or len(expected_hash) != 64
                or any(char not in "0123456789abcdef" for char in expected_hash)):
            invalid.append({"reason": "file_or_hash_invalid", "path": str(declared)})
            continue
        path = projected_runtime_artifact(declared).resolve()
        actual_hash = existing_file_sha256(path)
        valid = bool(
            path.parent == directory.resolve()
            and path.suffix.casefold() in suffixes
            and path.is_file()
            and path.stat().st_size > 0
            and expected_hash
            and actual_hash == expected_hash
        )
        if not valid:
            invalid.append(
                {
                    "reason": "file_or_hash_invalid",
                    "path": str(path),
                    "expected_sha256": expected_hash or None,
                    "actual_sha256": actual_hash,
                }
            )
        if path in recorded_files:
            invalid.append(
                {
                    "reason": "duplicate_record_path",
                    "path": str(path),
                }
            )
        recorded_files.add(path)
    return {
        "passed": (bool(live_files) or not required) and not invalid and live_files == recorded_files,
        "live_files": sorted(str(path) for path in live_files),
        "recorded_files": sorted(str(path) for path in recorded_files),
        "invalid": invalid,
    }


def rendered_file_sets(records: object, *, directory: Path) -> dict[str, dict[str, Any]]:
    """The finite supported figure formats share one exact file-set owner."""
    from sciplot_core.delivery.filesystem_metadata import is_delivery_finder_metadata
    from sciplot_core.policy.frame_export import canonical_export_format
    from sciplot_core.policy.export_formats import export_format_from_path

    result: dict[str, dict[str, Any]] = {}
    for kind, suffixes in (("pdf", {".pdf"}), ("tiff", {".tif", ".tiff"}), ("png", {".png"}), ("svg", {".svg"})):
        rows = ([item for item in records if isinstance(item, dict)
                 and Path(str(item.get("path") or "")).suffix.casefold() in suffixes]
                if isinstance(records, list) else None)
        result[kind] = _recorded_file_set(rows, directory=directory, suffixes=suffixes,
            hash_field="delivery_sha256", required=kind in {"pdf", "tiff"})
    actual = {path.resolve() for path in directory.iterdir() if not is_delivery_finder_metadata(path)} if directory.is_dir() else set()
    declared = {projected_runtime_artifact(str(item["path"])).resolve() for item in records
                if isinstance(item, dict) and isinstance(item.get("path"), str) and item["path"].strip()} if isinstance(records, list) else set()
    def format_matches(item: dict[str, Any]) -> bool:
        value = item.get("export_format") or item.get("format")
        if not value:
            return True
        try:
            return canonical_export_format(value) == export_format_from_path(item.get("path", ""))
        except ValueError:
            return False

    declared_formats = all(format_matches(item) for item in records if isinstance(item, dict)) if isinstance(records, list) else False
    result["all_formats"] = {"passed": bool(declared_formats and isinstance(records, list)
        and all(isinstance(item, dict) and export_format_from_path(str(item.get("path") or "")) is not None for item in records)
        and actual == declared), "live_files": sorted(str(path) for path in actual),
        "recorded_files": sorted(str(path) for path in declared)}
    return result


def additional_figure_contract_current(records: object, manifest: dict[str, Any]) -> bool:
    """Requested extra formats cannot disappear with their entire record/file."""
    from sciplot_core.delivery.plan_binding import figure_artifact_hashes_current
    from sciplot_core.foundation.source_locations import literal_source_path
    from sciplot_core.policy.export_formats import export_format_from_path

    def extra(path: object) -> bool:
        return isinstance(path, str) and export_format_from_path(path) in {"png_300", "png_600", "svg"}

    expected: set[str] = set()
    result = manifest.get("result")
    if isinstance(result, dict) and isinstance(result.get("exports"), list):
        expected.update(item["path"] for item in result["exports"] if isinstance(item, dict) and extra(item.get("path")))
    if isinstance(manifest.get("figures"), list):
        expected.update(path for path in manifest["figures"] if extra(path))
    plan = manifest.get("resolved_figure_plan")
    if isinstance(plan, dict):
        for outcome in plan.get("outcomes", []):
            if isinstance(outcome, dict):
                expected.update(path for path in outcome.get("artifacts", []) if extra(path))
    rows = [item for item in records if isinstance(item, dict) and extra(item.get("path"))] if isinstance(records, list) else []
    actual: list[str] = []
    for row in rows:
        source = row.get("source")
        if not isinstance(source, str) or not source.strip():
            return False
        actual.append(source)
    if {literal_source_path(Path(path)) for path in expected} != {literal_source_path(Path(path)) for path in actual}:
        return False
    return not rows or figure_artifact_hashes_current(rows)
