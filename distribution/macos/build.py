"""Build and verify a relocatable macOS .app without installing host software."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from distribution.macos.entrypoints import compile_finder_launcher, write_entrypoints
from distribution.macos.macho import Relocator, audit_runtime
from distribution.macos.mcp_probe import verify_mcp
from distribution.macos.runtime_files import QT_MODULES, copy_runtime


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_snapshot(repo: Path) -> dict[str, str]:
    files = [repo / "pyproject.toml", *[
        path for path in sorted((repo / "src").rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and ".git" not in path.parts
        and not any(part.endswith(".egg-info") for part in path.parts)
        and path.suffix != ".pyc" and path.name != ".DS_Store"
    ]]
    return {str(path.relative_to(repo)): file_hash(path) for path in files}


def isolated_environment() -> dict[str, str]:
    """Keep the host identity; remove inherited Python/Qt/repo resolution."""
    return {
        key: value for key, value in os.environ.items()
        if not key.startswith(("SCIPLOT_", "PYTHON", "QT_", "DYLD_", "QML"))
    } | {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}


def verify_app(app: Path, evidence: Path, *, smoke: bool = False) -> dict:
    evidence.mkdir(parents=True, exist_ok=False)
    command = app / "Contents/MacOS/sciplot"
    commands = [
        ("doctor", ["doctor", "--json"]),
        ("native_window", ["studio", "--qt-smoke"]),
        ("welcome", ["--welcome", "--out", str(evidence / "connection"), "--no-open"]),
    ]
    if smoke:
        commands.append(("runtime_smoke", ["smoke", "--out", str(evidence / "smoke"), "--json"]))
    results = []
    for name, arguments in commands:
        print(f"Verifying {name}…", flush=True)
        completed = subprocess.run(
            [str(command), *arguments], cwd=evidence, env=isolated_environment(),
            capture_output=True, text=True, timeout=900,
        )
        (evidence / f"{name}.stdout.json").write_text(completed.stdout)
        (evidence / f"{name}.stderr.log").write_text(completed.stderr)
        record = {"name": name, "returncode": completed.returncode}
        results.append(record)
        if completed.returncode:
            raise RuntimeError(f"{name} failed; see {evidence / (name + '.stderr.log')}")
        if name == "doctor" and json.loads(completed.stdout).get("status") != "ready":
            raise RuntimeError("Bundled Doctor did not report ready")
    report = {
        "status": "passed",
        "app": str(app),
        "platform": platform.platform(),
        "launch_environment": "inherited Python/Qt/SciPlot paths removed; PATH contains system tools only",
        "checks": results,
        "native_dependencies": audit_runtime(app / "Contents/Resources"),
        "clean_machine_test": "not_performed",
        "novice_user_test": "not_performed",
        "developer_id_signed": False,
        "notarized": False,
    }
    print("Verifying MCP stdio discovery and a capabilities call…", flush=True)
    report["mcp"] = verify_mcp(command, isolated_environment())
    (evidence / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def build_app(repo: Path, output: Path) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("This builder supports the current macOS architecture only")
    if output.suffix != ".app" or output.exists():
        raise ValueError("--out must name a new .app path; existing bundles are never overwritten")
    for tool in ("otool", "install_name_tool", "codesign"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"Build tool unavailable: {tool}")
    resources = output / "Contents/Resources"
    resources.mkdir(parents=True)
    before = source_snapshot(repo)
    print("Copying the interpreter, application and installed runtime dependencies…", flush=True)
    roots, inventory = copy_runtime(repo, resources)
    if source_snapshot(repo) != before:
        raise RuntimeError("Application source changed while copying; build again from stable source")
    for relative, expected in before.items():
        copied = resources / "app" / relative
        if not copied.is_file() or file_hash(copied) != expected:
            raise RuntimeError(f"Copied source does not match the build snapshot: {relative}")
    shutil.copytree(Path(__file__).parent, resources / "distribution-source", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(Path(__file__).with_name("welcome.py"), resources / "welcome.py")
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    write_entrypoints(output, version)
    compile_finder_launcher(output)
    print("Closing and relocating native dependencies…", flush=True)
    binaries = Relocator(resources, roots).run()
    manifest = {
        "kind": "sciplot_macos_distribution",
        "version": 1,
        "python": sys.version,
        "architecture": platform.machine(),
        "build_macos": platform.mac_ver()[0],
        "source_pyproject_sha256": file_hash(repo / "pyproject.toml"),
        "source_file_hashes": {
            str(path.relative_to(resources / "app")): file_hash(path)
            for path in sorted((resources / "app" / "src").rglob("*")) if path.is_file()
        },
        "dependencies": inventory,
        "qt_module_scope": sorted(QT_MODULES),
        "native_binaries": binaries,
        "runtime_dependency_audit": audit_runtime(resources),
        "signing": "ad_hoc_native_binaries_only; no Developer ID or notarization",
        "claims": {
            "self_contained_runtime_dependencies": True,
            "clean_machine_installation_verified": False,
            "novice_usability_verified": False,
            "other_architectures_or_macos_versions_verified": False,
            "bit_reproducible_build": False,
        },
    }
    (resources / "build-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Built {output} ({len(binaries)} native binaries)", flush=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path, required=True, help="New SciPlot.app path")
    parser.add_argument("--verify", type=Path, help="New verification evidence directory")
    parser.add_argument("--smoke", action="store_true", help="Also run the existing synthetic runtime smoke")
    parser.add_argument("--verify-existing", action="store_true", help="Verify an existing, optionally moved app")
    args = parser.parse_args()
    app = args.out.expanduser().resolve()
    if not args.verify_existing:
        build_app(args.repo.expanduser().resolve(), app)
    if args.verify:
        print(json.dumps(verify_app(app, args.verify.expanduser().resolve(), smoke=args.smoke), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
