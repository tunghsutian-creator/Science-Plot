"""Verify exact-current export, QA, and delivery artifact bindings."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import (
    existing_file_sha256,
)

from sciplot_core.studio_core.runtime import (
    _normalize_export_format,
    _export_suffix,
)


def _verify_exact_current_export_binding(
    *,
    document_path: Path,
    export_document_sha256: str,
    exports: list[dict[str, Any]],
) -> None:
    expected_document_hash = str(export_document_sha256 or "").strip()
    current_document_hash = existing_file_sha256(document_path)
    if not expected_document_hash or current_document_hash != expected_document_hash:
        raise RuntimeError(
            "The current VSZ hash no longer matches the document that produced "
            "these exports."
        )
    if not exports:
        raise RuntimeError("Exact-current export produced no artifact records.")
    seen_formats: set[str] = set()
    seen_paths: set[Path] = set()
    for item in exports:
        path_value = item.get("path") if isinstance(item, dict) else None
        raw_format = (
            str(item.get("format") or "").strip() if isinstance(item, dict) else ""
        )
        expected_hash = (
            str(item.get("sha256") or "").strip() if isinstance(item, dict) else ""
        )
        try:
            normalized_format = _normalize_export_format(raw_format)
        except ValueError as exc:
            raise RuntimeError(
                f"Exact-current export record has an invalid format: {raw_format!r}."
            ) from exc
        if raw_format != normalized_format:
            raise RuntimeError(
                "Exact-current export records must use canonical format names; "
                f"received {raw_format!r}, expected {normalized_format!r}."
            )
        if normalized_format in seen_formats:
            raise RuntimeError(
                f"Exact-current export has duplicate {normalized_format} records."
            )
        if not isinstance(path_value, str) or not path_value.strip():
            raise RuntimeError("Exact-current export record has no artifact path.")
        artifact_path = Path(path_value).expanduser().resolve()
        if artifact_path in seen_paths:
            raise RuntimeError(
                f"Exact-current export reuses one artifact path: {artifact_path}"
            )
        expected_suffix, _dpi = _export_suffix(normalized_format)
        actual_hash = existing_file_sha256(artifact_path)
        actual_size = artifact_path.stat().st_size if artifact_path.is_file() else 0
        if (
            not artifact_path.is_file()
            or actual_size <= 0
            or item.get("exists") is not True
            or int(item.get("size_bytes") or 0) != actual_size
            or not expected_hash
            or actual_hash != expected_hash
            or not artifact_path.name.endswith(expected_suffix)
        ):
            raise RuntimeError(
                "An exported artifact is missing or changed before its "
                f"receipt was published: {artifact_path}"
            )
        seen_formats.add(normalized_format)
        seen_paths.add(artifact_path)


def _verify_qa_artifact_hashes(
    qa: dict[str, Any],
    *,
    exports: list[dict[str, Any]],
    covered_formats: set[str],
) -> None:
    canonical_covered = {_normalize_export_format(item) for item in covered_formats}
    expected_records: Counter[tuple[str, str, str]] = Counter()
    for item in exports:
        if not isinstance(item, dict):
            continue
        try:
            normalized_format = _normalize_export_format(str(item.get("format") or ""))
        except ValueError:
            continue
        if normalized_format not in canonical_covered:
            continue
        path_value = str(item.get("path") or "")
        expected_records[
            (
                normalized_format,
                Path(path_value).name,
                str(item.get("sha256") or ""),
            )
        ] += 1

    actual_records: Counter[tuple[str, str, str]] = Counter()
    for qa_key, normalized_format in (
        ("pdfs", "pdf"),
        ("tiffs", "tiff_300"),
    ):
        records = qa.get(qa_key)
        if normalized_format not in canonical_covered or not isinstance(records, list):
            continue
        for item in records:
            if not isinstance(item, dict):
                continue
            actual_records[
                (
                    normalized_format,
                    Path(str(item.get("path") or "")).name,
                    str(item.get("sha256") or ""),
                )
            ] += 1

    if (
        not expected_records
        or any(not record[2] for record in expected_records)
        or expected_records != actual_records
    ):
        raise RuntimeError("Artifact QA hashes do not match the exact-current exports.")


def _verify_studio_delivery_binding(
    delivery: object,
    *,
    exports: list[dict[str, Any]],
    export_document_sha256: str,
    document_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    issues: list[str] = []
    if not isinstance(delivery, dict):
        return {
            "kind": "sciplot_studio_delivery_verification",
            "status": "failed",
            "passed": False,
            "issues": ["The delivery package record is missing."],
        }
    root_value = delivery.get("path")
    try:
        delivery_root = Path(str(root_value)).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "kind": "sciplot_studio_delivery_verification",
            "status": "failed",
            "passed": False,
            "issues": [f"The delivery root is invalid: {exc}"],
        }

    def delivery_file(value: object, *, role: str) -> Path | None:
        if not isinstance(value, str) or not value.strip():
            issues.append(f"The delivery {role} path is missing.")
            return None
        try:
            candidate = Path(value).expanduser().resolve()
            candidate.relative_to(delivery_root)
        except (OSError, RuntimeError, ValueError):
            issues.append(f"The delivery {role} is outside its package root: {value}")
            return None
        try:
            if not candidate.is_file() or candidate.stat().st_size <= 0:
                issues.append(f"The delivery {role} is missing or empty: {candidate}")
                return None
        except OSError as exc:
            issues.append(f"The delivery {role} could not be inspected: {exc}")
            return None
        return candidate

    expected_exports: dict[Path, tuple[str, str]] = {}
    for item in exports:
        try:
            source = Path(str(item["path"])).expanduser().resolve()
            export_format = _normalize_export_format(str(item.get("format") or ""))
        except (KeyError, OSError, RuntimeError, ValueError):
            issues.append("An exact-current export record is invalid.")
            continue
        expected_hash = str(item.get("sha256") or "").strip()
        if not expected_hash:
            issues.append(f"Export {source} has no SHA-256.")
            continue
        expected_exports[source] = (export_format, expected_hash)

    matched_sources: set[Path] = set()
    figure_records = (
        delivery.get("figures") if isinstance(delivery.get("figures"), list) else []
    )
    for record in figure_records:
        if not isinstance(record, dict):
            issues.append("A delivery figure record is invalid.")
            continue
        try:
            source = Path(str(record.get("source") or "")).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            issues.append("A delivery figure source path is invalid.")
            continue
        expected = expected_exports.get(source)
        if expected is None:
            issues.append(
                f"Delivery figure is not bound to an exact-current export: {source}"
            )
            continue
        if source in matched_sources:
            issues.append(
                f"Delivery figure source is recorded more than once: {source}"
            )
            continue
        export_format, expected_hash = expected
        try:
            recorded_format = _normalize_export_format(
                str(record.get("export_format") or record.get("format") or "")
            )
        except ValueError:
            recorded_format = ""
        destination = delivery_file(
            record.get("path"),
            role=f"{export_format} figure",
        )
        source_hash = existing_file_sha256(source)
        destination_hash = (
            existing_file_sha256(destination) if destination is not None else None
        )
        if (
            recorded_format != export_format
            or source_hash != expected_hash
            or destination_hash != expected_hash
            or str(record.get("source_sha256") or "") != expected_hash
            or str(record.get("delivery_sha256") or "") != expected_hash
            or record.get("copy_hash_matches") is not True
        ):
            issues.append(f"Delivery figure hash or format binding failed: {source}")
            continue
        matched_sources.add(source)
    if set(expected_exports) != matched_sources:
        issues.append(
            "The delivery figures do not cover every exact-current export exactly once."
        )

    data_records = (
        delivery.get("data_csvs") if isinstance(delivery.get("data_csvs"), list) else []
    )
    if not data_records:
        issues.append("The delivery contains no recorded data CSV.")
    for record in data_records:
        if not isinstance(record, dict):
            issues.append("A delivery data record is invalid.")
            continue
        destination = delivery_file(record.get("path"), role="data CSV")
        expected_hash = str(record.get("sha256") or "").strip()
        if (
            destination is None
            or not expected_hash
            or existing_file_sha256(destination) != expected_hash
        ):
            issues.append("A delivery data CSV failed its SHA-256 binding.")

    project_records = (
        delivery.get("project_documents")
        if isinstance(delivery.get("project_documents"), list)
        else []
    )
    if not project_records:
        issues.append("The delivery contains no editable Veusz document.")
    expected_document_hashes = {
        str(Path(path).expanduser().resolve()): str(value)
        for path, value in (document_hashes or {}).items()
        if str(path).strip() and str(value).strip()
    }
    for record in project_records:
        if not isinstance(record, dict):
            issues.append("A delivery project-document record is invalid.")
            continue
        destination = delivery_file(
            record.get("path"),
            role="editable Veusz document",
        )
        destination_hash = (
            existing_file_sha256(destination) if destination is not None else None
        )
        source_path = Path(str(record.get("source") or "")).expanduser().resolve()
        expected_project_hash = expected_document_hashes.get(
            str(source_path),
            export_document_sha256,
        )
        if (
            destination_hash != expected_project_hash
            or str(record.get("source_sha256") or "") != expected_project_hash
            or str(record.get("delivery_sha256") or "") != expected_project_hash
            or record.get("copy_hash_matches") is not True
            or record.get("hash_matches_export") is not True
        ):
            issues.append(
                "An editable Veusz delivery copy is not bound to the "
                "exported document SHA-256."
            )

    editable = (
        delivery.get("editable_vsz")
        if isinstance(delivery.get("editable_vsz"), dict)
        else {}
    )
    editable_path = delivery_file(
        editable.get("path"),
        role="authoritative editable Veusz document",
    )
    if (
        editable_path is None
        or existing_file_sha256(editable_path) != export_document_sha256
        or str(editable.get("expected_hash") or "") != export_document_sha256
        or str(editable.get("actual_hash") or "") != export_document_sha256
        or editable.get("hash_matches_export") is not True
    ):
        issues.append(
            "The authoritative editable Veusz delivery record is not current."
        )

    delivery_file(
        delivery.get("open_in_veusz"),
        role="Open_in_Veusz launcher",
    )
    if delivery.get("complete") is not True:
        issues.append("The delivery package contract is incomplete.")
    passed = not issues
    return {
        "kind": "sciplot_studio_delivery_verification",
        "status": "passed" if passed else "failed",
        "passed": passed,
        "delivery_root": str(delivery_root),
        "verified_export_count": len(matched_sources),
        "verified_data_csv_count": len(data_records),
        "verified_project_document_count": len(project_records),
        "issues": issues,
    }
