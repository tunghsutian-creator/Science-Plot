"""Probe imports, source wrappers, Qt windows, launchers, and standalone export."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from sciplot_core._paths import (
    PACKAGE_ROOT,
    REPO_ROOT,
)
from sciplot_core.foundation.file_hashing import file_sha256


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
    removed_compatibility_root = (PACKAGE_ROOT / "_vendor").resolve()
    compatibility_paths_added = []
    for item in added:
        try:
            if Path(item).expanduser().resolve() == removed_compatibility_root:
                compatibility_paths_added.append(item)
        except (OSError, RuntimeError):
            continue
    return {
        "passed": not compatibility_paths_added,
        "added_paths": added,
        "vendor_paths_added": compatibility_paths_added,
    }


def _source_checkout_wrapper_probe() -> dict[str, Any]:
    """Prove a checkout wrapper or installed CLI starts without import leakage."""

    package_source_root = PACKAGE_ROOT.parent
    wrapper = REPO_ROOT / "skill" / "scripts" / "sciplot"
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
    if wrapper.is_file():
        env["SCIPLOT_PYTHON"] = sys.executable
        env["SCIPLOT_REPO"] = str(REPO_ROOT)
        env["SCIPLOT_SOURCE_ROOT"] = str(package_source_root)
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
        "source_root": str(package_source_root),
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
        and payload.get("fail_closed_close_installed") is True
        and payload.get("atomic_save_installed") is True
        and payload.get("integrated_window_factory_installed") is True
        and payload.get("initial_widget_path") not in {None, "", "/"}
        and all(
            value is True
            for value in (
                payload.get("close_safety")
                if isinstance(payload.get("close_safety"), dict)
                else {}
            ).values()
        )
        and len(
            payload.get("close_safety")
            if isinstance(payload.get("close_safety"), dict)
            else {}
        )
        == 6
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
        "window_title": payload.get("window_title"),
        "initial_widget_path": payload.get("initial_widget_path"),
        "fail_closed_close_installed": payload.get("fail_closed_close_installed"),
        "atomic_save_installed": payload.get("atomic_save_installed"),
        "integrated_window_factory_installed": payload.get(
            "integrated_window_factory_installed"
        ),
        "close_safety": payload.get("close_safety"),
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
