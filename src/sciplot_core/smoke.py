from __future__ import annotations

import copy
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._paths import (
    VEUSZ_ROOT,
    VEUSZ_UPSTREAM_COMMIT,
    VENDORED_CORE_ROOT,
)
from sciplot_core._utils import file_sha256, json_safe

RUNTIME_SMOKE_VERSION = 21
EXPECTED_RULE_ID = "ftir_spectrum"
MANUAL_EDIT_MARKER = "# SciPlot runtime smoke manual-edit preservation probe"
EXPECTED_SCALAR_VISUAL_ATTACK_IDS = frozenset(
    {
        "axis_label_size_zero",
        "axis_line_width_zero",
        "axis_major_tick_length_zero",
        "axis_major_tick_width_zero",
        "axis_minor_tick_length_zero",
        "axis_minor_tick_width_zero",
        "axis_ticklabels_size_zero",
        "colorbar_background_deleted",
        "colorbar_background_fill_changed",
        "colorbar_background_geometry_changed",
        "colorbar_background_hidden",
        "colorbar_background_transparency_changed",
        "colorbar_border_hidden",
        "colorbar_border_transparent",
        "colorbar_border_width_zero",
        "colorbar_foreground_changed",
        "colorbar_label_hidden",
        "colorbar_label_size_zero",
        "colorbar_line_hidden",
        "colorbar_line_transparent",
        "colorbar_line_width_zero",
        "colorbar_major_tick_length_zero",
        "colorbar_major_tick_width_zero",
        "colorbar_major_ticks_hidden",
        "colorbar_minor_tick_length_zero",
        "colorbar_minor_tick_width_zero",
        "colorbar_minor_ticks_hidden",
        "colorbar_minor_ticks_transparent",
        "colorbar_ticklabels_hidden",
        "colorbar_ticklabels_size_zero",
        "colorbar_ticks_transparent",
        "colorbar_zero_width",
        "contour_lines_hidden",
        "image_transparency",
        "reference_guide_made_opaque",
        "reference_line_geometry_changed",
        "reference_line_hidden",
        "reference_line_style_changed",
        "reference_line_width_changed",
        "unmanaged_line_overlay",
        "unmanaged_opaque_overlay",
    }
)


