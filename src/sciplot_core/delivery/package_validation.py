"""Revalidate a persisted visible delivery package."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.launchers import (
    inspect_delivery_launcher_contract,
)
from sciplot_core.policy import (
    DELIVERY_DATA_DIR,
    DELIVERY_LAUNCHER,
    DELIVERY_PDF_DIR,
    DELIVERY_PROJECT_DIR,
    DELIVERY_TIFF_DIR,
)

from sciplot_core.delivery.contracts import (
    DELIVERY_PACKAGE_CONTRACT_VERSION,
)

from sciplot_core.delivery.figure_pairing import (
    _delivery_figure_pairing,
)

from sciplot_core.delivery.file_set_validation import (
    _recorded_file_set,
)


def verify_delivery_package(
    delivery_package: object,
    *,
    expected_root: Path,
) -> dict[str, Any]:
    """Revalidate the persisted minimal delivery against live files and hashes."""

    record = delivery_package if isinstance(delivery_package, dict) else {}
    expected = expected_root.expanduser().resolve()
    path_value = record.get("path")
    recorded_root = (
        Path(path_value).expanduser().resolve()
        if isinstance(path_value, str) and path_value.strip()
        else None
    )
    root_ready = bool(recorded_root == expected and expected.is_dir())
    expected_top_level = {
        DELIVERY_DATA_DIR,
        DELIVERY_PDF_DIR,
        DELIVERY_TIFF_DIR,
        DELIVERY_PROJECT_DIR,
        DELIVERY_LAUNCHER,
    }
    actual_top_level = (
        {path.name for path in expected.iterdir()} if expected.is_dir() else set()
    )
    data_check = _recorded_file_set(
        record.get("data_csvs"),
        directory=expected / DELIVERY_DATA_DIR,
        suffixes={".csv"},
        hash_field="sha256",
    )
    figure_records = record.get("figures")
    pdf_records = (
        [
            item
            for item in figure_records
            if isinstance(item, dict)
            and Path(str(item.get("path") or "")).suffix.casefold() == ".pdf"
        ]
        if isinstance(figure_records, list)
        else None
    )
    tiff_records = (
        [
            item
            for item in figure_records
            if isinstance(item, dict)
            and Path(str(item.get("path") or "")).suffix.casefold() in {".tif", ".tiff"}
        ]
        if isinstance(figure_records, list)
        else None
    )
    pdf_check = _recorded_file_set(
        pdf_records,
        directory=expected / DELIVERY_PDF_DIR,
        suffixes={".pdf"},
        hash_field="delivery_sha256",
    )
    tiff_check = _recorded_file_set(
        tiff_records,
        directory=expected / DELIVERY_TIFF_DIR,
        suffixes={".tif", ".tiff"},
        hash_field="delivery_sha256",
    )
    project_check = _recorded_file_set(
        record.get("project_documents"),
        directory=expected / DELIVERY_PROJECT_DIR,
        suffixes={".vsz"},
        hash_field="delivery_sha256",
    )
    live_figure_records = [
        {"path": path}
        for directory, suffixes in (
            (expected / DELIVERY_PDF_DIR, {".pdf"}),
            (expected / DELIVERY_TIFF_DIR, {".tif", ".tiff"}),
        )
        if directory.is_dir()
        for path in directory.iterdir()
        if path.is_file() and path.suffix.casefold() in suffixes
    ]
    pairing = _delivery_figure_pairing(live_figure_records)
    launcher = expected / DELIVERY_LAUNCHER
    live_launcher_contract = inspect_delivery_launcher_contract(expected)
    recorded_launcher_contract = (
        record.get("launcher_contract")
        if isinstance(record.get("launcher_contract"), dict)
        else {}
    )
    recorded_launcher_path = record.get("open_in_veusz")
    launcher_path_current = bool(
        isinstance(recorded_launcher_path, str)
        and recorded_launcher_path.strip()
        and Path(recorded_launcher_path).expanduser().resolve() == launcher.resolve()
    )
    recorded_launcher_sha256 = str(record.get("open_in_veusz_sha256") or "").strip()
    launcher_hash_current = bool(
        recorded_launcher_sha256
        and recorded_launcher_sha256 == live_launcher_contract.get("content_sha256")
    )
    launcher_structure_current = bool(
        live_launcher_contract.get("ready") is True
        and live_launcher_contract.get("canonical_structure") is True
        and live_launcher_contract.get("required_command_present") is True
    )
    launcher_contract_current = bool(
        recorded_launcher_contract
        and recorded_launcher_contract == live_launcher_contract
    )
    launcher_ready = bool(
        launcher_path_current
        and launcher_hash_current
        and launcher_structure_current
        and launcher_contract_current
    )
    artifacts = record.get("artifacts")
    artifact_records_ready = bool(
        isinstance(artifacts, list)
        and artifacts
        and all(
            isinstance(item, dict)
            and item.get("exists") is True
            and isinstance(item.get("path"), str)
            and Path(str(item["path"])).expanduser().exists()
            for item in artifacts
        )
    )
    checks = {
        "record_kind_current": record.get("kind") == "sciplot_user_delivery_package"
        and record.get("version") == DELIVERY_PACKAGE_CONTRACT_VERSION,
        "recorded_complete": record.get("complete") is True,
        "canonical_root": root_ready,
        "minimal_top_level": actual_top_level == expected_top_level,
        "data_files_current": data_check["passed"],
        "pdf_files_current": pdf_check["passed"],
        "tiff_files_current": tiff_check["passed"],
        "project_files_current": project_check["passed"],
        "canonical_pdf_tiff_pairs": pairing["passed"],
        "launcher_path_current": launcher_path_current,
        "launcher_hash_current": launcher_hash_current,
        "launcher_structure_current": launcher_structure_current,
        "launcher_contract_current": launcher_contract_current,
        "launcher_current": launcher_ready,
        "artifact_records_current": artifact_records_ready,
    }
    return {
        "kind": "sciplot_delivery_verification",
        "version": 1,
        "passed": all(checks.values()),
        "checks": checks,
        "failed_checks": [key for key, passed in checks.items() if not passed],
        "expected_root": str(expected),
        "recorded_root": str(recorded_root) if recorded_root is not None else None,
        "top_level": {
            "expected": sorted(expected_top_level),
            "actual": sorted(actual_top_level),
        },
        "data": data_check,
        "pdf": pdf_check,
        "tiff": tiff_check,
        "project": project_check,
        "pairing": pairing,
        "launcher": live_launcher_contract,
    }
