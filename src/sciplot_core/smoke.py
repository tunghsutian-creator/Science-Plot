from __future__ import annotations

import copy
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

from sciplot_core._paths import VENDORED_CORE_ROOT
from sciplot_core._utils import file_sha256, json_safe

RUNTIME_SMOKE_VERSION = 15
EXPECTED_RULE_ID = "ftir_spectrum"
MANUAL_EDIT_MARKER = "# SciPlot runtime smoke manual-edit preservation probe"


def _check(
    check_id: str, label: str, passed: bool, *, detail: Any = None
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def _delivery_artifact(delivery: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    artifacts = (
        delivery.get("artifacts") if isinstance(delivery.get("artifacts"), list) else []
    )
    for item in artifacts:
        if isinstance(item, dict) and item.get("id") == artifact_id:
            return item
    return {}


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
    for name in (
        "Open_in_SciPlot_Studio.command",
        "Open_in_Veusz.command",
        "Export_Edited_Veusz.command",
    ):
        launcher = project_dir / name
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

    projects = (
        delivery.get("editable_vsz_projects")
        if isinstance(delivery.get("editable_vsz_projects"), list)
        else []
    )
    project = projects[0] if projects and isinstance(projects[0], dict) else {}
    source_value = project.get("path")
    if not source_value:
        return {
            "passed": False,
            "reason": "Delivery did not publish an editable VSZ project.",
        }
    source = Path(str(source_value)).expanduser().resolve()
    relocated = run_root / "relocated_delivery" / source.name
    if relocated.exists():
        shutil.rmtree(relocated)
    relocated.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, relocated)
    probe = _portable_launcher_probe(relocated, ignore_runtime_overrides=True)
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
    from sciplot_core.studio import StudioSeries, _apply_series_options

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
        and len(set(swelling_non_color_signatures)) == 9
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
            "non_color_signatures": swelling_non_color_signatures,
        },
    }


def _scalar_field_render_probe(run_root: Path) -> dict[str, Any]:
    """Exercise the public XYZ-to-Veusz scalar-field contract."""

    import pandas as pd

    from sciplot_core.render import render_to_dir

    source = run_root / "scalar_field_contract" / "field_xyz.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "thickness_mm": [-2.0, 0.0, 2.0, -2.0, 0.0, 2.0],
            "in_plane_mm": [0.0, 0.0, 0.0, 20.0, 20.0, 20.0],
            "temperature_C": [125.0, 265.0, 125.0, 125.0, 265.0, 125.0],
        }
    ).to_csv(source, index=False)
    rendered = render_to_dir(
        source,
        template="heatmap",
        output_dir=source.parent / "rendered",
        options={
            "size": "60x55",
            "data_variables": {
                "x": "thickness_mm",
                "y": "in_plane_mm",
                "z": "temperature_C",
            },
            "z_min": 125.0,
            "z_max": 265.0,
            "contour_levels": [160.0, 230.0],
            "highlight_contour_levels": [195.0],
            "show_colorbar": True,
        },
        export_formats=("pdf",),
    )
    outputs = [Path(str(path)) for path in rendered.get("outputs") or []]
    document = Path(str((rendered.get("veusz_documents") or [""])[0]))
    document_text = document.read_text(encoding="utf-8") if document.exists() else ""
    colorbar_index = document_text.find("Add('colorbar', name='field_colorbar'")
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
        and 0 <= colorbar_index < image_index
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
        "overlay_order": {
            "colorbar_before_image_in_object_tree": 0 <= colorbar_index < image_index,
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
            "Lifecycle success and artifact QA do not establish blanket journal compliance.",
        ],
    }
    summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


__all__ = ["run_runtime_smoke"]