def _check(
    check_id: str, label: str, passed: bool, *, detail: Any = None
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def _inspect_veusz_document_state(document_path: Path) -> dict[str, Any]:
    """Reopen a VSZ in the isolated Veusz worker and return widget settings."""

    from sciplot_core.veusz_runtime import veusz_worker_environment

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "sciplot_core.veusz_worker",
            "inspect-document-state",
            str(document_path.expanduser().resolve()),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
        env=veusz_worker_environment(),
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        raise ValueError(
            "Veusz attack materialization inspection failed: "
            f"{detail[-1] if detail else completed.returncode}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Veusz attack materialization inspection returned invalid JSON."
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "sciplot_veusz_document_state"
        or payload.get("version") != 1
        or payload.get("status") != "passed"
        or not isinstance(payload.get("widgets"), dict)
    ):
        raise ValueError(
            "Veusz attack materialization inspection did not pass."
        )
    return payload


def _delivery_artifact(delivery: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    artifacts = (
        delivery.get("artifacts") if isinstance(delivery.get("artifacts"), list) else []
    )
    for item in artifacts:
        if isinstance(item, dict) and item.get("id") == artifact_id:
            return item
    return {}


def _delivery_layout_probe(delivery: dict[str, Any]) -> dict[str, Any]:
    """Verify the small user-facing delivery surface and its CSV contract."""

    delivery_path = Path(str(delivery.get("path") or "")).expanduser().resolve()
    expected_entries = {"data", "pdf", "tiff", "project", "Open_in_Veusz.command"}
    actual_entries = {path.name for path in delivery_path.iterdir()} if delivery_path.is_dir() else set()
    forbidden_names = {
        "_sciplot_internal",
        "editable",
        "figures",
        "README.md",
        ".sciplot",
        "manifest.json",
        "raw",
        "tables",
    }
    forbidden_paths = [
        str(path)
        for path in delivery_path.rglob("*")
        if path.name in forbidden_names or path.suffix.casefold() in {".xlsx", ".xls", ".sciplot"}
    ] if delivery_path.is_dir() else []

    data_records = delivery.get("data_csvs") if isinstance(delivery.get("data_csvs"), list) else []
    data_checks: list[dict[str, Any]] = []
    for record in data_records:
        path = Path(str(record.get("path") or "")) if isinstance(record, dict) else Path()
        rows: list[list[str]] = []
        if path.is_file():
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
        data_checks.append(
            {
                "path": str(path),
                "under_data": path.parent == delivery_path / "data",
                "row_count": len(rows),
                "four_row_header": len(rows) >= 4 and all(rows[index] for index in range(3)),
                "data_rows": max(len(rows) - 3, 0),
                "column_count": len(rows[0]) if rows else 0,
            }
        )

    figure_records = delivery.get("figures") if isinstance(delivery.get("figures"), list) else []
    figure_locations = [
        {
            "path": str(record.get("path")),
            "format": record.get("format"),
            "in_expected_folder": (
                Path(str(record.get("path") or "")).parent
                == delivery_path / ("pdf" if record.get("format") == "pdf" else "tiff")
            ),
        }
        for record in figure_records
        if isinstance(record, dict)
    ]
    project_records = delivery.get("project_documents")
    project_records = project_records if isinstance(project_records, list) else []
    project_locations = [
        {
            "path": str(record.get("path")),
            "in_project": Path(str(record.get("path") or "")).parent == delivery_path / "project",
            "exists": bool(record.get("exists")),
        }
        for record in project_records
        if isinstance(record, dict)
    ]

    launcher = delivery_path / "Open_in_Veusz.command"
    launcher_probe: dict[str, Any] = {"path": str(launcher), "exists": launcher.is_file()}
    if launcher.is_file():
        env = os.environ.copy()
        env["SCIPLOT_LAUNCH_DRY_RUN"] = "1"
        completed = subprocess.run(
            ["zsh", str(launcher)],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        launcher_probe.update(
            {
                "returncode": completed.returncode,
                "dry_run_path": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
        )

    passed = (
        delivery_path.is_dir()
        and actual_entries == expected_entries
        and not forbidden_paths
        and bool(data_checks)
        and all(
            item["under_data"] and item["four_row_header"] and item["data_rows"] > 0 and item["column_count"] > 0
            for item in data_checks
        )
        and bool(figure_locations)
        and all(item["in_expected_folder"] for item in figure_locations)
        and bool(project_locations)
        and all(item["in_project"] and item["exists"] for item in project_locations)
        and launcher_probe.get("exists") is True
        and launcher_probe.get("returncode") == 0
        and Path(launcher_probe.get("dry_run_path") or "").is_file()
    )
    return {
        "passed": passed,
        "delivery_path": str(delivery_path),
        "expected_entries": sorted(expected_entries),
        "actual_entries": sorted(actual_entries),
        "forbidden_paths": forbidden_paths,
        "data": data_checks,
        "figures": figure_locations,
        "projects": project_locations,
        "launcher": launcher_probe,
    }


def _package_import_probe() -> dict[str, Any]:
    script = "\n".join(
        [
            "import json",
            "import sys",
            "before = list(sys.path)",
            "import sciplot_core",
            "after = list(sys.path)",
            "print(json.dumps({'added': [item for item in after if item not in before]}))",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "passed": False,
            "returncode": completed.returncode,
            "stderr": completed.stderr.strip(),
        }
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {
            "passed": False,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
        }
    added = [str(item) for item in payload.get("added", [])]
    vendor_root = VENDORED_CORE_ROOT.resolve()
    vendor_added = []
    for item in added:
        try:
            if Path(item).expanduser().resolve() == vendor_root:
                vendor_added.append(item)
        except (OSError, RuntimeError):
            continue
    return {
        "passed": not vendor_added,
        "added_paths": added,
        "vendor_paths_added": vendor_added,
    }


def _source_checkout_wrapper_probe() -> dict[str, Any]:
    """Prove a checkout wrapper or installed CLI starts without import leakage."""

    source_root = Path(__file__).resolve().parents[2]
    wrapper = source_root / "skill" / "scripts" / "sciplot"
    installed_cli = shutil.which("sciplot")
    command = str(wrapper) if wrapper.is_file() else installed_cli
    if command is None:
        return {
            "passed": False,
            "mode": "unavailable",
            "wrapper": str(wrapper),
            "installed_cli": installed_cli,
        }
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["SCIPLOT_PYTHON"] = sys.executable
    env["SCIPLOT_REPO"] = str(source_root)
    env["SCIPLOT_SOURCE_ROOT"] = str(source_root / "src")
    completed = subprocess.run(
        [command, "--help"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=30,
    )
    return {
        "passed": completed.returncode == 0
        and "Local SciPlot plotting" in completed.stdout,
        "mode": "source_checkout_wrapper" if wrapper.is_file() else "installed_cli",
        "wrapper": str(wrapper),
        "installed_cli": installed_cli,
        "returncode": completed.returncode,
        "source_root": str(source_root / "src"),
        "stderr": completed.stderr.strip(),
    }


def _qt_mainwindow_probe(document_path: Path | None = None) -> dict[str, Any]:
    """Construct the complete Veusz editor without requiring an Aqua session."""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    command = [sys.executable, "-m", "sciplot_core.cli", "studio"]
    if document_path is not None:
        command.append(str(document_path.expanduser().resolve()))
    command.append("--qt-smoke")
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=30,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {}
    settings_noise = "Error interpreting item" in completed.stderr
    passed = (
        completed.returncode == 0
        and payload.get("status") == "passed"
        and payload.get("window") == "MainWindow"
        and payload.get("main_window_constructed") is True
        and not settings_noise
    )
    if document_path is not None:
        passed = (
            passed
            and payload.get("document_loaded") is True
            and bool(payload.get("datasets"))
            and bool(payload.get("pages"))
        )
    return {
        "passed": passed,
        "returncode": completed.returncode,
        "window": payload.get("window"),
        "main_window_constructed": payload.get("main_window_constructed"),
        "document": payload.get("document"),
        "document_loaded": payload.get("document_loaded"),
        "datasets": payload.get("datasets"),
        "pages": payload.get("pages"),
        "settings_noise": settings_noise,
        "stderr": completed.stderr.strip(),
    }


def _portable_launcher_probe(
    project_dir: Path,
    *,
    ignore_runtime_overrides: bool = False,
    launcher_names: tuple[str, ...] = (
        "Open_in_SciPlot_Studio.command",
        "Open_in_Veusz.command",
        "Export_Edited_Veusz.command",
    ),
) -> dict[str, Any]:
    """Exercise generated launcher discovery without starting an interactive GUI."""

    results: list[dict[str, Any]] = []
    env = os.environ.copy()
    if ignore_runtime_overrides:
        for key in (
            "SCIPLOT_REPO",
            "SCIPLOT_RUNTIME_REPO",
            "SCIPLOT_VEUSZ_ROOT",
            "SCIPLOT_SOURCE_ROOT",
            "SCIPLOT_PYTHON",
        ):
            env.pop(key, None)
    for name in launcher_names:
        launcher = project_dir / name
        if not launcher.is_file():
            results.append(
                {
                    "launcher": str(launcher),
                    "exists": False,
                    "returncode": None,
                    "qt_smoke_passed": False,
                    "settings_noise": False,
                    "stderr": "Launcher is missing.",
                }
            )
            continue
        completed = subprocess.run(
            [str(launcher), "--check"],
            text=True,
            capture_output=True,
            check=False,
            env=env,
            timeout=30,
        )
        settings_noise = "Error interpreting item" in completed.stderr
        results.append(
            {
                "launcher": str(launcher),
                "exists": launcher.is_file(),
                "returncode": completed.returncode,
                "qt_smoke_passed": '"status": "passed"' in completed.stdout,
                "settings_noise": settings_noise,
                "stderr": completed.stderr.strip(),
            }
        )
    return {
        "passed": bool(results)
        and all(
            item["exists"]
            and item["returncode"] == 0
            and item["qt_smoke_passed"]
            and not item["settings_noise"]
            for item in results
        ),
        "launchers": results,
    }


def _relocated_delivery_launcher_probe(
    run_root: Path, delivery: dict[str, Any]
) -> dict[str, Any]:
    """Copy an editable delivery elsewhere and prove its launchers still load the VSZ."""

    source_value = delivery.get("path")
    if not source_value:
        return {
            "passed": False,
            "reason": "Delivery did not publish a portable package path.",
        }
    source = Path(str(source_value)).expanduser().resolve()
    if not source.is_dir():
        return {
            "passed": False,
            "reason": "Delivery package path is not a directory.",
            "source": str(source),
        }
    relocated = run_root / "relocated_delivery" / source.name
    if relocated.exists():
        shutil.rmtree(relocated)
    relocated.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, relocated)
    probe = _portable_launcher_probe(
        relocated,
        ignore_runtime_overrides=True,
        launcher_names=("Open_in_Veusz.command",),
    )
    probe.update(
        {
            "source": str(source),
            "relocated": str(relocated),
            "runtime_overrides_ignored": True,
        }
    )
    return probe


def _standalone_export_probe(run_root: Path, document_path: Path) -> dict[str, Any]:
    """Reproduce the real-world standalone-VSZ export path without a spec sidecar."""

    probe_root = run_root / "standalone_vsz_export"
    source_dir = probe_root / "source"
    artifact_root = probe_root / "artifacts"
    source_dir.mkdir(parents=True, exist_ok=True)
    standalone_document = source_dir / "standalone_exact_current.vsz"
    shutil.copy2(document_path, standalone_document)
    expected_spec = standalone_document.with_suffix(".spec.json")
    if expected_spec.exists():
        expected_spec.unlink()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "sciplot_core.cli",
            "studio",
            str(standalone_document),
            "--out",
            str(artifact_root),
            "--export",
            "pdf,tiff_300",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=os.environ.copy(),
        timeout=60,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {}
    receipt = (
        payload.get("standalone_export")
        if isinstance(payload.get("standalone_export"), dict)
        else {}
    )
    spec_reference = (
        receipt.get("spec_reference")
        if isinstance(receipt.get("spec_reference"), dict)
        else {}
    )
    exports = receipt.get("exports") if isinstance(receipt.get("exports"), list) else []
    export_paths = [
        Path(str(item.get("path"))).expanduser().resolve()
        for item in exports
        if isinstance(item, dict) and item.get("path")
    ]
    receipt_path = Path(str(receipt.get("receipt_path") or ""))
    qa_path = Path(str(receipt.get("artifact_qa_path") or ""))
    passed = (
        completed.returncode == 0
        and receipt.get("status") == "passed"
        and receipt.get("state") == "exported_exact_current"
        and receipt.get("export_ready") is True
        and receipt.get("requested_exports_complete") is True
        and (receipt.get("artifact_qa") or {}).get("status") == "passed"
        and receipt.get("project_delivery_complete") is False
        and spec_reference.get("exists") is False
        and spec_reference.get("path") is None
        and spec_reference.get("required_for_exact_current_export") is False
        and len(export_paths) == 2
        and all(
            path.is_file() and path.parent == (artifact_root / "figures").resolve()
            for path in export_paths
        )
        and receipt_path.is_file()
        and qa_path.is_file()
    )
    return {
        "passed": bool(passed),
        "returncode": completed.returncode,
        "document": str(standalone_document),
        "document_sha256": file_sha256(standalone_document),
        "spec_reference": spec_reference,
        "artifact_root": str(artifact_root),
        "exports": [str(path) for path in export_paths],
        "receipt": str(receipt_path),
        "qa_report": str(qa_path),
        "stderr": completed.stderr.strip(),
    }


def _write_synthetic_ftir(path: Path) -> dict[str, Any]:
    """Write a deterministic contract fixture; this is never real-data evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[float, float]] = []
    for wavenumber in range(4000, 399, -50):
        transmittance = (
            97.5
            - 30.0 * math.exp(-(((wavenumber - 3300.0) / 145.0) ** 2))
            - 18.0 * math.exp(-(((wavenumber - 1715.0) / 75.0) ** 2))
            - 12.0 * math.exp(-(((wavenumber - 1250.0) / 95.0) ** 2))
            - 8.0 * math.exp(-(((wavenumber - 760.0) / 65.0) ** 2))
        )
        rows.append((float(wavenumber), transmittance))
    path.write_text(
        "\n".join(f"{x_value:.1f},{y_value:.6f}" for x_value, y_value in rows) + "\n",
        encoding="utf-8",
    )
    return {
        "kind": "sciplot_generated_contract_fixture",
        "semantic_family": EXPECTED_RULE_ID,
        "path": str(path),
        "sha256": file_sha256(path),
        "point_count": len(rows),
        "real_data_evidence": False,
        "evidence_tier": "generated_synthetic_contract_fixture",
    }


def _data_mapping_studio_lifecycle_probe(
    *,
    run_root: Path,
    source_path: Path,
    base_request_path: Path,
) -> dict[str, Any]:
    from sciplot_core.canvas import (
        DataColumnMapping,
        DataMappingProposal,
        DataSourceReference,
    )
    from sciplot_core.data_mapping import (
        create_data_mapping_confirmation,
        execute_data_mapping_proposal,
        preview_data_mapping_proposal,
    )
    from sciplot_core.session_evidence_artifacts import (
        artifact_content_record,
        verify_regular_source_lineage,
    )
    from sciplot_core.studio import (
        export_studio_document,
        prepare_studio_document,
        publish_studio_export_run,
    )

    raw_hash_before = file_sha256(source_path)
    proposal = DataMappingProposal(
        proposal_id="runtime-smoke-mapping",
        base_request_sha256=file_sha256(base_request_path),
        provider="runtime_smoke_typed_provider",
        sources=(
            DataSourceReference(
                source_id="runtime_ftir",
                relative_path=source_path.name,
                sha256=raw_hash_before,
                header_row=None,
                delimiter=",",
            ),
        ),
        columns=(
            DataColumnMapping(
                source_id="runtime_ftir",
                source_column_index=0,
                output_column="wavenumber",
                role="x",
            ),
            DataColumnMapping(
                source_id="runtime_ftir",
                source_column_index=1,
                output_column="transmittance",
                role="y",
            ),
        ),
        sample_labels={"runtime_ftir": "runtime_ftir"},
        unit_overrides={
            "wavenumber": "cm^-1",
            "transmittance": "%",
        },
        request_patch={
            "recipe": "auto",
            "rule_id": "ftir_spectrum",
            "template": "stacked_curve",
            "series_order": ["runtime_ftir"],
        },
        confidence=1.0,
        rationale="Synthetic runtime mapping lifecycle fixture.",
    )
    preview = preview_data_mapping_proposal(
        proposal,
        source_root=source_path.parent,
        request_path=base_request_path,
    )
    confirmation = create_data_mapping_confirmation(
        proposal,
        source_root=source_path.parent,
        request_path=base_request_path,
        output_root=run_root / "mapped_projects",
        confirmed_by="runtime_smoke_noninteractive_operator",
    )
    execution = execute_data_mapping_proposal(
        proposal,
        confirmation,
        source_root=source_path.parent,
        request_path=base_request_path,
        output_root=run_root / "mapped_projects",
    )
    project_dir = Path(str(execution["output_root"]))
    prepared = prepare_studio_document(project_dir)
    document_path = Path(str(prepared["document"]))
    exported = export_studio_document(
        document_path,
        formats=["pdf", "tiff_300"],
    )
    published = publish_studio_export_run(
        project_dir=project_dir,
        request_path=Path(str(prepared["request"])),
        document_path=document_path,
        exports=list(exported.get("exports") or []),
        export_document_sha256=str(exported["document_sha256"]),
    )
    manifest_path = Path(str(published["manifest"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    coverage = (
        manifest.get("data_mapping_coverage")
        if isinstance(manifest.get("data_mapping_coverage"), dict)
        else {}
    )
    transform = (
        manifest.get("transform_ledger")
        if isinstance(manifest.get("transform_ledger"), dict)
        else {}
    )
    operations = [
        str(step.get("operation") or "")
        for step in transform.get("steps", [])
        if isinstance(step, dict)
    ]
    mapping_execution_path = project_dir / "execution.json"
    mapping_execution = json.loads(mapping_execution_path.read_text(encoding="utf-8"))
    source_record = artifact_content_record(source_path.parent)
    source_evidence = {
        "source_id": "source_01",
        "kind": "directory",
        "path": source_record["path"],
        "file_count": source_record["member_count"],
        "size_bytes": source_record["size_bytes"],
        "tree_sha256": "",
        "artifact_sha256": source_record["sha256"],
        "members": source_record["members"],
    }
    witnessed_mapping = {
        "path": str(mapping_execution_path.resolve()),
        "sha256": file_sha256(mapping_execution_path),
        "proposal_id": mapping_execution["proposal_id"],
        "proposal_sha256": mapping_execution["proposal_sha256"],
        "provider": mapping_execution["provider"],
        "confirmation_id": mapping_execution["confirmation_id"],
        "transform_ledger_sha256": mapping_execution["transform_ledger_sha256"],
        "raw_inputs_unchanged": True,
        "handoff_allowed": True,
    }
    try:
        verified_lineage = verify_regular_source_lineage(
            manifest,
            preregistration={
                "sources": [source_evidence],
                "expected_evidence": ["data_mapping"],
            },
            witnessed_mapping=witnessed_mapping,
        )
        lineage_error = None
    except (OSError, TypeError, ValueError) as exc:
        verified_lineage = None
        lineage_error = str(exc)
    forged_manifest = copy.deepcopy(manifest)
    forged_steps = (forged_manifest.get("transform_ledger") or {}).get("steps")
    if isinstance(forged_steps, list) and forged_steps:
        forged_steps[0]["operation"] = "forged_mapping_operation"
    try:
        verify_regular_source_lineage(
            forged_manifest,
            preregistration={
                "sources": [source_evidence],
                "expected_evidence": ["data_mapping"],
            },
            witnessed_mapping=witnessed_mapping,
        )
    except ValueError:
        forged_mapping_rejected = True
    else:
        forged_mapping_rejected = False
    raw_hash_after = file_sha256(source_path)
    passed = bool(
        preview.get("writes_performed") is False
        and execution.get("raw_inputs_unchanged") is True
        and raw_hash_before == raw_hash_after
        and Path(str(execution["request_candidate"])).name == "plot_request.json"
        and int(prepared.get("series_count") or 0) == 1
        and coverage.get("status") == "passed"
        and coverage.get("actual_series_labels") == ["runtime_ftir"]
        and operations[:2]
        == [
            "execute_confirmed_data_mapping_proposal",
            "reformat_and_order_ftir_spectra",
        ]
        and manifest.get("ready_to_use") is True
        and (manifest.get("qa") or {}).get("status") == "passed"
        and (manifest.get("delivery_package") or {}).get("complete") is True
        and isinstance(verified_lineage, dict)
        and verified_lineage.get("mapping_bound") is True
        and forged_mapping_rejected
    )
    return {
        "passed": passed,
        "preview_status": preview.get("status"),
        "execution": str(project_dir / "execution.json"),
        "request_candidate": execution.get("request_candidate"),
        "document": str(document_path),
        "manifest": str(manifest_path),
        "raw_hash_before": raw_hash_before,
        "raw_hash_after": raw_hash_after,
        "series_count": prepared.get("series_count"),
        "coverage": coverage,
        "operations": operations,
        "verified_lineage": verified_lineage,
        "lineage_error": lineage_error,
        "forged_mapping_rejected": forged_mapping_rejected,
        "qa_status": (manifest.get("qa") or {}).get("status"),
        "publication_status": ((manifest.get("qa") or {}).get("publication") or {}).get(
            "status"
        ),
        "delivery_complete": (manifest.get("delivery_package") or {}).get("complete"),
        "ready_to_use": manifest.get("ready_to_use"),
        "real_data_evidence": False,
    }


def _transform_parameters(result: dict[str, Any]) -> dict[str, Any]:
    steps = (
        result.get("transform_steps")
        if isinstance(result.get("transform_steps"), list)
        else []
    )
    first = steps[0] if steps and isinstance(steps[0], dict) else {}
    parameters = first.get("parameters")
    return parameters if isinstance(parameters, dict) else {}


def _semantic_parser_probe(run_root: Path) -> dict[str, Any]:
    """Exercise promoted real-data table shapes with generated contract data."""

    import pandas as pd

    from sciplot_core.materials_rules import compute_analysis_metrics
    from sciplot_core.semantic import classify_source, prepare_semantic_source
    from sciplot_core.studio import (
        StudioPreparationBlocked,
        StudioSeries,
        StudioSourceFrame,
        _apply_series_options,
        _apply_series_domain_contract_defaults,
        _semantic_payload_with_exact_current_axes,
        _semantic_payload_with_terminal_axes,
        derive_terminal_render_data_contract,
        _series_from_frame_records,
        _validate_log_domain_series,
        _veusz_spec_path,
    )

    contracts = run_root / "semantic_contracts"

    saxs_source = contracts / "saxs_profile" / "paired_q_intensity.csv"
    saxs_source.parent.mkdir(parents=True, exist_ok=True)
    saxs_source.write_text(
        "HDPE,,2 wt% UDC 3,\n"
        "q (nm-1),Log intensity (a.u.),q (nm-1),Log intensity (a.u.)\n"
        "0.01,1000,0.01,100000\n"
        "0.02,500,0.02,50000\n"
        "0.05,100,0.05,10000\n"
        "0.10,25,0.10,2500\n",
        encoding="utf-8",
    )
    saxs_semantic = classify_source(saxs_source)
    saxs_result = prepare_semantic_source(
        saxs_source,
        output_dir=contracts / "saxs_output",
        semantic=saxs_semantic,
    )
    saxs_parameters = _transform_parameters(saxs_result)

    gpc_dir = contracts / "gpc_sec_chromatogram"
    gpc_dir.mkdir(parents=True, exist_ok=True)
    gpc_source = gpc_dir / "8.xlsx"
    pd.DataFrame(
        [
            ["SampleName", "8"],
            ["DetectorType", "DetectorUnits"],
            ["RI", "mV"],
            ["RT (mins)", "RI"],
            [1.0, 10.0],
            [1.5, 25.0],
            [2.0, 12.0],
            [2.5, 4.0],
        ]
    ).to_excel(gpc_source, sheet_name="Slice Table", header=False, index=False)
    gpc_semantic = classify_source(gpc_dir)
    gpc_result = prepare_semantic_source(
        gpc_dir,
        output_dir=contracts / "gpc_output",
        semantic=gpc_semantic,
    )
    gpc_parameters = _transform_parameters(gpc_result)

    impact_dir = contracts / "impact_metric"
    impact_dir.mkdir(parents=True, exist_ok=True)
    impact_source = impact_dir / "impact strength.xlsx"
    with pd.ExcelWriter(impact_source) as writer:
        for thickness, offset in (("2 mm", 0.0), ("4 mm", 10.0)):
            pd.DataFrame(
                [
                    ["Re", "Re"],
                    ["kJ/m2", "kJ/m2"],
                    ["V-PA", "E-PA"],
                    [1.0 + offset, 2.0 + offset],
                    [1.2 + offset, 2.2 + offset],
                    [1.4 + offset, 2.4 + offset],
                ]
            ).to_excel(writer, sheet_name=thickness, header=False, index=False)
    impact_semantic = classify_source(impact_source)
    impact_result = prepare_semantic_source(
        impact_source,
        output_dir=contracts / "impact_output",
        semantic=impact_semantic,
    )
    impact_parameters = _transform_parameters(impact_result)
    impact_metric_rows = compute_analysis_metrics(
        source_path=impact_source,
        processed_source=impact_source,
        semantic=impact_semantic,
        output_dir=contracts / "impact_metrics",
    )

    swelling_source = contracts / "explicit_rule" / "parallel_blocks.csv"
    swelling_source.parent.mkdir(parents=True, exist_ok=True)
    swelling_rows: list[list[object]] = [
        [
            "Sample Name:",
            "Fig 3 (a): SH_DI water",
            "",
            "",
            "",
            "",
            "",
            "Fig 3 (b): SH_1000 mM NaCl",
            "",
            "",
            "",
            "",
            "",
            "Fig 3 (c): SH_0.1 wt% PAA",
            "",
            "",
            "",
            "",
            "",
        ],
        ["Data Set N°", 1, "", 2, "", 3, "", 1, "", 2, "", 3, "", 1, "", 2, "", 3, ""],
        ["Axis Cordinates:", *(["Time (s)", "Ai/A0 (unitless)"] * 9)],
    ]
    for point_index in range(5):
        row: list[object] = [""]
        for series_index in range(9):
            row.extend(
                [
                    point_index * 100 + series_index * 5,
                    1.0 + point_index * 0.03 + series_index * 0.001,
                ]
            )
        swelling_rows.append(row)
    swelling_rows.extend(
        [
            [""] * 19,
            [""] * 19,
            [
                "",
                "",
                "",
                "",
                "",
                "",
                72000,
                72.6,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ],
            [
                "",
                "",
                "",
                "",
                "",
                "",
                73000,
                72.7,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ],
        ]
    )
    swelling_source.write_text(
        "\n".join(",".join(str(value) for value in row) for row in swelling_rows)
        + "\n",
        encoding="utf-8",
    )
    swelling_semantic = classify_source(
        swelling_source, requested_rule_id="swelling_curve"
    )
    swelling_result = prepare_semantic_source(
        swelling_source,
        output_dir=contracts / "swelling_output",
        semantic=swelling_semantic,
    )
    swelling_parameters = _transform_parameters(swelling_result)
    styled_swelling_series = _apply_series_options(
        [
            StudioSeries(
                label=label,
                x_name=f"x_{index}",
                y_name=f"y_{index}",
                x_values=(0.0, 1.0),
                y_values=(1.0, 1.1),
                color="#000000",
            )
            for index, label in enumerate(
                swelling_parameters.get("series_order") or [], start=1
            )
        ],
        render_options=dict(swelling_semantic.get("render_options") or {}),
        request={"template": "point_line", "rule_id": "swelling_curve"},
    )
    swelling_non_color_signatures = [
        (item.line_style, str(item.marker)) for item in styled_swelling_series
    ]
    swelling_colors = [item.color for item in styled_swelling_series]
    swelling_condition_groups = [
        styled_swelling_series[index : index + 3]
        for index in range(0, len(styled_swelling_series), 3)
    ]

    amplitude_frame = pd.DataFrame(
        {
            "Strain": ["%", "Sample A", 0.1, 1.0, 10.0],
            "Storage Modulus": ["Pa", "Sample A", 1200.0, 1100.0, 900.0],
            "Loss Modulus": ["Pa", "Sample A", 240.0, 260.0, 300.0],
            "Loss Factor": ["1", "Sample A", 0.2, 0.24, 0.33],
            "Strain.1": ["%", "Sample B", 0.1, 1.0, 10.0],
            "Storage Modulus.1": ["Pa", "Sample B", 1800.0, 1600.0, 1300.0],
            "Loss Modulus.1": ["Pa", "Sample B", 300.0, 340.0, 390.0],
            "Loss Factor.1": ["1", "Sample B", 0.17, 0.21, 0.3],
        }
    )
    amplitude_source = contracts / "rheology_strain_sweep" / "comparison.csv"
    amplitude_source.parent.mkdir(parents=True, exist_ok=True)
    amplitude_source.write_text("synthetic contract frame\n", encoding="utf-8")
    amplitude_record = StudioSourceFrame(
        label="comparison",
        path=amplitude_source,
        sha256=file_sha256(amplitude_source),
        frame=amplitude_frame,
    )
    default_amplitude_series, default_amplitude_axis = _series_from_frame_records(
        {
            "template": "point_line",
            "rule_id": "rheology_strain_sweep",
            "series_order": ["Sample A", "Sample B"],
            "render_options": {"xscale": "log", "yscale": "log"},
            "explicit_render_option_keys": [],
            "study_model": {
                "figure_queue": [{"x_metric": "x", "y_metric": "y"}],
            },
        },
        frames=[amplitude_record],
    )
    loss_factor_series, loss_factor_axis = _series_from_frame_records(
        {
            "template": "point_line",
            "rule_id": "rheology_strain_sweep",
            "y_metric": "loss_factor",
            "series_order": ["Sample A", "Sample B"],
            "render_options": {"xscale": "log", "yscale": "log"},
            "explicit_render_option_keys": [],
        },
        frames=[amplitude_record],
    )

    positive_xrd_series = [
        StudioSeries(
            label="XRD",
            x_name="xrd_x",
            y_name="xrd_y",
            x_values=(3.0, 20.0, 50.0),
            y_values=(800.0, 5000.0, 900.0),
            color="#000000",
        )
    ]
    positive_xrd_options = _apply_series_domain_contract_defaults(
        {},
        request={
            "rule_id": "xrd_pattern",
            "render_options": {},
            "explicit_render_option_keys": [],
        },
        series=positive_xrd_series,
    )
    negative_xrd_options = _apply_series_domain_contract_defaults(
        {},
        request={
            "rule_id": "xrd_pattern",
            "render_options": {},
            "explicit_render_option_keys": [],
        },
        series=[
            StudioSeries(
                label="background-subtracted XRD",
                x_name="xrd_negative_x",
                y_name="xrd_negative_y",
                x_values=(3.0, 20.0, 50.0),
                y_values=(-5.0, 5000.0, 10.0),
                color="#000000",
            )
        ],
    )
    noisy_relaxation_options = _apply_series_domain_contract_defaults(
        {
            "y_min": -0.05,
            "y_max": 1.05,
            "y_ticks": [0.0, 0.25, 0.5, 0.75, 1.0],
        },
        request={
            "rule_id": "rheology_stress_relaxation",
            "render_options": {},
            "explicit_render_option_keys": [],
        },
        series=[
            StudioSeries(
                label="noisy relaxation",
                x_name="relaxation_x",
                y_name="relaxation_y",
                x_values=(0.01, 0.1, 1.0),
                y_values=(0.9, -0.47, 0.1),
                color="#000000",
            )
        ],
    )
    xrd_terminal_source = contracts / "xrd_pattern" / "terminal.csv"
    xrd_terminal_source.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "2theta": ["degree", "PDA-I", 3.0, 9.0, 20.0],
            "Intensity": ["count", "PDA-I", 2.0, 10.0, 1.0],
            "2theta.1": ["degree", "PDA-Br", 3.0, 7.0, 20.0],
            "Intensity.1": ["count", "PDA-Br", 1.0, 8.0, 2.0],
        }
    ).to_csv(xrd_terminal_source, index=False)
    xrd_terminal_contract = derive_terminal_render_data_contract(
        request={
            "template": "curve",
            "rule_id": "xrd_pattern",
            "series_order": ["pda_xrd_patterns"],
            "render_options": {},
            "explicit_render_option_keys": [],
            "study_model": {
                "sample_order": ["pda_xrd_patterns"],
                "figure_queue": [
                    {
                        "evidence_contract": {
                            "confirmation_status": "inferred",
                        }
                    }
                ],
            },
        },
        terminal_sources=[xrd_terminal_source],
    )
    xrd_terminal_labels = [
        str(unit.get("label") or "")
        for unit in xrd_terminal_contract.get("units") or []
        if isinstance(unit, dict)
    ]
    xrd_terminal_axes = (
        (xrd_terminal_contract.get("units") or [{}])[0].get("axes") or {}
    )
    try:
        _apply_series_options(
            positive_xrd_series,
            render_options={},
            request={
                "template": "curve",
                "rule_id": "xrd_pattern",
                "series_order": ["manual typo"],
                "study_model": {
                    "sample_order": ["XRD"],
                    "figure_queue": [
                        {
                            "evidence_contract": {
                                "confirmation_status": "confirmed",
                            }
                        }
                    ],
                },
            },
        )
    except StudioPreparationBlocked as exc:
        manual_order_rejection = {
            "reason_code": exc.reason_code,
            "message": str(exc),
        }
    else:
        manual_order_rejection = None

    ftir_terminal_source = contracts / "ftir_spectrum" / "terminal.csv"
    ftir_terminal_source.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "Wavenumber": ["cm^-1", "Percent T", 4000.0, 3000.0, 2000.0],
            "Transmittance": ["%", "Percent T", 90.0, 82.0, 75.0],
            "Wavenumber.1": [
                "cm^-1",
                "Hidden trace",
                4000.0,
                3000.0,
                2000.0,
            ],
            "Transmittance.1": [
                "%",
                "Hidden trace",
                88.0,
                80.0,
                72.0,
            ],
        }
    ).to_csv(ftir_terminal_source, index=False)
    ftir_terminal_contract = derive_terminal_render_data_contract(
        request={
            "template": "stacked_curve",
            "rule_id": "ftir_spectrum",
            "series_order": ["Percent T", "Hidden trace"],
            "render_options": {
                "y_label_override": "Absorbance (offset)",
                "series_include": ["Percent T"],
            },
            "explicit_render_option_keys": [],
        },
        terminal_sources=[ftir_terminal_source],
    )
    ftir_terminal_unit = (ftir_terminal_contract.get("units") or [{}])[0]
    ftir_terminal_axes = ftir_terminal_unit.get("axes") or {}

    gpc_axis_document = contracts / "axis_authority" / "gpc_document.vsz"
    gpc_axis_document.parent.mkdir(parents=True, exist_ok=True)
    gpc_axis_document.write_text(
        "# synthetic axis-authority contract\n",
        encoding="utf-8",
    )
    _veusz_spec_path(gpc_axis_document).write_text(
        json.dumps(
            {
                "axes": {
                    "x": {
                        "label": "Elution time (min)",
                        "scale": "linear",
                        "min": 1.0,
                        "max": 3.0,
                    },
                    "y": {
                        "label": "Detector response (mV)",
                        "scale": "linear",
                        "min": 0.0,
                        "max": 30.0,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    gpc_effective_semantic = _semantic_payload_with_terminal_axes(
        gpc_semantic,
        document_path=gpc_axis_document,
    )

    ftir_axis_document = contracts / "axis_authority" / "ftir_document.vsz"
    ftir_axis_document.write_text(
        "# synthetic axis-authority contract\n",
        encoding="utf-8",
    )
    ftir_axis_spec = {
        "x": {
            "label": "Wavenumber (cm^{-1})",
            "scale": "linear",
            "min": 4000.0,
            "max": 400.0,
        },
        "y": {
            "label": "Absorbance (a.u.)",
            "scale": "linear",
            "min": 0.0,
            "max": 0.5,
        },
    }
    _veusz_spec_path(ftir_axis_document).write_text(
        json.dumps({"axes": ftir_axis_spec}),
        encoding="utf-8",
    )
    ftir_absorbance_semantic = classify_source(
        ftir_terminal_source,
        requested_rule_id="ftir_spectrum",
    )
    ftir_effective_semantic = _semantic_payload_with_terminal_axes(
        ftir_absorbance_semantic,
        document_path=ftir_axis_document,
    )
    ftir_exact_semantic = _semantic_payload_with_exact_current_axes(
        ftir_effective_semantic,
        qa={
            "publication": {
                "veusz_document_audit": {
                    "documents": [
                        {
                            "path": str(ftir_axis_document.resolve()),
                            "sha256": file_sha256(ftir_axis_document),
                            "axes": [
                                {
                                    "name": axis_name,
                                    **axis_payload,
                                    "hidden": False,
                                }
                                for axis_name, axis_payload in ftir_axis_spec.items()
                            ],
                        }
                    ]
                }
            }
        },
        document_path=ftir_axis_document,
    )
    try:
        _validate_log_domain_series(
            [
                StudioSeries(
                    label="invalid log trace",
                    x_name="log_x",
                    y_name="log_y",
                    x_values=(0.01, 0.1, 1.0),
                    y_values=(10.0, 0.0, 1.0),
                    color="#000000",
                )
            ],
            render_options={"xscale": "log", "yscale": "log"},
        )
    except StudioPreparationBlocked as exc:
        log_domain_rejection = {
            "reason_code": exc.reason_code,
            "message": str(exc),
        }
    else:
        log_domain_rejection = None

    expected_saxs_order = ["HDPE", "2 wt% UDC 3"]
    expected_impact_order = ["V-PA (2 mm)", "E-PA (2 mm)", "V-PA (4 mm)", "E-PA (4 mm)"]
    expected_impact_metric_names = {
        f"impact_group_{metric}[{sample}]"
        for sample in expected_impact_order
        for metric in ("n", "median", "iqr")
    }
    impact_metric_names = {str(row.get("metric") or "") for row in impact_metric_rows}
    expected_swelling_order = [
        f"{condition} replicate {replicate}"
        for condition in ("SH DI water", "SH 1000 mM NaCl", "SH 0.1 wt% PAA")
        for replicate in range(1, 4)
    ]
    swelling_selections = swelling_parameters.get("source_selections") or []
    first_swelling_selection = swelling_selections[0] if swelling_selections else {}
    first_swelling_block = first_swelling_selection.get("source_block") or {}
    first_time_conversion = first_swelling_selection.get("time_conversion") or {}
    passed = (
        saxs_semantic.get("rule_id") == "saxs_profile"
        and saxs_parameters.get("series_order") == expected_saxs_order
        and saxs_parameters.get("source_point_counts") == [4, 4]
        and (saxs_semantic.get("axis_plan") or {}).get("x", {}).get("scale") == "log"
        and (saxs_semantic.get("axis_plan") or {}).get("y", {}).get("scale") == "log"
        and gpc_semantic.get("rule_id") == "gpc_sec_chromatogram"
        and gpc_parameters.get("series_order") == ["Sample 8"]
        and gpc_parameters.get("source_point_counts") == [4]
        and (gpc_parameters.get("source_selections") or [{}])[0].get("detector_unit")
        == "mV"
        and impact_semantic.get("rule_id") == "impact_metric"
        and impact_parameters.get("sample_order") == expected_impact_order
        and impact_parameters.get("replicate_count_total") == 12
        and impact_metric_names == expected_impact_metric_names
        and all(row.get("status") == "ok" for row in impact_metric_rows)
        and swelling_semantic.get("rule_id") == "swelling_curve"
        and swelling_semantic.get("confidence") == 100.0
        and swelling_parameters.get("series_order") == expected_swelling_order
        and swelling_parameters.get("source_point_counts") == [5] * 9
        and first_swelling_block.get("selection_policy")
        == "contiguous_labeled_swelling_block"
        and first_swelling_block.get("excluded_disconnected_rows") == 2
        and math.isclose(
            float(first_time_conversion.get("factor") or 0.0), 1.0 / 3600.0
        )
        and len(swelling_condition_groups) == 3
        and all(len({item.color for item in group}) == 1 for group in swelling_condition_groups)
        and len({group[0].color for group in swelling_condition_groups if group}) == 3
        and all(
            len({(item.line_style, str(item.marker)) for item in group}) == 3
            for group in swelling_condition_groups
        )
        and [item.label for item in default_amplitude_series]
        == ["Sample A", "Sample B"]
        and [item.y_values for item in default_amplitude_series]
        == [(1200.0, 1100.0, 900.0), (1800.0, 1600.0, 1300.0)]
        and "G" in str(default_amplitude_axis.get("y_label") or "")
        and "Pa" in str(default_amplitude_axis.get("y_label") or "")
        and [item.label for item in loss_factor_series]
        == ["Sample A", "Sample B"]
        and [item.y_values for item in loss_factor_series]
        == [(0.2, 0.24, 0.33), (0.17, 0.21, 0.3)]
        and "tan" in str(loss_factor_axis.get("y_label") or "").casefold()
        and positive_xrd_options.get("x_min") == 0.0
        and positive_xrd_options.get("y_min") == 0.0
        and negative_xrd_options.get("x_min") == 0.0
        and "y_min" not in negative_xrd_options
        and "y_min" not in noisy_relaxation_options
        and "y_ticks" not in noisy_relaxation_options
        and noisy_relaxation_options.get("y_max") == 1.05
        and (xrd_terminal_axes.get("x") or {}).get("min") == 0.0
        and (xrd_terminal_axes.get("y") or {}).get("min") == 0.0
        and xrd_terminal_labels == ["PDA-I", "PDA-Br"]
        and (manual_order_rejection or {}).get("reason_code")
        == "unknown_series_order"
        and (
            (gpc_effective_semantic.get("axis_plan") or {})
            .get("y", {})
            .get("canonical_unit")
            == "mV"
        )
        and (
            (gpc_effective_semantic.get("registered_axis_plan") or {})
            .get("y", {})
            .get("canonical_unit")
            == "a.u."
        )
        and (
            (ftir_exact_semantic.get("axis_plan") or {})
            .get("y", {})
            .get("canonical_label")
            == "Absorbance"
        )
        and (
            (ftir_exact_semantic.get("axis_plan") or {})
            .get("y", {})
            .get("canonical_unit")
            == "a.u."
        )
        and (ftir_exact_semantic.get("axis_authority") or {}).get("status")
        == "exact_current"
        and "Transmittance"
        in str((ftir_terminal_axes.get("y") or {}).get("label") or "")
        and "Absorbance"
        not in str((ftir_terminal_axes.get("y") or {}).get("label") or "")
        and ftir_terminal_unit.get("y_values") == [90.0, 82.0, 75.0]
        and ftir_terminal_contract.get("unit_count") == 1
        and (ftir_terminal_axes.get("y") or {}).get("show_ticks") is True
        and (log_domain_rejection or {}).get("reason_code")
        == "log_axis_nonpositive_data"
    )
    return {
        "passed": passed,
        "saxs": {
            "rule_id": saxs_semantic.get("rule_id"),
            "series_order": saxs_parameters.get("series_order"),
            "point_counts": saxs_parameters.get("source_point_counts"),
            "xscale": (saxs_semantic.get("axis_plan") or {}).get("x", {}).get("scale"),
            "yscale": (saxs_semantic.get("axis_plan") or {}).get("y", {}).get("scale"),
        },
        "gpc": {
            "rule_id": gpc_semantic.get("rule_id"),
            "series_order": gpc_parameters.get("series_order"),
            "point_counts": gpc_parameters.get("source_point_counts"),
            "source_selections": gpc_parameters.get("source_selections"),
        },
        "impact": {
            "rule_id": impact_semantic.get("rule_id"),
            "sample_order": impact_parameters.get("sample_order"),
            "replicate_count_total": impact_parameters.get("replicate_count_total"),
            "analysis_metric_names": sorted(impact_metric_names),
            "analysis_metric_count": len(impact_metric_rows),
        },
        "swelling": {
            "rule_id": swelling_semantic.get("rule_id"),
            "confidence": swelling_semantic.get("confidence"),
            "series_order": swelling_parameters.get("series_order"),
            "point_counts": swelling_parameters.get("source_point_counts"),
            "first_source_selection": first_swelling_selection,
            "colors": swelling_colors,
            "non_color_signatures": swelling_non_color_signatures,
        },
        "amplitude_sweep": {
            "default_labels": [item.label for item in default_amplitude_series],
            "default_y_values": [item.y_values for item in default_amplitude_series],
            "default_axis": default_amplitude_axis,
            "loss_factor_labels": [item.label for item in loss_factor_series],
            "loss_factor_y_values": [item.y_values for item in loss_factor_series],
            "loss_factor_axis": loss_factor_axis,
        },
        "axis_domain_contracts": {
            "positive_xrd_options": positive_xrd_options,
            "negative_xrd_options": negative_xrd_options,
            "noisy_relaxation_options": noisy_relaxation_options,
            "xrd_terminal_axes": xrd_terminal_axes,
            "xrd_terminal_labels": xrd_terminal_labels,
            "manual_order_rejection": manual_order_rejection,
            "gpc_effective_axis_plan": gpc_effective_semantic.get("axis_plan"),
            "gpc_registered_axis_plan": gpc_effective_semantic.get(
                "registered_axis_plan"
            ),
            "ftir_absorbance_effective_axis_plan": ftir_exact_semantic.get(
                "axis_plan"
            ),
            "ftir_absorbance_axis_authority": ftir_exact_semantic.get(
                "axis_authority"
            ),
            "ftir_terminal_axes": ftir_terminal_axes,
            "ftir_terminal_y_values": ftir_terminal_unit.get("y_values"),
            "log_domain_rejection": log_domain_rejection,
        },
    }


def _direct_label_contract_probe(run_root: Path) -> dict[str, Any]:
    """Exercise source-bound direct-label geometry and overlay controls."""

    import pandas as pd

    from sciplot_core.render import render_to_dir
    from sciplot_core.source_coverage import (
        verify_rendered_mapping_source_coverage,
    )

    root = run_root / "direct_label_contract"
    source = root / "stacked_curves.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "wavenumber": [1000.0, 1500.0, 2000.0, 2500.0],
            "sample_a": [0.2, 0.8, 0.5, 0.3],
            "sample_b": [0.4, 0.3, 0.9, 0.6],
        }
    ).to_csv(source, index=False)
    render_options = {
        "size": "60x55",
        "series_label_mode": "inline",
        "legend_position": "none",
    }
    rendered = render_to_dir(
        source,
        template="stacked_curve",
        output_dir=root / "rendered",
        options=render_options,
        export_formats=("pdf",),
    )
    document = Path(str((rendered.get("veusz_documents") or [""])[0]))
    spec = Path(str((rendered.get("veusz_specs") or [""])[0]))
    coverage_request = {
        "template": "stacked_curve",
        "render_options": dict(render_options),
    }
    mapping_application = {
        "proposal_id": "runtime-smoke-direct-label-coverage",
        "mapped_outputs": [
            {
                "path": str(source.resolve()),
                "sha256": file_sha256(source),
            }
        ],
    }
    coverage_input = {
        **rendered,
        "data_snapshot_source": str(source.resolve()),
    }
    baseline_coverage = verify_rendered_mapping_source_coverage(
        coverage_input,
        mapping_application=mapping_application,
        request=coverage_request,
    )
    document_text = document.read_text(encoding="utf-8")
    spec_text = spec.read_text(encoding="utf-8")
    baseline_spec = json.loads(spec_text)
    baseline_labels = baseline_spec.get("direct_labels")
    baseline_widgets = _inspect_veusz_document_state(document)["widgets"]
    attacks = {
        "position_changed": (
            "Set('xPos', [0.5])",
            "xPos",
        ),
        "size_inflated": (
            "Set('Text/size', '1000pt')",
            "Text/size",
        ),
        "text_color_changed": (
            "Set('Text/color', '#FFFFFF')",
            "Text/color",
        ),
        "background_unhidden": (
            "Set('Background/hide', False)",
            "Background/hide",
        ),
        "border_unhidden": (
            "Set('Border/hide', False)",
            "Border/hide",
        ),
    }
    target_path = "/page1/graph1/label_1"
    materialization_results: dict[str, bool] = {}
    rejection_results: dict[str, bool] = {}
    for attack_id, (command, setting_path) in attacks.items():
        attacked_document = (
            document_text
            + f"\nTo('{target_path}')\n"
            + command
            + "\nTo('/')\n"
        )
        try:
            document.write_text(attacked_document, encoding="utf-8")
            attacked_widgets = _inspect_veusz_document_state(document)[
                "widgets"
            ]
            materialization_results[attack_id] = (
                baseline_widgets.get(target_path, {})
                .get("settings", {})
                .get(setting_path)
                != attacked_widgets.get(target_path, {})
                .get("settings", {})
                .get(setting_path)
            )
            verify_rendered_mapping_source_coverage(
                coverage_input,
                mapping_application=mapping_application,
                request=coverage_request,
            )
        except (OSError, RuntimeError, ValueError):
            rejection_results[attack_id] = True
            materialization_results.setdefault(attack_id, False)
        else:
            rejection_results[attack_id] = False
        finally:
            document.write_text(document_text, encoding="utf-8")

    coordinated_materialized = False
    coordinated_rejected = False
    if isinstance(baseline_labels, list) and baseline_labels:
        forged_spec = json.loads(spec_text)
        forged_labels = forged_spec.get("direct_labels")
        if isinstance(forged_labels, list) and forged_labels:
            original_x = float(forged_labels[0]["x"])
            replacement_x = (
                0.5
                if not math.isclose(original_x, 0.5)
                else 0.25
            )
            forged_labels[0]["x"] = replacement_x
            forged_spec_text = json.dumps(
                forged_spec,
                indent=2,
                ensure_ascii=False,
            )
            forged_document_text = (
                document_text
                + f"\nTo('{target_path}')\n"
                + f"Set('xPos', [{replacement_x!r}])\n"
                + "To('/')\n"
            )
            try:
                spec.write_text(forged_spec_text, encoding="utf-8")
                document.write_text(
                    forged_document_text,
                    encoding="utf-8",
                )
                forged_x = (
                    _inspect_veusz_document_state(document)["widgets"]
                    .get(target_path, {})
                    .get("settings", {})
                    .get("xPos")
                )
                baseline_x = (
                    baseline_widgets.get(target_path, {})
                    .get("settings", {})
                    .get("xPos")
                )
                coordinated_materialized = (
                    forged_spec_text != spec_text
                    and forged_x != baseline_x
                )
                verify_rendered_mapping_source_coverage(
                    coverage_input,
                    mapping_application=mapping_application,
                    request=coverage_request,
                )
            except (OSError, RuntimeError, ValueError):
                coordinated_rejected = True
            finally:
                spec.write_text(spec_text, encoding="utf-8")
                document.write_text(document_text, encoding="utf-8")

    expected_attack_ids = frozenset(attacks)
    passed = (
        baseline_coverage.get("status") == "passed"
        and isinstance(baseline_labels, list)
        and len(baseline_labels) == 2
        and set(materialization_results) == expected_attack_ids
        and all(materialization_results.values())
        and set(rejection_results) == expected_attack_ids
        and all(rejection_results.values())
        and coordinated_materialized
        and coordinated_rejected
    )
    return {
        "passed": bool(passed),
        "source": str(source),
        "document": str(document),
        "spec": str(spec),
        "baseline_status": baseline_coverage.get("status"),
        "direct_label_count": (
            len(baseline_labels)
            if isinstance(baseline_labels, list)
            else 0
        ),
        "expected_attack_ids": sorted(expected_attack_ids),
        "materialization_results": materialization_results,
        "rejection_results": rejection_results,
        "coordinated_spec_vsz_forgery_materialized": (
            coordinated_materialized
        ),
        "coordinated_spec_vsz_forgery_rejected": coordinated_rejected,
        "real_data_evidence": False,
        "evidence_tier": "generated_synthetic_contract_fixture",
    }


def _scalar_field_render_probe(run_root: Path) -> dict[str, Any]:
    """Exercise the public XYZ-to-Veusz scalar-field contract."""

    import pandas as pd

    from sciplot_core.render import render_to_dir
    from sciplot_core.source_coverage import (
        verify_rendered_mapping_source_coverage,
    )
    from sciplot_core.studio import _reference_guide_rect_contracts

    source = run_root / "scalar_field_contract" / "field_xyz.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "thickness_mm": [-2.0, 0.0, 2.0, -2.0, 0.0, 2.0],
            "in_plane_mm": [0.0, 0.0, 0.0, 20.0, 20.0, 20.0],
            "temperature_C": [125.0, 265.0, 125.0, 125.0, 265.0, 125.0],
        }
    ).to_csv(source, index=False)
    scalar_options = {
        "size": "60x55",
        "data_variables": {
            "x": "thickness_mm",
            "y": "in_plane_mm",
            "z": "temperature_C",
        },
        "z_min": 125.0,
        "z_max": 265.0,
        "z_ticks": [125.0, 195.0, 265.0],
        "z_tick_format": "%.0f",
        "contour_levels": [160.0, 230.0],
        "highlight_contour_levels": [195.0],
        "reference_guides": [
            {
                "id": "safe_temperature_transition_band",
                "kind": "band",
                "axis": "x",
                "start": -0.5,
                "end": 0.5,
                "color": "#CBD5E1",
                "transparency": 85,
            },
            {
                "id": "safe_temperature_reference_line",
                "kind": "line",
                "axis": "x",
                "value": 0.0,
                "color": "#64748B",
                "transparency": 40,
                "line_width_pt": 1.1,
                "line_style": "dash-dot",
            },
        ],
        "show_colorbar": True,
        "colorbar_width_mm": 29.5,
        "colorbar_height_mm": 2.8,
        "colorbar_foreground_color": "#223344",
        "colorbar_background_color": "#F7F7F7",
        "colorbar_background_transparency": 85,
        "colorbar_background_x_fraction": 0.52,
        "colorbar_background_y_fraction": 0.84,
        "colorbar_background_width_fraction": 0.48,
        "colorbar_background_height_fraction": 0.22,
    }
    rendered = render_to_dir(
        source,
        template="heatmap",
        output_dir=source.parent / "rendered",
        options=scalar_options,
        export_formats=("pdf",),
    )
    outputs = [Path(str(path)) for path in rendered.get("outputs") or []]
    document = Path(str((rendered.get("veusz_documents") or [""])[0]))
    spec = Path(str((rendered.get("veusz_specs") or [""])[0]))
    coverage_request = {
        "template": "heatmap",
        "render_options": dict(scalar_options),
    }
    mapping_application = {
        "proposal_id": "runtime-smoke-scalar-field-coverage",
        "mapped_outputs": [
            {
                "path": str(source.resolve()),
                "sha256": file_sha256(source),
            }
        ],
    }
    rendered_source_coverage = verify_rendered_mapping_source_coverage(
        {
            **rendered,
            "data_snapshot_source": str(source.resolve()),
        },
        mapping_application=mapping_application,
        request=coverage_request,
    )
    direct_label_contract = _direct_label_contract_probe(run_root)
    invalid_scalar_requests = {
        "explicit_zero_colorbar_width": {
            "colorbar_width_mm": 0,
        },
        "oversized_colorbar_background": {
            "colorbar_background_width_fraction": 100.0,
        },
        "opaque_colorbar_background": {
            "colorbar_background_transparency": 0,
        },
        "manual_colorbar_background": {
            "colorbar_manual_position": True,
        },
        "zero_axis_and_colorbar_font_size": {
            "font_size_pt": 0,
        },
        "opaque_reference_guide": {
            "reference_guides": [
                {
                    "kind": "band",
                    "axis": "x",
                    "start": -2.0,
                    "end": 2.0,
                    "transparency": 0,
                }
            ],
        },
        "transparent_colormap": {
            "colormap_colors": ["#00000000", "#FFFFFF00"],
        },
        "identical_colormap": {
            "colormap_colors": ["#123456", "#123456FF"],
        },
        "zero_reference_line_width": {
            "reference_guides": [
                scalar_options["reference_guides"][0],
                {
                    **scalar_options["reference_guides"][1],
                    "line_width_pt": 0,
                },
            ],
        },
    }
    invalid_scalar_request_results: dict[str, bool] = {}
    for request_id, overrides in invalid_scalar_requests.items():
        try:
            render_to_dir(
                source,
                template="heatmap",
                output_dir=source.parent / f"invalid_{request_id}",
                options={**scalar_options, **overrides},
                export_formats=("pdf",),
            )
        except (
            OSError,
            RuntimeError,
            subprocess.CalledProcessError,
            TypeError,
            ValueError,
        ):
            invalid_scalar_request_results[request_id] = True
        else:
            invalid_scalar_request_results[request_id] = False
    document_text = document.read_text(encoding="utf-8") if document.exists() else ""
    spec_text = spec.read_text(encoding="utf-8") if spec.exists() else ""
    log_x_band_contracts = _reference_guide_rect_contracts(
        {
            "axes": {
                "x": {"min": 1.0, "max": 1000.0, "scale": "log"},
                "y": {"min": 0.0, "max": 1.0, "scale": "linear"},
            },
            "reference_guides": [
                {
                    "kind": "band",
                    "axis": "x",
                    "start": 1.0,
                    "end": 100.0,
                    "color": "#CBD5E1",
                    "transparency": 86,
                }
            ],
        }
    )
    log_x_reference_guide_geometry_correct = (
        len(log_x_band_contracts) == 1
        and math.isclose(
            float(log_x_band_contracts[0]["xPos"][0]),
            10.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and math.isclose(
            float(log_x_band_contracts[0]["width"][0]),
            2.0 / 3.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    )
    document_only_visual_edit = document_text.replace(
        "Set('colorInvert', False)",
        "Set('colorInvert', True)",
        1,
    )
    document_only_visual_edit_materialized = (
        document_only_visual_edit != document_text
    )
    document_only_visual_edit_rejected = False
    if document_only_visual_edit_materialized:
        try:
            document.write_text(
                document_only_visual_edit,
                encoding="utf-8",
            )
            verify_rendered_mapping_source_coverage(
                {
                    **rendered,
                    "data_snapshot_source": str(source.resolve()),
                },
                mapping_application=mapping_application,
                request=coverage_request,
            )
        except (OSError, RuntimeError, ValueError):
            document_only_visual_edit_rejected = True
        finally:
            document.write_text(document_text, encoding="utf-8")

    coordinated_visual_forgery_materialized = False
    coordinated_visual_forgery_rejected = False
    if spec_text and document_only_visual_edit_materialized:
        forged_spec = json.loads(spec_text)
        scalar_field = forged_spec.get("scalar_field")
        if isinstance(scalar_field, dict):
            scalar_field["color_invert"] = True
            forged_spec_text = json.dumps(forged_spec, indent=2)
            coordinated_visual_forgery_materialized = (
                forged_spec_text != spec_text
            )
            try:
                spec.write_text(forged_spec_text, encoding="utf-8")
                document.write_text(
                    document_only_visual_edit,
                    encoding="utf-8",
                )
                verify_rendered_mapping_source_coverage(
                    {
                        **rendered,
                        "data_snapshot_source": str(source.resolve()),
                    },
                    mapping_application=mapping_application,
                    request=coverage_request,
                )
            except (OSError, RuntimeError, ValueError):
                coordinated_visual_forgery_rejected = True
            finally:
                spec.write_text(spec_text, encoding="utf-8")
                document.write_text(document_text, encoding="utf-8")
    exact_current_visual_attacks = {
        "image_transparency": (
            "To('/page1/graph1/field_image')\n"
            "Set('transparency', 100)\n"
            "To('/')"
        ),
        "colorbar_zero_width": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('width', '0cm')\n"
            "To('/')"
        ),
        "colorbar_label_hidden": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('Label/hide', True)\n"
            "To('/')"
        ),
        "colorbar_ticklabels_hidden": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('TickLabels/hide', True)\n"
            "To('/')"
        ),
        "colorbar_major_ticks_hidden": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MajorTicks/hide', True)\n"
            "To('/')"
        ),
        "colorbar_minor_ticks_hidden": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MinorTicks/hide', True)\n"
            "To('/')"
        ),
        "colorbar_line_hidden": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('Line/hide', True)\n"
            "To('/')"
        ),
        "colorbar_border_hidden": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('Border/hide', True)\n"
            "To('/')"
        ),
        "colorbar_label_size_zero": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('Label/size', '0pt')\n"
            "To('/')"
        ),
        "colorbar_ticklabels_size_zero": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('TickLabels/size', '0pt')\n"
            "To('/')"
        ),
        "colorbar_line_width_zero": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('Line/width', '0pt')\n"
            "To('/')"
        ),
        "colorbar_border_width_zero": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('Border/width', '0pt')\n"
            "To('/')"
        ),
        "colorbar_major_tick_width_zero": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MajorTicks/width', '0pt')\n"
            "To('/')"
        ),
        "colorbar_major_tick_length_zero": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MajorTicks/length', '0pt')\n"
            "To('/')"
        ),
        "colorbar_minor_tick_width_zero": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MinorTicks/width', '0pt')\n"
            "To('/')"
        ),
        "colorbar_minor_tick_length_zero": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MinorTicks/length', '0pt')\n"
            "To('/')"
        ),
        "colorbar_foreground_changed": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('Line/color', '#FF0000')\n"
            "To('/')"
        ),
        "colorbar_line_transparent": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('Line/transparency', 100)\n"
            "To('/')"
        ),
        "colorbar_border_transparent": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('Border/transparency', 100)\n"
            "To('/')"
        ),
        "colorbar_ticks_transparent": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MajorTicks/transparency', 100)\n"
            "To('/')"
        ),
        "colorbar_minor_ticks_transparent": (
            "To('/page1/graph1/field_colorbar')\n"
            "Set('MinorTicks/transparency', 100)\n"
            "To('/')"
        ),
        "contour_lines_hidden": (
            "To('/page1/graph1/field_contours')\n"
            "Set('Lines/hide', True)\n"
            "To('/')"
        ),
        "reference_guide_made_opaque": (
            "To('/page1/graph1/reference_guide_1')\n"
            "Set('Fill/transparency', 0)\n"
            "To('/')"
        ),
        "reference_line_width_changed": (
            "To('/page1/graph1/reference_guide_2')\n"
            "Set('Line/width', '4pt')\n"
            "To('/')"
        ),
        "reference_line_style_changed": (
            "To('/page1/graph1/reference_guide_2')\n"
            "Set('Line/style', 'solid')\n"
            "To('/')"
        ),
        "reference_line_hidden": (
            "To('/page1/graph1/reference_guide_2')\n"
            "Set('Line/hide', True)\n"
            "To('/')"
        ),
        "reference_line_geometry_changed": (
            "To('/page1/graph1/reference_guide_2')\n"
            "Set('xPos', [1.5])\n"
            "Set('xPos2', [1.5])\n"
            "To('/')"
        ),
        "colorbar_background_geometry_changed": (
            "To('/page1/graph1/field_colorbar_background')\n"
            "Set('width', [0.01])\n"
            "To('/')"
        ),
        "colorbar_background_fill_changed": (
            "To('/page1/graph1/field_colorbar_background')\n"
            "Set('Fill/color', '#000000')\n"
            "To('/')"
        ),
        "colorbar_background_hidden": (
            "To('/page1/graph1/field_colorbar_background')\n"
            "Set('Fill/hide', True)\n"
            "To('/')"
        ),
        "colorbar_background_transparency_changed": (
            "To('/page1/graph1/field_colorbar_background')\n"
            "Set('Fill/transparency', 100)\n"
            "To('/')"
        ),
        "axis_label_size_zero": (
            "To('/page1/graph1/x')\n"
            "Set('Label/size', '0pt')\n"
            "To('/')"
        ),
        "axis_ticklabels_size_zero": (
            "To('/page1/graph1/x')\n"
            "Set('TickLabels/size', '0pt')\n"
            "To('/')"
        ),
        "axis_line_width_zero": (
            "To('/page1/graph1/x')\n"
            "Set('Line/width', '0pt')\n"
            "To('/')"
        ),
        "axis_major_tick_width_zero": (
            "To('/page1/graph1/x')\n"
            "Set('MajorTicks/width', '0pt')\n"
            "To('/')"
        ),
        "axis_major_tick_length_zero": (
            "To('/page1/graph1/x')\n"
            "Set('MajorTicks/length', '0pt')\n"
            "To('/')"
        ),
        "axis_minor_tick_width_zero": (
            "To('/page1/graph1/x')\n"
            "Set('MinorTicks/width', '0pt')\n"
            "To('/')"
        ),
        "axis_minor_tick_length_zero": (
            "To('/page1/graph1/x')\n"
            "Set('MinorTicks/length', '0pt')\n"
            "To('/')"
        ),
    }
    exact_current_attack_documents = {
        attack_id: document_text + "\n" + commands + "\n"
        for attack_id, commands in exact_current_visual_attacks.items()
    }
    unmanaged_overlay = (
        "Add('rect', name='unmanaged_overlay', autoadd=False)\n"
        "To('unmanaged_overlay')\n"
        "Set('positioning', 'relative')\n"
        "Set('xPos', [0.5])\n"
        "Set('yPos', [0.5])\n"
        "Set('width', [1.0])\n"
        "Set('height', [1.0])\n"
        "Set('clip', True)\n"
        "Set('Fill/color', '#FFFFFF')\n"
        "Set('Fill/hide', False)\n"
        "Set('Fill/transparency', 0)\n"
        "Set('Border/hide', True)\n"
        "To('..')\n"
    )
    image_command = "Add('image', name='field_image', autoadd=False)"
    unmanaged_overlay_document = document_text.replace(
        image_command,
        unmanaged_overlay + image_command,
        1,
    )
    exact_current_attack_documents["unmanaged_opaque_overlay"] = (
        unmanaged_overlay_document
    )
    unmanaged_line = (
        "Add('line', name='unmanaged_line_overlay', autoadd=False)\n"
        "To('unmanaged_line_overlay')\n"
        "Set('positioning', 'relative')\n"
        "Set('mode', 'point-to-point')\n"
        "Set('xPos', [0.0])\n"
        "Set('yPos', [0.0])\n"
        "Set('xPos2', [1.0])\n"
        "Set('yPos2', [1.0])\n"
        "Set('clip', True)\n"
        "Set('Line/color', '#FFFFFF')\n"
        "Set('Line/width', '20pt')\n"
        "Set('Line/transparency', 0)\n"
        "Set('Line/hide', False)\n"
        "Set('arrowleft', 'none')\n"
        "Set('arrowright', 'none')\n"
        "Set('Fill/hide', True)\n"
        "To('..')\n"
    )
    exact_current_attack_documents["unmanaged_line_overlay"] = (
        document_text.replace(
            image_command,
            unmanaged_line + image_command,
            1,
        )
    )
    background_command = "Add('rect', name='field_colorbar_background'"
    background_start = document_text.find(background_command)
    image_start = document_text.find(image_command)
    if 0 <= background_start < image_start:
        exact_current_attack_documents["colorbar_background_deleted"] = (
            document_text[:background_start] + document_text[image_start:]
        )
    attack_targets = {
        "image_transparency": (
            "/page1/graph1/field_image",
            "transparency",
        ),
        "colorbar_zero_width": (
            "/page1/graph1/field_colorbar",
            "width",
        ),
        "colorbar_label_hidden": (
            "/page1/graph1/field_colorbar",
            "Label/hide",
        ),
        "colorbar_ticklabels_hidden": (
            "/page1/graph1/field_colorbar",
            "TickLabels/hide",
        ),
        "colorbar_major_ticks_hidden": (
            "/page1/graph1/field_colorbar",
            "MajorTicks/hide",
        ),
        "colorbar_minor_ticks_hidden": (
            "/page1/graph1/field_colorbar",
            "MinorTicks/hide",
        ),
        "colorbar_line_hidden": (
            "/page1/graph1/field_colorbar",
            "Line/hide",
        ),
        "colorbar_border_hidden": (
            "/page1/graph1/field_colorbar",
            "Border/hide",
        ),
        "colorbar_label_size_zero": (
            "/page1/graph1/field_colorbar",
            "Label/size",
        ),
        "colorbar_ticklabels_size_zero": (
            "/page1/graph1/field_colorbar",
            "TickLabels/size",
        ),
        "colorbar_line_width_zero": (
            "/page1/graph1/field_colorbar",
            "Line/width",
        ),
        "colorbar_border_width_zero": (
            "/page1/graph1/field_colorbar",
            "Border/width",
        ),
        "colorbar_major_tick_width_zero": (
            "/page1/graph1/field_colorbar",
            "MajorTicks/width",
        ),
        "colorbar_major_tick_length_zero": (
            "/page1/graph1/field_colorbar",
            "MajorTicks/length",
        ),
        "colorbar_minor_tick_width_zero": (
            "/page1/graph1/field_colorbar",
            "MinorTicks/width",
        ),
        "colorbar_minor_tick_length_zero": (
            "/page1/graph1/field_colorbar",
            "MinorTicks/length",
        ),
        "colorbar_foreground_changed": (
            "/page1/graph1/field_colorbar",
            "Line/color",
        ),
        "colorbar_line_transparent": (
            "/page1/graph1/field_colorbar",
            "Line/transparency",
        ),
        "colorbar_border_transparent": (
            "/page1/graph1/field_colorbar",
            "Border/transparency",
        ),
        "colorbar_ticks_transparent": (
            "/page1/graph1/field_colorbar",
            "MajorTicks/transparency",
        ),
        "colorbar_minor_ticks_transparent": (
            "/page1/graph1/field_colorbar",
            "MinorTicks/transparency",
        ),
        "contour_lines_hidden": (
            "/page1/graph1/field_contours",
            "Lines/hide",
        ),
        "reference_guide_made_opaque": (
            "/page1/graph1/reference_guide_1",
            "Fill/transparency",
        ),
        "reference_line_width_changed": (
            "/page1/graph1/reference_guide_2",
            "Line/width",
        ),
        "reference_line_style_changed": (
            "/page1/graph1/reference_guide_2",
            "Line/style",
        ),
        "reference_line_hidden": (
            "/page1/graph1/reference_guide_2",
            "Line/hide",
        ),
        "reference_line_geometry_changed": (
            "/page1/graph1/reference_guide_2",
            "xPos",
        ),
        "colorbar_background_geometry_changed": (
            "/page1/graph1/field_colorbar_background",
            "width",
        ),
        "colorbar_background_fill_changed": (
            "/page1/graph1/field_colorbar_background",
            "Fill/color",
        ),
        "colorbar_background_hidden": (
            "/page1/graph1/field_colorbar_background",
            "Fill/hide",
        ),
        "colorbar_background_transparency_changed": (
            "/page1/graph1/field_colorbar_background",
            "Fill/transparency",
        ),
        "axis_label_size_zero": (
            "/page1/graph1/x",
            "Label/size",
        ),
        "axis_ticklabels_size_zero": (
            "/page1/graph1/x",
            "TickLabels/size",
        ),
        "axis_line_width_zero": (
            "/page1/graph1/x",
            "Line/width",
        ),
        "axis_major_tick_width_zero": (
            "/page1/graph1/x",
            "MajorTicks/width",
        ),
        "axis_major_tick_length_zero": (
            "/page1/graph1/x",
            "MajorTicks/length",
        ),
        "axis_minor_tick_width_zero": (
            "/page1/graph1/x",
            "MinorTicks/width",
        ),
        "axis_minor_tick_length_zero": (
            "/page1/graph1/x",
            "MinorTicks/length",
        ),
    }
    baseline_document_state = _inspect_veusz_document_state(document)
    baseline_widgets = baseline_document_state["widgets"]
    exact_current_visual_attack_materialization: dict[str, bool] = {}
    exact_current_visual_attack_results: dict[str, bool] = {}
    for attack_id, attacked_document in exact_current_attack_documents.items():
        materialized = False
        try:
            document.write_text(
                attacked_document,
                encoding="utf-8",
            )
            attacked_state = _inspect_veusz_document_state(document)
            attacked_widgets = attacked_state["widgets"]
            if attack_id == "colorbar_background_deleted":
                materialized = (
                    "/page1/graph1/field_colorbar_background"
                    in baseline_widgets
                    and "/page1/graph1/field_colorbar_background"
                    not in attacked_widgets
                )
            elif attack_id in {
                "unmanaged_line_overlay",
                "unmanaged_opaque_overlay",
            }:
                extra_path = (
                    "/page1/graph1/unmanaged_line_overlay"
                    if attack_id == "unmanaged_line_overlay"
                    else "/page1/graph1/unmanaged_overlay"
                )
                materialized = (
                    extra_path not in baseline_widgets
                    and extra_path in attacked_widgets
                )
            else:
                target_path, setting_path = attack_targets[attack_id]
                baseline_target = baseline_widgets.get(target_path)
                attacked_target = attacked_widgets.get(target_path)
                materialized = (
                    isinstance(baseline_target, dict)
                    and isinstance(attacked_target, dict)
                    and baseline_target.get("settings", {}).get(setting_path)
                    != attacked_target.get("settings", {}).get(setting_path)
                )
            exact_current_visual_attack_materialization[attack_id] = (
                materialized
            )
            verify_rendered_mapping_source_coverage(
                {
                    **rendered,
                    "data_snapshot_source": str(source.resolve()),
                },
                mapping_application=mapping_application,
                request=coverage_request,
            )
        except (OSError, RuntimeError, ValueError):
            exact_current_visual_attack_results[attack_id] = True
            exact_current_visual_attack_materialization.setdefault(
                attack_id,
                False,
            )
        else:
            exact_current_visual_attack_results[attack_id] = False
        finally:
            document.write_text(document_text, encoding="utf-8")
    colorbar_index = document_text.find("Add('colorbar', name='field_colorbar'")
    colorbar_background_index = document_text.find(
        "Add('rect', name='field_colorbar_background'"
    )
    contour_index = document_text.find("Add('contour', name='field_contours'")
    image_index = document_text.find("Add('image', name='field_image'")
    qa_reports = (
        rendered.get("qa_reports")
        if isinstance(rendered.get("qa_reports"), list)
        else []
    )
    passed = (
        rendered.get("render_engine") == "veusz"
        and outputs
        and all(path.exists() and path.stat().st_size > 0 for path in outputs)
        and document.exists()
        and spec.exists()
        and rendered_source_coverage.get("status") == "passed"
        and rendered_source_coverage.get("rendered_unit_count") == 1
        and rendered_source_coverage.get("document_count") == 1
        and direct_label_contract.get("passed") is True
        and document_only_visual_edit_materialized
        and document_only_visual_edit_rejected
        and coordinated_visual_forgery_materialized
        and coordinated_visual_forgery_rejected
        and log_x_reference_guide_geometry_correct
        and invalid_scalar_request_results
        and all(invalid_scalar_request_results.values())
        and set(exact_current_attack_documents)
        == EXPECTED_SCALAR_VISUAL_ATTACK_IDS
        and set(exact_current_visual_attack_materialization)
        == EXPECTED_SCALAR_VISUAL_ATTACK_IDS
        and all(exact_current_visual_attack_materialization.values())
        and exact_current_visual_attack_results
        and set(exact_current_visual_attack_results)
        == EXPECTED_SCALAR_VISUAL_ATTACK_IDS
        and all(exact_current_visual_attack_results.values())
        and 0 <= colorbar_index < image_index
        and 0 <= colorbar_index < colorbar_background_index < image_index
        and 0 <= contour_index < image_index
        and "Set('widgetName', 'field_image')" in document_text
        and "Add('rect', name='page_export_background'" in document_text
        and all(
            not report.get("issues")
            for report in qa_reports
            if isinstance(report, dict)
        )
    )
    return {
        "passed": bool(passed),
        "source": str(source),
        "grid_shape": [2, 3],
        "field_orientation": {
            "x": "thickness_mm",
            "y": "in_plane_mm",
            "z": "temperature_C",
        },
        "outputs": [str(path) for path in outputs],
        "document": str(document),
        "spec": str(spec),
        "rendered_source_coverage": rendered_source_coverage,
        "direct_label_contract": direct_label_contract,
        "scalar_visual_attack_regression": {
            "document_only_edit_materialized": (
                document_only_visual_edit_materialized
            ),
            "document_only_edit_rejected": (
                document_only_visual_edit_rejected
            ),
            "coordinated_spec_vsz_forgery_materialized": (
                coordinated_visual_forgery_materialized
            ),
            "coordinated_spec_vsz_forgery_rejected": (
                coordinated_visual_forgery_rejected
            ),
            "invalid_request_results": invalid_scalar_request_results,
            "log_x_reference_guide_geometry_correct": (
                log_x_reference_guide_geometry_correct
            ),
            "expected_exact_current_attack_ids": sorted(
                EXPECTED_SCALAR_VISUAL_ATTACK_IDS
            ),
            "expected_exact_current_attack_count": len(
                EXPECTED_SCALAR_VISUAL_ATTACK_IDS
            ),
            "exact_current_attack_id_set_matches": (
                set(exact_current_attack_documents)
                == EXPECTED_SCALAR_VISUAL_ATTACK_IDS
            ),
            "exact_current_attack_materialization": (
                exact_current_visual_attack_materialization
            ),
            "exact_current_visual_attacks": (
                exact_current_visual_attack_results
            ),
        },
        "overlay_order": {
            "colorbar_before_image_in_object_tree": 0 <= colorbar_index < image_index,
            "colorbar_background_between_colorbar_and_image": (
                0
                <= colorbar_index
                < colorbar_background_index
                < image_index
            ),
            "contours_before_image_in_object_tree": 0 <= contour_index < image_index,
        },
        "opaque_page_background": "Add('rect', name='page_export_background'"
        in document_text,
        "real_data_evidence": False,
        "evidence_tier": "generated_synthetic_contract_fixture",
    }


def _run_hash_failure_probe(
    output_dir: Path, manifest: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    from sciplot_core.delivery import build_delivery_package

    mismatched_manifest = copy.deepcopy(manifest)
    mismatched_manifest["exported_document_hash"] = "0" * 64
    rejected = build_delivery_package(output_dir, manifest=mismatched_manifest)
    hash_gate = _delivery_artifact(rejected, "editable_vsz_hash_match")
    rejected_as_expected = (
        rejected.get("complete") is False and hash_gate.get("exists") is False
    )

    restored = build_delivery_package(output_dir, manifest=manifest)
    restored_successfully = restored.get("complete") is True
    return rejected_as_expected and restored_successfully, {
        "mismatched_delivery_complete": rejected.get("complete"),
        "mismatched_hash_gate": hash_gate,
        "restored_delivery_complete": restored.get("complete"),
    }


def run_runtime_smoke(*, output_root: Path) -> dict[str, Any]:
    """Run a fixture-free end-to-end Studio lifecycle and delivery failure probe."""

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="runtime_smoke_", dir=resolved_output))
    summary_path = run_root / "runtime_smoke.json"
    checks: list[dict[str, Any]] = []
    fixture: dict[str, Any] | None = None
    manifest_path: Path | None = None
    project_dir: Path | None = None
    error: dict[str, str] | None = None

    try:
        import_probe = _package_import_probe()
        checks.append(
            _check(
                "package_import_isolated",
                "Importing sciplot_core does not activate the migrated compatibility path",
                import_probe.get("passed") is True,
                detail=import_probe,
            )
        )
        wrapper_probe = _source_checkout_wrapper_probe()
        checks.append(
            _check(
                "source_checkout_wrapper_bootstraps",
                "The source wrapper or installed CLI starts without relying on an editable import leak",
                wrapper_probe.get("passed") is True,
                detail=wrapper_probe,
            )
        )
        from sciplot_core.canvas_probe import run_canvas_contract_probe

        canvas_contract_probe = run_canvas_contract_probe(
            output_root=run_root / "canvas_contract"
        )
        checks.append(
            _check(
                "canvas_contract_v7",
                "CanvasSession, hash-bound provider requests and responses, "
                "active Assistant transactions, journal outbox, contextual "
                "inspector, typed edits, native review promotion, point "
                "selection, and mapping proposals roundtrip without Qt",
                canvas_contract_probe.get("status") == "passed",
                detail=canvas_contract_probe,
            )
        )
        from sciplot_core.data_mapping_probe import run_data_mapping_probe

        data_mapping_probe = run_data_mapping_probe(
            output_root=run_root / "data_mapping"
        )
        checks.append(
            _check(
                "deterministic_data_mapping_lifecycle",
                "DataMappingProposal v2 previews without writes, requires an "
                "external confirmation receipt, executes atomically, preserves "
                "raw sources, records transform lineage, and rejects stale or "
                "tampered state",
                data_mapping_probe.get("status") == "passed",
                detail=data_mapping_probe,
            )
        )
        from sciplot_core.readiness_probe import run_readiness_probe

        readiness_probe = run_readiness_probe(output_root=run_root / "readiness")
        readiness_registry = readiness_probe.get("registry_status") or {}
        checks.append(
            _check(
                "validated_ready_envelopes",
                "All current accepted rule contracts remain bound to authorized "
                "real-data evidence, reject contract drift and provider-authored "
                "ready flags, and gate one-step readiness",
                readiness_probe.get("status") == "passed",
                detail={
                    "status": readiness_probe.get("status"),
                    "passed_count": readiness_probe.get("passed_count"),
                    "check_count": readiness_probe.get("check_count"),
                    "ready_without_ai_rule_count": readiness_registry.get(
                        "ready_without_ai_rule_count"
                    ),
                    "evidence_strength_counts": readiness_registry.get(
                        "evidence_strength_counts"
                    ),
                    "artifacts": readiness_probe.get("artifacts"),
                },
            )
        )

        from sciplot_core.session_evidence_probe import (
            run_session_evidence_probe,
        )

        session_evidence_probe = run_session_evidence_probe(
            output_root=run_root / "session_evidence"
        )
        checks.append(
            _check(
                "session_evidence_contract_v1",
                "Preregistered natural-task evidence is hash-chained, "
                "reopen-witnessed, final-authority bound, duplicate-safe, "
                "tamper-evident, and unable to promote synthetic probes into "
                "M3/M6 counts",
                session_evidence_probe.get("status") == "passed",
                detail={
                    "status": session_evidence_probe.get("status"),
                    "summary": session_evidence_probe.get("summary"),
                    "artifacts": session_evidence_probe.get("artifacts"),
                    "limitations": session_evidence_probe.get("limitations"),
                },
            )
        )

        from sciplot_core.session_evidence_runtime import (
            _linked_qt_binaries,
            runtime_identity,
        )

        frozen_runtime = runtime_identity(
            veusz_root=VEUSZ_ROOT,
            veusz_upstream_commit=VEUSZ_UPSTREAM_COMMIT,
        )
        linked_qt = frozen_runtime.get("linked_qt_binaries")
        linked_qt = linked_qt if isinstance(linked_qt, dict) else {}
        linked_qt_binaries = linked_qt.get("binaries")
        linked_qt_binaries = (
            linked_qt_binaries if isinstance(linked_qt_binaries, list) else []
        )
        helper_count = len(list((VEUSZ_ROOT / "veusz" / "helpers").glob("*.so")))
        no_helper_veusz_root = run_root / "runtime_identity_no_helpers"
        no_helper_package = no_helper_veusz_root / "veusz"
        no_helper_package.mkdir(parents=True, exist_ok=True)
        (no_helper_package / "__init__.py").write_text(
            "# Runtime identity no-helper contract fixture.\n",
            encoding="utf-8",
        )
        no_helper_runtime = runtime_identity(
            veusz_root=no_helper_veusz_root,
            veusz_upstream_commit=VEUSZ_UPSTREAM_COMMIT,
        )
        no_helper_linked = (no_helper_runtime.get("linked_qt_binaries") or {}).get(
            "binaries"
        )
        no_helper_linked = (
            no_helper_linked if isinstance(no_helper_linked, list) else []
        )
        unresolved_qt_rejected = True
        if sys.platform == "darwin":
            try:
                _linked_qt_binaries(
                    no_helper_veusz_root,
                    qt_binding_root=run_root / "missing_pyqt_runtime",
                )
            except ValueError:
                pass
            else:
                unresolved_qt_rejected = False
        checks.append(
            _check(
                "frozen_runtime_identity",
                "The evidence candidate fingerprints active Veusz, every "
                "PyQt/Qt binary, linked Qt helper runtimes, Python, platform, "
                "and installed dependency versions",
                bool(frozen_runtime.get("identity_sha256"))
                and int((frozen_runtime.get("veusz") or {}).get("file_count") or 0) > 0
                and int((frozen_runtime.get("qt_binding") or {}).get("file_count") or 0)
                > 0
                and (
                    sys.platform != "darwin"
                    or (
                        bool(linked_qt_binaries)
                        and bool(no_helper_linked)
                        and unresolved_qt_rejected
                    )
                ),
                detail={
                    "identity_sha256": frozen_runtime.get("identity_sha256"),
                    "veusz_file_count": (frozen_runtime.get("veusz") or {}).get(
                        "file_count"
                    ),
                    "qt_binary_count": (frozen_runtime.get("qt_binding") or {}).get(
                        "file_count"
                    ),
                    "veusz_helper_count": helper_count,
                    "linked_qt_binary_count": len(linked_qt_binaries),
                    "no_helper_linked_qt_binary_count": len(no_helper_linked),
                    "unresolved_qt_rejected": unresolved_qt_rejected,
                    "dependency_count": (frozen_runtime.get("dependencies") or {}).get(
                        "count"
                    ),
                },
            )
        )

        from sciplot_core.doctor import doctor_payload
        from sciplot_core.studio import (
            export_studio_document,
            prepare_studio_document,
            publish_studio_export_run,
        )

        doctor = doctor_payload()
        checks.append(
            _check(
                "runtime_ready",
                "Required runtime dependencies and rule registry are ready",
                doctor.get("status") == "ready",
                detail={
                    "status": doctor.get("status"),
                    "ready_rules": (doctor.get("rule_summary") or {}).get("ready"),
                },
            )
        )
        from sciplot_core.policy import (
            DEFAULT_LOG_MINOR_MULTIPLIERS,
            DEFAULT_LOG_MINOR_TICK_COUNT,
            RHEOLOGY_FREQUENCY_RENDER_OPTIONS,
            UNIFIED_AXIS_LINEWIDTH_PT,
            UNIFIED_FONT_FAMILY,
            UNIFIED_FONT_SIZE_PT,
            UNIFIED_LEGEND_FONT_SIZE_PT,
            UNIFIED_LINE_WIDTH_PT,
            UNIFIED_MARKER_SIZE_PT,
            UNIFIED_MINOR_TICK_WIDTH_PT,
            UNIFIED_PANEL_LABEL_SIZE_PT,
            UNIFIED_TICK_WIDTH_PT,
        )

        log_tick_policy = {
            "subdivisions_per_decade": DEFAULT_LOG_MINOR_TICK_COUNT,
            "visible_minor_multipliers": list(DEFAULT_LOG_MINOR_MULTIPLIERS),
            "rheology_frequency_minor_tick_count": (
                RHEOLOGY_FREQUENCY_RENDER_OPTIONS.get("minor_tick_count")
            ),
        }
        checks.append(
            _check(
                "sparse_log_minor_tick_policy",
                "Log modulus axes retain four visible minor ticks per decade",
                DEFAULT_LOG_MINOR_TICK_COUNT == 5
                and DEFAULT_LOG_MINOR_MULTIPLIERS == (2.0, 4.0, 6.0, 8.0)
                and RHEOLOGY_FREQUENCY_RENDER_OPTIONS.get("minor_tick_count")
                == DEFAULT_LOG_MINOR_TICK_COUNT,
                detail=log_tick_policy,
            )
        )
        unified_style = {
            "font_family": UNIFIED_FONT_FAMILY,
            "font_size_pt": UNIFIED_FONT_SIZE_PT,
            "legend_font_size_pt": UNIFIED_LEGEND_FONT_SIZE_PT,
            "panel_label_size_pt": UNIFIED_PANEL_LABEL_SIZE_PT,
            "line_width_pt": UNIFIED_LINE_WIDTH_PT,
            "axis_linewidth_pt": UNIFIED_AXIS_LINEWIDTH_PT,
            "tick_width_pt": UNIFIED_TICK_WIDTH_PT,
            "minor_tick_width_pt": UNIFIED_MINOR_TICK_WIDTH_PT,
            "marker_size_pt": UNIFIED_MARKER_SIZE_PT,
        }
        checks.append(
            _check(
                "unified_figure_style_contract",
                "All templates use the same SciPlot typography, strokes, and marker size",
                unified_style
                == {
                    "font_family": "Arial",
                    "font_size_pt": 7.0,
                    "legend_font_size_pt": 6.0,
                    "panel_label_size_pt": 7.0,
                    "line_width_pt": 1.2,
                    "axis_linewidth_pt": 0.8,
                    "tick_width_pt": 0.8,
                    "minor_tick_width_pt": 0.8,
                    "marker_size_pt": 2.0,
                },
                detail=unified_style,
            )
        )
        qt_mainwindow_probe = _qt_mainwindow_probe()
        checks.append(
            _check(
                "qt_mainwindow_constructs",
                "The complete Veusz editor constructs without optional examples or macOS settings noise",
                qt_mainwindow_probe.get("passed") is True,
                detail=qt_mainwindow_probe,
            )
        )
        normal_mode = (
            doctor.get("normal_mode")
            if isinstance(doctor.get("normal_mode"), dict)
            else {}
        )
        checks.append(
            _check(
                "independent_mode",
                "Normal plotting remains independent and Codex-optional",
                normal_mode.get("frontend_default") == "independent"
                and normal_mode.get("codex_required") is False
                and normal_mode.get("user_switch_required") is False,
                detail=normal_mode,
            )
        )

        parser_probe = _semantic_parser_probe(run_root)
        checks.append(
            _check(
                "promoted_semantic_parsers",
                "Generated SAXS, Agilent GPC, impact, and explicit-intent swelling contracts parse deterministically",
                parser_probe.get("passed") is True,
                detail=parser_probe,
            )
        )
        from sciplot_core.analysis_contract_probe import (
            run_analysis_contract_probe,
        )
        from sciplot_core.semantic_contract_probe import (
            run_semantic_contract_probe,
        )

        analysis_contract_probe = run_analysis_contract_probe(
            run_root / "analysis_contract_probe"
        )
        checks.append(
            _check(
                "scientific_analysis_contracts",
                "Scientific metrics use the confirmed metric columns, "
                "per-series extrema, and conservative interpretation rules",
                analysis_contract_probe.get("status") == "passed",
                detail=analysis_contract_probe,
            )
        )
        semantic_contract_probe = run_semantic_contract_probe(
            run_root / "semantic_contract_probe"
        )
        checks.append(
            _check(
                "scientific_semantic_contracts",
                "Scientific preprocessing preserves units, interval identity, "
                "log domains, and complete in-scope source coverage",
                semantic_contract_probe.get("status") == "passed",
                detail=semantic_contract_probe,
            )
        )

        scalar_probe = _scalar_field_render_probe(run_root)
        checks.append(
            _check(
                "scalar_field_render",
                "Synthetic XYZ data render through Veusz with visible contours and colorbar",
                scalar_probe.get("passed") is True,
                detail=scalar_probe,
            )
        )
        scalar_document = Path(str(scalar_probe.get("document") or ""))
        qt_scalar_document_probe = _qt_mainwindow_probe(scalar_document)
        checks.append(
            _check(
                "qt_scalar_vsz_loads",
                "The Studio GUI runtime loads a saved 2D scalar-field VSZ with its dataset and page",
                qt_scalar_document_probe.get("passed") is True,
                detail=qt_scalar_document_probe,
            )
        )

        from sciplot_core.qa import _normalized_label

        qa_label_probe = {
            "veusz_label": r"LS\_5CRW\_20W\_t1",
            "pdf_label": "LS_5CRW_20W_t1",
        }
        qa_label_probe["normalized_veusz_label"] = _normalized_label(
            qa_label_probe["veusz_label"]
        )
        qa_label_probe["normalized_pdf_label"] = _normalized_label(
            qa_label_probe["pdf_label"]
        )
        checks.append(
            _check(
                "veusz_pdf_label_equivalence",
                "Escaped Veusz labels match their rendered PDF text",
                qa_label_probe["normalized_veusz_label"]
                == qa_label_probe["normalized_pdf_label"],
                detail=qa_label_probe,
            )
        )

        from sciplot_core.workbench_contract import apply_request_patch

        option_provenance_probe = apply_request_patch(
            {
                "exports": ["pdf", "tiff_300"],
                "render_options": {"size": "60x55", "legend_position": "auto"},
                "explicit_render_option_keys": [],
            },
            render_options={"size": "120x55"},
        )
        checks.append(
            _check(
                "explicit_render_option_provenance",
                "A user-selected render option becomes authoritative without promoting semantic defaults",
                option_provenance_probe.get("explicit_render_option_keys") == ["size"]
                and (option_provenance_probe.get("render_options") or {}).get("size")
                == "120x55"
                and (option_provenance_probe.get("render_options") or {}).get(
                    "legend_position"
                )
                == "auto",
                detail=option_provenance_probe,
            )
        )

        from sciplot_core.materials_rules import get_rule
        from sciplot_core.studio import _apply_studio_request_overrides

        override_project = run_root / "explicit_rule_override"
        override_project.mkdir(parents=True, exist_ok=True)
        override_request_path = override_project / "plot_request.json"
        previous_rule = get_rule("swelling_curve")
        previous_options = {
            **previous_rule.render_options,
            "x_label_override": previous_rule.x_axis.display_label,
            "y_label_override": previous_rule.y_axis.display_label,
            "size": "180x55",
        }
        override_request_path.write_text(
            json.dumps(
                {
                    "recipe": "auto",
                    "rule_id": previous_rule.rule_id,
                    "template": previous_rule.template,
                    "render_options": previous_options,
                    "explicit_render_option_keys": ["size"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        _apply_studio_request_overrides(
            override_project,
            request_path=override_request_path,
            rule_id="saxs_profile",
        )
        overridden_request = json.loads(
            override_request_path.read_text(encoding="utf-8")
        )
        overridden_options = overridden_request.get("render_options") or {}
        checks.append(
            _check(
                "existing_project_explicit_rule_override",
                "An explicit rule replaces prior semantic defaults while preserving user render choices",
                overridden_request.get("rule_id") == "saxs_profile"
                and overridden_request.get("template") == "curve"
                and overridden_request.get("explicit_render_option_keys") == ["size"]
                and overridden_options.get("size") == "180x55"
                and overridden_options.get("x_label_override") == r"q (nm$^{-1}$)"
                and overridden_options.get("y_label_override") == "Intensity (a.u.)"
                and overridden_options.get("xscale") == "log"
                and overridden_options.get("yscale") == "log"
                and "marker_sequence" not in overridden_options,
                detail=overridden_request,
            )
        )

        fixture_path = run_root / "fixture" / "ftir_runtime_smoke.csv"
        fixture = _write_synthetic_ftir(fixture_path)
        prepared = prepare_studio_document(
            fixture_path,
            output_root=run_root / "projects",
            project_name="Synthetic FTIR runtime smoke",
        )
        project_dir = Path(str(prepared["project_dir"]))
        request_path = Path(str(prepared["request"]))
        document_path = Path(str(prepared["document"]))
        mapped_studio_probe = _data_mapping_studio_lifecycle_probe(
            run_root=run_root,
            source_path=fixture_path,
            base_request_path=request_path,
        )
        checks.append(
            _check(
                "mapped_project_studio_lifecycle",
                "A confirmed mapping candidate uses the standard project "
                "entrypoint, preserves raw input, retains every mapped sample, "
                "records causal lineage, and completes VSZ, QA, and delivery",
                mapped_studio_probe.get("passed") is True,
                detail=mapped_studio_probe,
            )
        )
        from sciplot_core.studio_project_probe import (
            run_studio_project_probe,
        )

        studio_project_probe = run_studio_project_probe(
            project_dir,
            output_root=run_root / "studio_project",
            mapped_document=Path(str(mapped_studio_probe["document"])),
        )
        checks.append(
            _check(
                "veusz_mainwindow_project_integration",
                "One native Veusz MainWindow keeps Project and AI docks opt-in, "
                "tracks live VSZ/source/mapping/QA truth, rejects stale QA, and "
                "exports both project and standalone exact-current receipts",
                studio_project_probe.get("status") == "passed",
                detail={
                    "status": studio_project_probe.get("status"),
                    "summary": studio_project_probe.get("summary"),
                    "artifacts": studio_project_probe.get("artifacts"),
                },
            )
        )
        from sciplot_core.canvas_probe import run_canvas_characterization

        canvas_characterization = run_canvas_characterization(
            document_path,
            output_root=run_root / "canvas_characterization",
        )
        checks.append(
            _check(
                "embedded_canvas_characterization",
                "Embedded PlotWindow supports live typed redraw, interaction, history, recovery, conflict detection, save/reopen, and exact export",
                canvas_characterization.get("status") == "passed",
                detail=canvas_characterization,
            )
        )
        from sciplot_core.canvas_app_probe import run_canvas_app_probe

        canvas_app_probe = run_canvas_app_probe(
            project_dir,
            output_root=run_root / "canvas_app",
            operation_count=50,
        )
        canvas_app_evidence = canvas_app_probe.get("evidence")
        canvas_app_evidence = (
            canvas_app_evidence if isinstance(canvas_app_evidence, dict) else {}
        )
        checks.append(
            _check(
                "native_canvas_app_lifecycle",
                "The SciPlot-owned Canvas completes contextual edits, point "
                "selection, structural QA, 50 live redraws, save/reopen, exact "
                "export, project delivery, and explicit recovery",
                canvas_app_probe.get("status") == "passed",
                detail={
                    "status": canvas_app_probe.get("status"),
                    "summary": canvas_app_probe.get("summary"),
                    "operation_count": canvas_app_evidence.get("operation_count"),
                    "revision": canvas_app_evidence.get("revision_after_operations"),
                    "render_changes": canvas_app_evidence.get("render_changes"),
                    "reopened_state": canvas_app_evidence.get("reopened_state"),
                    "recovered_state": canvas_app_evidence.get("recovered_state"),
                    "export": canvas_app_evidence.get("export"),
                    "source_immutable": canvas_app_evidence.get("source_immutable"),
                    "artifacts": canvas_app_probe.get("artifacts"),
                },
            )
        )
        session_runtime_probes = session_evidence_probe.get("runtime_probes")
        session_runtime_probes = (
            session_runtime_probes if isinstance(session_runtime_probes, dict) else {}
        )
        canvas_review_probe = session_runtime_probes.get("canvas_review")
        if not isinstance(canvas_review_probe, dict):
            from sciplot_core.canvas_review_probe import run_canvas_review_probe

            canvas_review_probe = run_canvas_review_probe(
                project_dir,
                output_root=run_root / "canvas_review",
            )
        checks.append(
            _check(
                "native_canvas_review_lifecycle",
                "The SciPlot-owned Canvas persists five review tools outside "
                "publication exports, promotes four typed native annotations, "
                "and preserves undo, reopen, QA, and audit semantics",
                canvas_review_probe.get("status") == "passed",
                detail={
                    "status": canvas_review_probe.get("status"),
                    "summary": canvas_review_probe.get("summary"),
                    "evidence": canvas_review_probe.get("evidence"),
                    "artifacts": canvas_review_probe.get("artifacts"),
                },
            )
        )
        composition_probe = session_runtime_probes.get("composition")
        if not isinstance(composition_probe, dict):
            from sciplot_core.composition_probe import run_composition_probe

            composition_probe = run_composition_probe(
                [document_path],
                output_root=run_root / "composition",
            )
        checks.append(
            _check(
                "native_composition_lifecycle",
                "The 183 mm Composition Board compiles all five native layouts, "
                "routes a real drag through typed reversible operations, protects "
                "manual edits, keeps variants and source VSZ files independent, "
                "and passes exact-current PDF/TIFF delivery QA",
                composition_probe.get("status") == "passed",
                detail={
                    "status": composition_probe.get("status"),
                    "check_count": composition_probe.get("check_count"),
                    "passed_count": composition_probe.get("passed_count"),
                    "artifacts": composition_probe.get("artifacts"),
                },
            )
        )
        from sciplot_core.canvas_assistant_probe import (
            run_canvas_assistant_probe,
        )

        canvas_assistant_probe = run_canvas_assistant_probe(
            project_dir,
            output_root=run_root / "canvas_assistant",
        )
        canvas_assistant_evidence = canvas_assistant_probe.get("evidence")
        canvas_assistant_evidence = (
            canvas_assistant_evidence
            if isinstance(canvas_assistant_evidence, dict)
            else {}
        )
        checks.append(
            _check(
                "native_canvas_assistant_transaction",
                "The SciPlot-owned Canvas accepts a bounded provider request "
                "off the GUI thread, shows progress, previews hash-bound typed "
                "diffs without mutation, discards late cancelled results, "
                "applies live, undoes, commits, rolls back exactly, and "
                "recovers interrupted work; DataMappingProposal additionally "
                "requires a zero-write preview and an explicit receipt before "
                "building a separate mapped Canvas",
                canvas_assistant_probe.get("status") == "passed",
                detail={
                    "status": canvas_assistant_probe.get("status"),
                    "summary": canvas_assistant_probe.get("summary"),
                    "first_apply_latency_ms": canvas_assistant_evidence.get(
                        "first_apply_latency_ms"
                    ),
                    "journal_event_count": canvas_assistant_evidence.get(
                        "journal_event_count"
                    ),
                    "provider_request_count": canvas_assistant_evidence.get(
                        "provider_request_count"
                    ),
                    "provider_contract_guards": canvas_assistant_evidence.get(
                        "provider_contract_guards"
                    ),
                    "provider_late_result_discarded": (
                        canvas_assistant_evidence.get("provider_late_result_discarded")
                    ),
                    "source_hash_before": canvas_assistant_evidence.get(
                        "source_hash_before"
                    ),
                    "source_hash_after": canvas_assistant_evidence.get(
                        "source_hash_after"
                    ),
                    "artifacts": canvas_assistant_probe.get("artifacts"),
                    "limitations": canvas_assistant_probe.get("limitations"),
                },
            )
        )
        from sciplot_core.promotion_probe import run_promotion_probe

        session_evidence_artifacts = session_evidence_probe.get("artifacts")
        session_evidence_artifacts = (
            session_evidence_artifacts
            if isinstance(session_evidence_artifacts, dict)
            else {}
        )
        data_mapping_artifacts = data_mapping_probe.get("artifacts")
        data_mapping_artifacts = (
            data_mapping_artifacts
            if isinstance(data_mapping_artifacts, dict)
            else {}
        )
        canvas_assistant_artifacts = canvas_assistant_probe.get("artifacts")
        canvas_assistant_artifacts = (
            canvas_assistant_artifacts
            if isinstance(canvas_assistant_artifacts, dict)
            else {}
        )
        promotion_probe = run_promotion_probe(
            output_root=run_root / "promotion",
            synthetic_session_ledger=Path(
                str(session_evidence_artifacts["canvas_ledger"])
            ),
            mapping_execution=Path(str(data_mapping_artifacts["execution"])),
            canvas_project=(
                Path(str(canvas_assistant_artifacts["run_root"])) / "project"
            ),
        )
        checks.append(
            _check(
                "reviewed_promotion_mechanism",
                "Replay-verified mapping executions and committed Canvas "
                "transactions canonicalize into powerless candidates; "
                "synthetic evidence, mixed-owner or duplicate-task vote "
                "stuffing, unsigned or session-unbound receipts, rewritten "
                "states, unrelated probes, mutable Git/index authority, "
                "self-attested mapping effects, raw values, provider "
                "identities, object IDs, and tampered collections cannot "
                "cross the reviewed gate",
                promotion_probe.get("status") == "passed",
                detail={
                    "status": promotion_probe.get("status"),
                    "summary": promotion_probe.get("summary"),
                    "artifacts": promotion_probe.get("artifacts"),
                    "limitations": promotion_probe.get("limitations"),
                },
            )
        )
        from sciplot_core.openai_provider_probe import run_openai_provider_probe

        openai_provider_probe = run_openai_provider_probe(
            output_root=run_root / "openai_provider",
        )
        checks.append(
            _check(
                "openai_responses_provider_boundary",
                "The production Responses adapter streams strict structured output, "
                "enforces the selected-object capability catalog, cancels safely, "
                "and redacts credentials",
                openai_provider_probe.get("status") == "passed",
                detail={
                    "status": openai_provider_probe.get("status"),
                    "summary": openai_provider_probe.get("summary"),
                    "artifacts": openai_provider_probe.get("artifacts"),
                    "limitations": openai_provider_probe.get("limitations"),
                },
            )
        )
        from sciplot_core.canvas_openai_provider_probe import (
            run_canvas_openai_provider_probe,
        )

        canvas_openai_probe = run_canvas_openai_provider_probe(
            project_dir,
            output_root=run_root / "canvas_openai_provider",
        )
        checks.append(
            _check(
                "native_canvas_openai_provider_lifecycle",
                "A natural-language request reaches the production adapter from "
                "the visible Canvas, previews without mutation, applies through "
                "the typed gateway, and rolls back exactly",
                canvas_openai_probe.get("status") == "passed",
                detail={
                    "status": canvas_openai_probe.get("status"),
                    "summary": canvas_openai_probe.get("summary"),
                    "evidence": canvas_openai_probe.get("evidence"),
                    "artifacts": canvas_openai_probe.get("artifacts"),
                    "limitations": canvas_openai_probe.get("limitations"),
                },
            )
        )
        launcher_probe = _portable_launcher_probe(project_dir)
        checks.append(
            _check(
                "portable_project_launchers",
                "Generated Studio, Veusz, and exact-export launchers locate and load the moved project",
                launcher_probe.get("passed") is True,
                detail=launcher_probe,
            )
        )
        with document_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n{MANUAL_EDIT_MARKER}\n")

        export_payload = export_studio_document(
            document_path, formats=["pdf", "tiff_300"]
        )
        exports = (
            export_payload.get("exports")
            if isinstance(export_payload.get("exports"), list)
            else []
        )
        studio_run = publish_studio_export_run(
            project_dir=project_dir,
            request_path=request_path,
            document_path=document_path,
            exports=exports,
            export_document_sha256=str(
                export_payload["document_sha256"]
            ),
        )
        manifest_path = Path(str(studio_run["manifest"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        semantic = (
            manifest.get("semantic")
            if isinstance(manifest.get("semantic"), dict)
            else {}
        )
        transform = (
            manifest.get("transform_ledger")
            if isinstance(manifest.get("transform_ledger"), dict)
            else {}
        )
        publication_intent = (
            manifest.get("publication_intent")
            if isinstance(manifest.get("publication_intent"), dict)
            else {}
        )
        delivery = (
            manifest.get("delivery_package")
            if isinstance(manifest.get("delivery_package"), dict)
            else {}
        )
        relocated_delivery_probe = _relocated_delivery_launcher_probe(
            run_root, delivery
        )
        editable_vsz = (
            delivery.get("editable_vsz")
            if isinstance(delivery.get("editable_vsz"), dict)
            else {}
        )
        editable_path = (
            Path(str(editable_vsz["path"])) if editable_vsz.get("path") else None
        )
        raw_archive_value = (manifest.get("raw_archive") or {}).get("path")
        raw_archive_path = Path(str(raw_archive_value)) if raw_archive_value else None
        exported_formats = {
            str(item.get("format")) for item in exports if isinstance(item, dict)
        }
        exports_exist = all(
            isinstance(item, dict)
            and item.get("exists") is True
            and int(item.get("size_bytes") or 0) > 0
            for item in exports
        )
        delivery_layout = _delivery_layout_probe(delivery)

        checks.extend(
            [
                _check(
                    "semantic_rule_selected",
                    "Synthetic FTIR input selects the ready FTIR rule",
                    semantic.get("rule_id") == EXPECTED_RULE_ID,
                    detail={
                        "selected": semantic.get("rule_id"),
                        "expected": EXPECTED_RULE_ID,
                    },
                ),
                _check(
                    "vsz_reopen_export",
                    "Veusz reopens the canonical VSZ and exports the canonical format pair",
                    document_path.exists()
                    and int(prepared.get("series_count") or 0) > 0
                    and {"pdf", "tiff_300"} <= exported_formats
                    and exports_exist,
                    detail={
                        "document": str(document_path),
                        "series_count": prepared.get("series_count"),
                        "formats": sorted(exported_formats),
                    },
                ),
                _check(
                    "manual_edit_preserved",
                    "A saved VSZ edit is preserved in the editable delivery copy",
                    manifest.get("manual_edit_detected") is True
                    and MANUAL_EDIT_MARKER in document_path.read_text(encoding="utf-8")
                    and editable_path is not None
                    and editable_path.exists()
                    and MANUAL_EDIT_MARKER in editable_path.read_text(encoding="utf-8"),
                    detail={
                        "manual_edit_detected": manifest.get("manual_edit_detected"),
                        "editable_vsz": str(editable_path)
                        if editable_path is not None
                        else None,
                    },
                ),
                _check(
                    "exact_current_vsz_hash",
                    "The current, exported, and delivered editable VSZ hashes match",
                    manifest.get("exported_document_hash") == file_sha256(document_path)
                    and editable_vsz.get("hash_matches_export") is True,
                    detail={
                        "exported_document_hash": manifest.get(
                            "exported_document_hash"
                        ),
                        "current_document_hash": file_sha256(document_path),
                        "delivery_document_hash": editable_vsz.get("actual_hash"),
                    },
                ),
                _check(
                    "canonical_pdf_tiff_pair",
                    "Delivery contains a canonical PDF and 300 dpi TIFF pair",
                    _delivery_artifact(delivery, "canonical_pdf_tiff_pairs").get(
                        "exists"
                    )
                    is True,
                    detail=_delivery_artifact(delivery, "canonical_pdf_tiff_pairs"),
                ),
                _check(
                    "minimal_delivery_layout",
                    "The user-facing delivery contains only four artifact groups and its Veusz launcher",
                    delivery_layout.get("passed") is True,
                    detail=delivery_layout,
                ),
                _check(
                    "qa_and_delivery_hashes",
                    "Artifact QA passes and its hashes match the delivery copies",
                    (manifest.get("qa") or {}).get("status") == "passed"
                    and _delivery_artifact(
                        delivery, "qa_artifact_hashes_match_delivery"
                    ).get("exists")
                    is True,
                    detail={
                        "qa_status": (manifest.get("qa") or {}).get("status"),
                        "hash_gate": _delivery_artifact(
                            delivery, "qa_artifact_hashes_match_delivery"
                        ),
                    },
                ),
                _check(
                    "delivery_complete",
                    "The portable delivery package is complete",
                    delivery.get("complete") is True,
                    detail={
                        "path": delivery.get("path"),
                        "complete": delivery.get("complete"),
                    },
                ),
                _check(
                    "relocated_delivery_launchers",
                    "A copied editable delivery locates SciPlot and loads its exact VSZ without runtime overrides",
                    relocated_delivery_probe.get("passed") is True,
                    detail=relocated_delivery_probe,
                ),
                _check(
                    "runtime_lineage_recorded",
                    "Runtime transform and publication contracts are recorded",
                    transform.get("status") == "runtime_recorded"
                    and publication_intent.get("kind") == "sciplot_publication_intent"
                    and raw_archive_path is not None
                    and raw_archive_path.exists(),
                    detail={
                        "transform_status": transform.get("status"),
                        "publication_kind": publication_intent.get("kind"),
                        "raw_archive": str(raw_archive_path)
                        if raw_archive_path is not None
                        else None,
                    },
                ),
            ]
        )

        standalone_probe = _standalone_export_probe(run_root, document_path)
        checks.append(
            _check(
                "standalone_vsz_exact_export",
                "A standalone VSZ without a spec sidecar exports to --out, passes artifact QA, and exits zero",
                standalone_probe.get("passed") is True,
                detail=standalone_probe,
            )
        )

        failure_probe_passed, failure_probe = _run_hash_failure_probe(
            Path(str(manifest["output"])),
            manifest,
        )
        checks.append(
            _check(
                "delivery_hash_failure_rejected",
                "A mismatched exported VSZ hash makes delivery incomplete",
                failure_probe_passed,
                detail=failure_probe,
            )
        )
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        checks.append(
            _check(
                "runtime_exception",
                "The runtime smoke completed without an exception",
                False,
                detail=error,
            )
        )

    status = (
        "passed"
        if checks and all(item["status"] == "passed" for item in checks)
        else "failed"
    )
    payload = {
        "kind": "sciplot_runtime_smoke",
        "version": RUNTIME_SMOKE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "state": "ready" if status == "passed" else "needs_rule_repair",
        "fixture": fixture,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(item["status"] == "passed" for item in checks),
            "failed_ids": [item["id"] for item in checks if item["status"] != "passed"],
        },
        "artifacts": {
            "run_root": str(run_root),
            "project_dir": str(project_dir) if project_dir is not None else None,
            "manifest": str(manifest_path) if manifest_path is not None else None,
            "summary": str(summary_path),
        },
        "error": error,
        "limitations": [
            "The generated FTIR and scalar-field tables are synthetic contract fixtures, "
            "not real-data evidence.",
            "This smoke proves one representative Studio lifecycle, project and relocated-delivery "
            "launcher checks, a standalone exact-current export, and a delivery hash failure path; "
            "it does not replace the complete ready-rule acceptance matrix.",
            "The OpenAI provider gates use an in-memory HTTP/SSE wire fixture and do not "
            "claim live-model quality or a successful paid API call.",
            "The session-evidence gate uses synthetic contracts and adversarial "
            "mutations; it never counts as owner-operated M3/M6 evidence.",
            "The promotion gate uses simulated threshold records and a replayed "
            "synthetic ledger; it creates no real candidate or promotion.",
            "Lifecycle success and artifact QA do not establish blanket journal compliance.",
        ],
    }
    summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


__all__ = ["run_runtime_smoke"]
