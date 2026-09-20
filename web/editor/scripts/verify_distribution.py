"""Verify built wheel resources and the editor's complete preferred source in sdist.

Run from a source checkout after building both distribution formats:
  .venv/bin/python web/editor/scripts/verify_distribution.py WHEEL SDIST
This reads the archives without installing anything into the active environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tarfile
import zipfile


def files_under(path: Path) -> list[Path]:
    result = []
    for directory, directories, files in os.walk(path):
        directories[:] = [name for name in directories if name not in {"node_modules", "__pycache__"}]
        result.extend(Path(directory) / name for name in files if not name.endswith(".pyc"))
    return sorted(result)


def check_bytes(actual: bytes, expected: Path, errors: list[str], name: str) -> None:
    if hashlib.sha256(actual).digest() != hashlib.sha256(expected.read_bytes()).digest():
        errors.append(f"Content differs: {name}")


def verify(wheel: Path, sdist: Path, root: Path) -> dict[str, object]:
    errors: list[str] = []
    assets = files_under(root / "src/sciplot_core/live_editor_assets")
    native = files_under(root / "src/sciplot_core/live_editor")
    native.append(root / "src/sciplot_core/veusz_worker/live_session.py")
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        expected_assets = {file.relative_to(root / "src").as_posix() for file in assets}
        packaged_assets = {name for name in names if name.startswith("sciplot_core/live_editor_assets/")}
        for name in sorted(packaged_assets - expected_assets):
            errors.append(f"Unexpected stale wheel asset: {name}")
        for file in [*assets, *native]:
            name = file.relative_to(root / "src").as_posix()
            if name not in names:
                errors.append(f"Missing wheel runtime file: {name}")
            else:
                check_bytes(archive.read(name), file, errors, name)
        if any("/node_modules/" in name or "/.tmp_verify/" in name for name in names):
            errors.append("Wheel includes dependencies or development evidence")
        license_name = "sciplot_core/live_editor_assets/tavotto-LICENSE.txt"
        if license_name in names:
            check_bytes(archive.read(license_name), root / "third_party/tavotto-ui/LICENSE", errors, license_name)
    source = [*files_under(root / "web/editor"), *files_under(root / "third_party/tavotto-ui"),
              root / "docs/THIRD_PARTY_NOTICES.md", root / "MANIFEST.in"]
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        regular = {member.name.split("/", 1)[1]: member for member in members
                   if member.isfile() and "/" in member.name}
        for file in source:
            name = file.relative_to(root).as_posix()
            if name not in regular:
                errors.append(f"Missing sdist preferred source: {name}")
            else:
                stream = archive.extractfile(regular[name])
                assert stream is not None
                check_bytes(stream.read(), file, errors, name)
        if any("/node_modules/" in member.name or "/.tmp_verify/" in member.name for member in members):
            errors.append("Source archive includes node_modules or development evidence")
    return {"status": "failed" if errors else "passed", "wheel_assets": len(assets),
            "native_modules": len(native), "preferred_source_files": len(source), "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("sdist", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[3])
    args = parser.parse_args()
    result = verify(args.wheel, args.sdist, args.source.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
