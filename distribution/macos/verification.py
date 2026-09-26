"""Fail-closed local application checks with durable failure evidence."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path

from distribution.macos.identity import bundle_snapshot, content_digest, file_hash
from distribution.macos.macho import audit_runtime
from distribution.macos.mcp_probe import verify_mcp


def isolated_environment() -> dict[str, str]:
    return {
        key: value for key, value in os.environ.items()
        if not key.startswith(("SCIPLOT_", "PYTHON", "QT_", "DYLD_", "QML"))
    } | {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}


def validate_command_result(name: str, result: subprocess.CompletedProcess) -> dict:
    if result.returncode:
        raise RuntimeError(f"{name} exited {result.returncode}; inspect its saved stdout/stderr")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError(f"{name} returned a non-object JSON result")
    if name == "doctor":
        valid = payload.get("status") == "ready"
    elif name == "welcome":
        valid = payload.get("doctor_status") == "ready" and payload.get("mcp_available") is True
    else:
        valid = payload.get("status") == "passed"
    if not valid:
        raise RuntimeError(f"{name} did not report successful checks")
    return payload


def verify_app(app: Path, evidence: Path, *, smoke: bool = False) -> dict:
    app, evidence = app.resolve(), evidence.resolve()
    if evidence.is_relative_to(app):
        raise ValueError("Verification evidence must be outside the application")
    evidence.mkdir(parents=True, exist_ok=False)
    report = {
        "kind": "sciplot_macos_verification", "version": 1, "status": "running",
        "app": str(app), "platform": {"system": platform.system(), "macos": platform.mac_ver()[0], "architecture": platform.machine()}, "checks": [],
        "launch_environment": "inherited Python/Qt/SciPlot paths removed; PATH contains system tools only",
        "runtime_smoke_requested": smoke,
        "clean_machine_test": "not_performed", "novice_user_test": "not_performed",
        "signing_assessed": False, "developer_id_signed": None, "notarized": None,
    }
    report_path = evidence / "verification.json"

    def save() -> None:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    save()
    try:
        before = bundle_snapshot(app)
        report["bundle_sha256"] = content_digest(before)
        manifest_path = app / "Contents/Resources/build-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        report["build_manifest_sha256"] = file_hash(manifest_path)
        report["app_version"] = manifest.get("app_version")
        sources = manifest.get("source_file_hashes")
        if not isinstance(sources, dict) or not sources:
            raise ValueError("Missing build source identities")
        source_root = app / "Contents/Resources/app"
        for relative, expected in sources.items():
            path = (source_root / relative).resolve()
            if not path.is_relative_to(source_root) or not path.is_file() or file_hash(path) != expected:
                raise ValueError(f"Packaged source differs from build manifest: {relative}")
        # Check native closure before launching any bundled executable.
        report["native_dependencies"] = audit_runtime(app / "Contents/Resources")
        commands = [
            ("doctor", ["doctor", "--json"]),
            ("native_window", ["studio", "--qt-smoke"]),
            ("welcome", ["--welcome", "--out", str(evidence / "connection"), "--no-open"]),
        ]
        if smoke:
            commands.append(("runtime_smoke", ["smoke", "--out", str(evidence / "smoke"), "--json"]))
        command = app / "Contents/MacOS/sciplot"
        for name, arguments in commands:
            print(f"Verifying {name}…", flush=True)
            record = {"name": name, "status": "running"}
            report["checks"].append(record)
            save()
            try:
                result = subprocess.run(
                    [str(command), *arguments], cwd=evidence, env=isolated_environment(),
                    capture_output=True, text=True, timeout=900,
                )
                (evidence / f"{name}.stdout.json").write_text(result.stdout)
                (evidence / f"{name}.stderr.log").write_text(result.stderr)
                record["returncode"] = result.returncode
                validate_command_result(name, result)
                record["status"] = "passed"
            except Exception as error:
                record.update(status="failed", error=str(error))
                raise
            finally:
                save()
        print("Verifying MCP stdio discovery and task capabilities…", flush=True)
        report["mcp"] = verify_mcp(command, isolated_environment())
        if report["mcp"].get("status") != "passed":
            raise RuntimeError("Bundled MCP verification failed")
        if bundle_snapshot(app) != before:
            raise RuntimeError("Application bytes or permissions changed during verification")
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        save()
    return report
