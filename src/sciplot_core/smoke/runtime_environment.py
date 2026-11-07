"""Probe imports, source wrappers, saved native closure, and standalone export."""

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


def _native_document_probe(
    documents: list[Path], *, portable_root: Path | None = None
) -> dict[str, Any]:
    """Safely cold-load every saved member without a window or launcher."""
    from sciplot_core.smoke.contracts import _inspect_veusz_document_state

    results: list[dict[str, Any]] = []
    root = portable_root.resolve() if portable_root is not None else None
    for document in documents:
        before = file_sha256(document)
        state = _inspect_veusz_document_state(document)
        links = state.get("linked_files")
        if not isinstance(links, list) or not all(isinstance(link, str) for link in links):
            raise ValueError("Native inspection did not observe linked-source metadata.")
        dependencies = []
        for filename in links:
            path = Path(filename).expanduser()
            path = (document.parent / path).resolve() if not path.is_absolute() else path.resolve()
            dependencies.append({"path": str(path), "exists": path.is_file(),
                                 "inside_package": root is None or path.is_relative_to(root)})
        current = file_sha256(document)
        results.append({
            "document": str(document), "sha256": before,
            "passed": before == current
            and state.get("document") == {"path": str(document.resolve()), "sha256": before}
            and bool(state.get("datasets")) and bool(state.get("pages"))
            and all(item["exists"] and item["inside_package"] for item in dependencies),
            "datasets": state.get("datasets"), "pages": state.get("pages"),
            "linked_sources": dependencies,
        })
    return {"passed": bool(results) and all(item["passed"] for item in results),
            "documents": results}


def _project_native_probe(project_dir: Path) -> dict[str, Any]:
    from sciplot_core.studio_core.project_query_paths import project_snapshot

    _request, _primary, figures = project_snapshot(project_dir)
    documents = [Path(entry["document"]) for entry in figures if entry.get("status") == "ready"]
    return _native_document_probe(documents)


def _relocated_delivery_native_probe(
    run_root: Path, delivery: dict[str, Any]
) -> dict[str, Any]:
    """Verify copied VSZ bytes and actual cold-load dependency closure."""
    source_value = delivery.get("path")
    if not source_value:
        return {"passed": False, "reason": "Delivery did not publish a portable package path."}
    source = Path(str(source_value)).expanduser().resolve()
    if not source.is_dir():
        return {"passed": False, "reason": "Delivery package path is not a directory.",
                "source": str(source)}
    original = {path.relative_to(source).as_posix(): file_sha256(path)
                for path in sorted((source / "project").rglob("*.vsz")) if path.is_file()}
    relocated = run_root / "relocated_delivery" / source.name
    relocated.parent.mkdir(parents=True, exist_ok=True)
    # An existing destination is an unexpected state, never a license to delete it.
    shutil.copytree(source, relocated)
    copied = {path.relative_to(relocated).as_posix(): file_sha256(path)
              for path in sorted((relocated / "project").rglob("*.vsz")) if path.is_file()}
    if not original or copied != original:
        raise ValueError("Relocation changed the complete native document membership or bytes.")
    probe = _native_document_probe([relocated / name for name in original], portable_root=relocated)
    after = {path.relative_to(source).as_posix(): file_sha256(path)
             for path in sorted((source / "project").rglob("*.vsz")) if path.is_file()}
    if after != original:
        raise ValueError("The original native delivery changed during relocation inspection.")
    probe.update({"source": str(source), "relocated": str(relocated),
                  "native_copy_sha256": copied})
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
