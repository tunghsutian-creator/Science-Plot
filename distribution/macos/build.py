"""Build and verify a relocatable macOS .app without installing host software."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import tomllib
from pathlib import Path

from distribution.macos.entrypoints import compile_finder_launcher, write_entrypoints
from distribution.macos.macho import Relocator, audit_runtime
from distribution.macos.identity import content_digest, file_hash, source_snapshot as source_snapshot
from distribution.macos.verification import isolated_environment as isolated_environment, verify_app
from distribution.macos.runtime_files import QT_MODULES, copy_runtime


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
    shutil.copytree(repo / "distribution/macos", resources / "distribution-source", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(repo / "distribution/macos/welcome.py", resources / "welcome.py")
    if source_snapshot(repo) != before:
        raise RuntimeError("Application source changed while copying; build again from stable source")
    for relative, expected in before.items():
        copied = resources / "app" / relative
        if relative.startswith("distribution/macos/"):
            copied = resources / "distribution-source" / Path(relative).relative_to("distribution/macos")
        elif relative.startswith("distribution/"):
            continue
        elif relative.startswith("third_party/veusz/") and not copied.is_file():
            # Upstream development files are intentionally outside the runtime.
            continue
        if not copied.is_file():
            raise RuntimeError(f"Copied source is missing: {relative}")
        if file_hash(copied) != expected:
            raise RuntimeError(f"Copied source does not match the build snapshot: {relative}")
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    project = tomllib.loads((repo / "pyproject.toml").read_text())["project"]
    write_entrypoints(output, version, app_version=project["version"])
    compile_finder_launcher(output)
    print("Closing and relocating native dependencies…", flush=True)
    binaries = Relocator(resources, roots).run()
    manifest = {
        "kind": "sciplot_macos_distribution",
        "version": 2,
        "app_version": project["version"],
        "source_snapshot_sha256": content_digest(before),
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
        "distribution_channel": "candidate",
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
    if (args.verify_existing or args.smoke) and args.verify is None:
        parser.error("--verify-existing and --smoke require --verify")
    app = args.out.expanduser().resolve()
    if not args.verify_existing:
        build_app(args.repo.expanduser().resolve(), app)
    if args.verify:
        print(json.dumps(verify_app(app, args.verify.expanduser().resolve(), smoke=args.smoke), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
