"""Prepare a verified archive; public distribution requires Apple's local gates."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from distribution.macos.identity import bundle_snapshot, content_digest, file_hash
from distribution.macos.verification import verify_app


def assess_distribution(app: Path, evidence: Path) -> dict:
    """Inspect actual signatures/ticket; never sign, upload, or disable Gatekeeper."""
    commands = {
        "signature": ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
        "identity": ["/usr/bin/codesign", "--display", "--verbose=4", str(app)],
        "ticket": ["/usr/bin/xcrun", "stapler", "validate", str(app)],
        "gatekeeper": ["/usr/sbin/spctl", "--assess", "--type", "execute", "--verbose=4", str(app)],
    }
    results = {}
    evidence.mkdir(parents=True, exist_ok=False)
    for name, command in commands.items():
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            output = result.stdout + result.stderr
            passed = result.returncode == 0
            if name == "identity":
                passed = passed and "Authority=Developer ID Application:" in output and "TeamIdentifier=" in output
            (evidence / f"{name}.log").write_text(output)
            results[name] = {"passed": passed, "returncode": result.returncode}
        except (OSError, subprocess.TimeoutExpired) as error:
            results[name] = {"passed": False, "error": str(error)}
    return {"passed": all(item["passed"] for item in results.values()), "checks": results}


def prepare_release(app: Path, out: Path, *, public: bool = False) -> dict:
    app, out = app.resolve(strict=True), out.resolve()
    if app.suffix != ".app" or not app.is_dir():
        raise ValueError("--app must name an existing .app directory")
    if out.is_relative_to(app) or app.is_relative_to(out):
        raise ValueError("Release directory must not overlap the source application")
    out.mkdir(parents=True, exist_ok=False)
    report = {
        "kind": "sciplot_macos_release", "version": 1, "status": "running",
        "channel": "public" if public else "candidate", "public_distribution_ready": False,
        "independent_clean_machine_acceptance": "not_recorded",
        "independent_user_acceptance": "not_recorded",
    }
    report_path = out / "release.json"

    def save() -> None:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    save()
    try:
        original = bundle_snapshot(app)
        staged = out / "application" / app.name
        staged.parent.mkdir()
        # Preserve bundle links and attributes, including an existing notarization ticket.
        subprocess.run(["/usr/bin/ditto", str(app), str(staged)], check=True, capture_output=True, timeout=300)
        if bundle_snapshot(staged) != original or bundle_snapshot(app) != original:
            raise RuntimeError("Staged application does not match the source bundle")
        signing = assess_distribution(staged, out / "signing")
        report["distribution_assessment"] = signing
        save()
        if public and not signing["passed"]:
            raise ValueError("Public distribution requires Developer ID, a stapled notarization ticket and Gatekeeper acceptance; see signing logs")
        verification = verify_app(staged, out / "verification", smoke=True)
        if verification["status"] != "passed" or verification["bundle_sha256"] != content_digest(original):
            raise RuntimeError("Release verification does not identify the staged application")
        report["verification_sha256"] = file_hash(out / "verification/verification.json")
        manifest_path = staged / "Contents/Resources/build-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        report["build_manifest_sha256"] = file_hash(manifest_path)
        report["bundle_sha256"] = content_digest(original)
        report["app_version"] = manifest.get("app_version")
        report["architecture"] = manifest.get("architecture")
        # Names use the verified content identity, never uncontrolled manifest strings.
        archive = out / f"SciPlot-{report['channel']}-{report['bundle_sha256'][:12]}.zip"
        subprocess.run([
            "/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(staged), str(archive),
        ], check=True, capture_output=True, timeout=300)
        extracted = out / "archive-check"
        subprocess.run(["/usr/bin/ditto", "-x", "-k", str(archive), str(extracted)], check=True, capture_output=True, timeout=300)
        if bundle_snapshot(extracted / app.name) != original or bundle_snapshot(staged) != original:
            raise RuntimeError("Archived application differs from the verified bundle")
        report["archive"] = {"name": archive.name, "sha256": file_hash(archive), "bytes": archive.stat().st_size}
        (out / "SHA256SUMS").write_text(f"{report['archive']['sha256']}  {archive.name}\n")
        guide = staged / "Contents/Resources/app/docs/PUBLIC_BETA.md"
        shutil.copy2(guide, out / "START_HERE.md")
        report.update(status="passed", public_distribution_ready=public and signing["passed"])
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        save()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New release directory; never overwritten")
    parser.add_argument("--public", action="store_true", help="Require Developer ID, notarization ticket and Gatekeeper acceptance")
    args = parser.parse_args()
    try:
        report = prepare_release(args.app, args.out, public=args.public)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
