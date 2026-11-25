"""Source-only public control checkout; this is not an OS isolation boundary.

The ordinary public guard still owns public test execution. Only the generated
observer launch port may use a private-absent stage to exercise missing hooks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, cast, overload

from sciplot_core.verification.public_stage_selection import (
    PLATFORM_SKIPS as PLATFORM_SKIPS,
    TARGETED_SCOPES,
    record_report as pytest_runtest_logreport,  # noqa: F401 (pytest hook)
    take_reports,
    reset_reports as pytest_sessionstart,  # noqa: F401 (pytest hook)
    review_stage_reports as review_stage_reports,
    selected_public_nodes as _selected_public_nodes,
    target_modules, validate_profile_selectors,
)

PRIVATE_NAMES = ("real_world", "polymer_corpus", "archived_output_raw_data", "rendering_profiles")
RECEIPT = ".tmp_verify/public-source-stage.json"
HELPERS = ("_nc_cntr", "qtmml", "qtloops", "recordpaint", "threed")
BINDING_CHECKS = ("private_namespace_absent", "stage_source_equal", "origin_source_equal",
                  "stage_head_equal", "origin_head_equal", "runtime_equal", "stage_runtime_equal")
CLAIM = "private-absent generated behavior; no OS isolation, scientific acceptance or complete private access capture"
def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@overload
def _git(root: Path, *arguments: str, input_bytes: None = None) -> str: ...


@overload
def _git(root: Path, *arguments: str, input_bytes: bytes) -> bytes: ...


def _git(root: Path, *arguments: str, input_bytes: bytes | None = None) -> str | bytes:
    if any(os.environ.get(key) for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_TEMPLATE_DIR", "GIT_CONFIG_COUNT")):
        raise ValueError("Controlled source inventory rejects inherited Git namespace overrides.")
    environment = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    command = ["git", "-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false", *arguments]
    result = subprocess.run(command, cwd=root, env=environment, input=input_bytes,
                            text=input_bytes is None, capture_output=True, check=True)
    # subprocess typing cannot express the input-bytes-dependent return type.
    return cast(str | bytes, result.stdout)


def private_namespace_paths(root: Path) -> list[Path]:
    return [*(root / "tests/fixtures" / name for name in PRIVATE_NAMES), root / ".local"]


def _no_alias(path: Path, root: Path) -> None:
    current = path
    while current != root.parent:
        if current.is_symlink():
            raise ValueError("Public control namespace contains a lexical alias.")
        if current == root:
            break
        current = current.parent


def assert_private_absent(root: Path, environment: dict[str, str]) -> None:
    """Absence is a source namespace contract, never a filesystem sandbox claim."""
    if "SCIPLOT_REFERENCE_DATA" in environment:
        raise ValueError("Controlled public stages reject inherited reference-data configuration.")
    for path in private_namespace_paths(root):
        _no_alias(path, root)
        if path.exists() or path.is_symlink():
            raise ValueError("Controlled public source contains a private input namespace.")


def source_binding(root: Path) -> dict[str, str]:
    """Bind actual tracked bytes plus untracked source/config additions."""
    exclusions = [f":(exclude)tests/fixtures/{name}" for name in PRIVATE_NAMES]
    if _git(root, "status", "--porcelain", "--untracked-files=all", "--", ".", *exclusions, ":(exclude).local").strip():
        raise ValueError("Controlled public source must have a clean independent Git inventory.")
    paths = [name for name in _git(root, "ls-files", "-z").split("\0") if name]
    # Git ignore/index flags cannot hide a new executable source from closure.
    known = set(paths)
    ignored = {".git", ".tmp_verify", ".venv", ".local", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist"}
    for directory, names, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in list(names):
            path = parent / name
            private = any(path == root / "tests/fixtures" / part for part in PRIVATE_NAMES)
            if private:
                names.remove(name)
                continue
            if path.is_symlink() and not (parent == root and name in {".local", ".venv"}):
                raise ValueError("Public source directory contains an alias.")
            if name in ignored:
                names.remove(name)
        for name in files:
            path = parent / name
            relative = str(path.relative_to(root))
            if path.suffix in {".py", ".json", ".toml", ".sh"} and relative not in known:
                raise ValueError("Public source membership contains an untracked executable/config input.")
    result = {}
    for name in paths:
        if name == ".local" or name.startswith(".local/") or any(name.startswith(f"tests/fixtures/{part}/") for part in PRIVATE_NAMES):
            continue
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Public source inventory contains an alias or missing file.")
        result[name] = _hash(path)
    return result


def _helper_paths(root: Path, environment: dict[str, str]) -> dict[str, Path]:
    runtime = Path(environment.get("SCIPLOT_RUNTIME_REPO", str(root)))
    veusz = Path(environment.get("SCIPLOT_VEUSZ_ROOT", str(runtime / "third_party/veusz")))
    directory = veusz / "veusz/helpers"
    result = {}
    for name in HELPERS:
        matches = [path for path in directory.glob(f"{name}*.so") if path.is_file()]
        if len(matches) != 1:
            raise ValueError(f"Exactly one built native helper is required: {name}.")
        result[name] = matches[0]
    return result


def runtime_binding(root: Path, environment: dict[str, str]) -> dict[str, Any]:
    from PyQt6 import QtCore
    import pytest
    from _pytest.assertion import rewrite
    from sciplot_core.verification.private_process_boundaries import runtime_identity

    return {"python_executable": str(Path(sys.executable).resolve()), "python_sha256": _hash(Path(sys.executable)),
            "python_core_and_stdlib": runtime_identity(), "qt_binding_sha256": _hash(Path(QtCore.__file__)),
            "qt_version": QtCore.qVersion(), "pyqt_version": QtCore.PYQT_VERSION_STR,
            "pytest_version": pytest.__version__, "pytest_entry_sha256": _hash(Path(pytest.__file__)),
            "pytest_rewrite_sha256": _hash(Path(rewrite.__file__)),
            "helpers": {name: _hash(path) for name, path in _helper_paths(root, environment).items()},
            "claim": "actual Python core/owned stdlib, pytest entry/rewrite, QtCore binding and five helper bytes; not all native dependencies"}


def assert_stage_helpers(root: Path, environment: dict[str, str]) -> None:
    """Copied stage binaries cannot become external aliases with equal bytes."""
    directory = root / "third_party/veusz/veusz/helpers"
    _no_alias(directory, root)
    for path in _helper_paths(root, environment).values():
        _no_alias(path, root)


def validate_stage(root: Path, environment: dict[str, str], *additional_environments: dict[str, str]) -> dict[str, Any]:
    """Observe once for these owned environments; every call captures fresh facts."""
    from . import public_stage_environment

    root = root.absolute()
    environment, *others = [dict(item) for item in (environment, *additional_environments)]
    for item in (environment, *others):
        public_stage_environment.require_stage_environment(root, item)
    assert_private_absent(root, environment)
    if any((root / relative).resolve() != root / relative for _, relative in public_stage_environment.STAGE_ROOTS):
        raise ValueError("Controlled public source/runtime environment does not bind the actual stage.")
    receipt_path = root / RECEIPT
    if receipt_path.is_symlink():
        raise ValueError("Public stage receipt cannot be an alias.")
    receipt = json.loads(receipt_path.read_bytes())
    if (not isinstance(receipt, dict) or receipt.get("kind") != "sciplot_public_source_stage"
            or receipt.get("stage_root") != str(root) or receipt.get("claim") != CLAIM):
        raise ValueError("Unknown controlled public source receipt.")
    if source_binding(root) != receipt.get("source_bytes") or _git(root, "rev-parse", "HEAD").strip() != receipt.get("stage_head"):
        raise ValueError("Public stage source/config or independent Git identity drift.")
    assert_stage_helpers(root, environment)
    if runtime_binding(root, environment) != receipt.get("runtime"):
        raise ValueError("Public stage actual runtime bytes drift.")
    origin = Path(receipt["origin_root"])
    if source_binding(origin) != receipt.get("origin_source_bytes") or _git(origin, "rev-parse", "HEAD").strip() != receipt.get("origin_head"):
        raise ValueError("Public stage actual origin source/config identity drift.")
    for filename, source in (("public_stage.py", __file__), ("public_stage_environment.py", public_stage_environment.__file__)):
        loaded = Path(source).resolve()
        if loaded != root / "src/sciplot_core/verification" / filename or _hash(loaded) != receipt["source_bytes"].get(str(loaded.relative_to(root))):
            raise ValueError("Controlled public validator is not the bound loaded source.")
    return receipt


def create_stage(root: Path, output: Path, environment: dict[str, str]) -> tuple[Path, dict[str, str], dict[str, Any]]:
    """Copy public tracked source and exact native helpers, preserving origin."""
    from sciplot_core.verification.development_storage import without_development_storage
    environment = without_development_storage(environment)
    root = root.expanduser().resolve()
    output = Path(os.path.abspath(output.expanduser()))
    if "SCIPLOT_REFERENCE_DATA" in environment:
        raise ValueError("Controlled public stages reject inherited reference-data configuration.")
    for key, expected_root in (("SCIPLOT_REPO", root), ("SCIPLOT_SOURCE_ROOT", root / "src")):
        if key in environment and environment[key] != str(expected_root):
            raise ValueError("Stage origin environment does not bind the actual source owner.")
    if output.exists() or output.is_symlink() or not output.is_relative_to(root / ".tmp_verify"):
        raise ValueError("Public stage output must be a fresh ignored directory.")
    _no_alias(output, root)
    before = source_binding(root)
    origin_head = _git(root, "rev-parse", "HEAD").strip()
    runtime = runtime_binding(root, environment)
    stage = output / "source"
    stage.mkdir(parents=True)
    excluded = [f"tests/fixtures/{name}/" for name in PRIVATE_NAMES]
    public = {name: value for name, value in before.items() if not any(name.startswith(prefix) for prefix in excluded)
              and not name.startswith(".local/") and name != ".local"}
    for name, expected in public.items():
        original, target = root / name, stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        if _hash(target) != expected:
            raise ValueError("Source stage copy differs from actual origin bytes.")
    for path in _helper_paths(root, environment).values():
        target = stage / "third_party/veusz/veusz/helpers" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    _git(stage, "init", "-q")
    _git(stage, "config", "user.name", "SciPlot generated public stage")
    _git(stage, "config", "user.email", "public-stage@invalid")
    _git(stage, "add", "--all")
    _git(stage, "-c", "commit.gpgsign=false", "commit", "-qm", "Independent public source inventory")
    stage_head = _git(stage, "rev-parse", "HEAD").strip()
    if source_binding(stage) != public or source_binding(root) != before or _git(root, "rev-parse", "HEAD").strip() != origin_head:
        raise ValueError("Origin/stage source bytes changed during staging.")
    receipt = {"kind": "sciplot_public_source_stage", "version": 1, "claim": CLAIM, "stage_root": str(stage),
               "origin_root": str(root), "origin_head": origin_head, "origin_source_bytes": before,
               "source_bytes": public, "stage_head": stage_head, "excluded_namespaces": [str(path.relative_to(stage)) for path in private_namespace_paths(stage)],
               "runtime": runtime}
    (stage / ".tmp_verify").mkdir()
    (stage / RECEIPT).write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    child_environment = dict(environment, SCIPLOT_REPO=str(stage), SCIPLOT_SOURCE_ROOT=str(stage / "src"),
                             SCIPLOT_RUNTIME_REPO=str(stage), SCIPLOT_VEUSZ_ROOT=str(stage / "third_party/veusz"),
                             SCIPLOT_PYTHON=sys.executable, PYTHONPATH=os.pathsep.join((str(stage / "src"), str(stage / "tests"))))
    for key in ("SCIPLOT_PUBLIC_INPUT_GUARD", "SCIPLOT_PUBLIC_GUARD_BOOTSTRAP", "SCIPLOT_PUBLIC_GUARD_WRAPPER_BOOTSTRAP"):
        child_environment.pop(key, None)
    return stage, child_environment, receipt


def run_public_stage(root: Path, output: Path, profile: str, *, targets: list[str] | None = None) -> dict[str, Any]:
    """Run one existing public profile with its own fresh source stage."""
    validate_profile_selectors(profile, targets)
    return _run_public_profiles(root, output, [(profile, targets)], grouped=False)[0]


def run_public_profiles(
    root: Path, output: Path, profiles: list[tuple[str, list[str] | None]],
) -> list[dict[str, Any]]:
    """Share the source copy, never the pytest process, order or phase evidence."""
    if tuple(profile for profile, _ in profiles) not in {
        ("public-focused", "public-comprehensive"), ("public-affected", "public-affected-native"),
    }:
        raise ValueError("Grouped public stages require the reviewed profile order.")
    for profile, targets in profiles:
        validate_profile_selectors(profile, targets)
    return _run_public_profiles(root, output, profiles, grouped=True)


def _run_public_profiles(
    root: Path, output: Path, profiles: list[tuple[str, list[str] | None]], *, grouped: bool,
) -> list[dict[str, Any]]:
    root = root.expanduser().resolve()
    output = output.expanduser()
    output = output if output.is_absolute() else root / output
    environment = dict(os.environ)
    if environment.get("PYTEST_ADDOPTS", "").strip():
        raise ValueError("Controlled public profiles reject PYTEST_ADDOPTS filters/options.")
    stage, child_environment, before = create_stage(root, output, environment)
    if grouped:
        from sciplot_core.foundation.research_destination import require_data_destination

        # Keep generated project data outside the source and separate between tiers.
        scratch = require_data_destination(Path(tempfile.gettempdir()))
    results = []
    for profile, targets in profiles:
        destination = output / profile if grouped else output
        if grouped:
            destination.mkdir()
            pytest_root = str(Path(tempfile.mkdtemp(prefix="sciplot-public-", dir=scratch)))
        else:
            pytest_root = None
        result = _run_public_stage(root, destination, profile, targets, stage, environment,
                                   dict(child_environment), before, pytest_root=pytest_root)
        results.append(result)
        if result["status"] != "PASS":
            break
        if grouped and len(results) < len(profiles):
            # Reset generated stage outputs between processes, as distinct
            # stages did. Retain the earlier tier's diagnostics, never promote
            # its outputs to inputs for the next tier.
            scratch_path = (stage / RECEIPT).parent
            receipt = stage / RECEIPT
            _no_alias(receipt, stage)
            receipt_bytes = receipt.read_bytes()
            if json.loads(receipt_bytes) != before:
                raise ValueError("Controlled stage receipt changed during a public profile.")
            scratch_path.rename(destination / "stage-diagnostics")
            scratch_path.mkdir()
            receipt.write_bytes(receipt_bytes)
    return results


def _run_public_stage(
    root: Path, output: Path, profile: str, targets: list[str] | None, stage: Path,
    environment: dict[str, str], child_environment: dict[str, str], before: dict[str, Any],
    *, pytest_root: str | None,
) -> dict[str, Any]:
    affected = profile in TARGETED_SCOPES
    from sciplot_core.verification.input_scope import load_manifest
    manifest = load_manifest(stage / "src/sciplot_core/verification/input_scope_manifest.json")
    scope = TARGETED_SCOPES.get(profile, profile)
    expected = _selected_public_nodes(manifest, before["source_bytes"], profile, targets)
    finish = output / "finish.json"
    command = [sys.executable, "-m", "pytest", "-vv", "-p", "sciplot_core.verification.pytest_finish",
               "-p", "sciplot_core.verification.public_stage", "-p", "sciplot_core.verification.public_stage_selection",
               "--input-scope", scope]
    if pytest_root is not None:
        command.extend(("--basetemp", pytest_root))
    if targets:
        # Collect complete modules, not leaf node IDs: the manifest still
        # catches added, removed and reclassified siblings before any body.
        command.extend(value for target in targets for value in ("--sciplot-public-target", target))
        command.extend(sorted(target_modules(targets)))
    child_environment["SCIPLOT_VERIFY_FINISH"] = str(finish)
    child_environment["SCIPLOT_PUBLIC_STAGE_REPORT"] = str(output / "reports.json")
    with (output / "command.log").open("xb") as log:
        process = subprocess.run(command, cwd=stage, env=child_environment, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, close_fds=True, check=False)
    issues = []
    checks: dict[str, bool | None] = dict.fromkeys(BINDING_CHECKS)
    try:
        assert_private_absent(stage, child_environment)
        checks["private_namespace_absent"] = True
        checks["stage_source_equal"] = source_binding(stage) == before["source_bytes"]
        checks["origin_source_equal"] = source_binding(root) == before["origin_source_bytes"]
        checks["stage_head_equal"] = _git(stage, "rev-parse", "HEAD").strip() == before["stage_head"]
        checks["origin_head_equal"] = _git(root, "rev-parse", "HEAD").strip() == before["origin_head"]
        checks["runtime_equal"] = runtime_binding(root, environment) == before["runtime"]
        assert_stage_helpers(stage, child_environment)
        checks["stage_runtime_equal"] = runtime_binding(stage, child_environment) == before["runtime"]
        if not all(checks[key] is True for key in BINDING_CHECKS):
            raise ValueError("Actual source/stage/runtime closure drift after execution.")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        issues.append(str(error))
    marker = json.loads(finish.read_bytes()) if finish.is_file() else {}
    reports = json.loads((output / "reports.json").read_bytes()) if (output / "reports.json").is_file() else {}
    issues.extend(review_stage_reports(marker, reports, platform=sys.platform))
    if set(marker.get("selected_tests", [])) != expected:
        issues.append("Actual execution omitted or added an exact selected public node.")
    result = {"kind": "sciplot_public_source_stage_execution", "profile": profile,
              "claim": "limited_affected_public_behavior_not_canonical_profile" if affected else CLAIM,
              "selection_targets": targets, "canonical_profile_executed": not affected,
              "collection_scope": "affected_modules" if affected else "complete_suite",
              "status": "PASS" if process.returncode == 0 and not issues else "BLOCKED",
              "actual_exit_code": process.returncode, "execution_argv": command, "stage_root": str(stage),
              "origin_head": before["origin_head"], "stage_head": before["stage_head"], "issues": issues,
              "finish": marker, "binding_checks": checks,
              "source_before_after_equal": all(checks[key] is True for key in ("stage_source_equal", "origin_source_equal")),
              "scientific_acceptance": False, "access_capture_complete": False}
    (output / "result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    from sciplot_core.verification.evidence import atomic_json

    destination = os.environ.get("SCIPLOT_PUBLIC_STAGE_REPORT")
    if destination:
        atomic_json(Path(destination), {"selected_tests": [item.nodeid for item in session.items],
                                       "exit_code": int(exitstatus), "reports": take_reports()})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--profile", choices=("public-focused", "public-comprehensive", "public-all", "public-ci-full", *TARGETED_SCOPES), default="public-comprehensive")
    parser.add_argument("--target", action="append", dest="targets")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    try:
        if arguments.profile == "public-ci-full":
            if arguments.targets:
                raise ValueError("Full public CI does not take target selectors.")
            results = run_public_profiles(root, arguments.out, [
                ("public-focused", None), ("public-comprehensive", None)])
            result = {"status": results[-1]["status"], "profiles": results}
        else:
            result = run_public_stage(root, arguments.out, arguments.profile, targets=arguments.targets)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        result = {"kind": "sciplot_public_source_stage_execution", "status": "BLOCKED", "error": str(error), "executed_test_count": 0}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 4


if __name__ == "__main__":
    sys.exit(main())
