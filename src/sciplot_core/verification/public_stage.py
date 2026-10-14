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
from typing import Any

PRIVATE_NAMES = ("real_world", "polymer_corpus", "archived_output_raw_data", "rendering_profiles")
RECEIPT = ".tmp_verify/public-source-stage.json"
HELPERS = ("_nc_cntr", "qtmml", "qtloops", "recordpaint", "threed")
CLAIM = "private-absent generated behavior; no OS isolation, scientific acceptance or complete private access capture"
PLATFORM_SKIPS = {
    "tests/test_macos_distribution.py::test_build_refuses_existing_output_before_copying": ("call", "Skipped: macOS builder"),
    "tests/test_verification_evidence_runtime.py::test_runtime_keeps_logical_roots_and_missing_enabled_usersite": ("setup", "Skipped: default runtime policy binds the actual macOS build"),
    "tests/test_verification_evidence_runtime.py::test_relative_runtime_environment_binds_real_child_inputs": ("setup", "Skipped: default runtime policy binds the actual macOS build"),
    "tests/test_private_observer_native.py::test_actual_mac_qt_reexec_is_sealed_and_continued": ("call", "Skipped: The actual Qt framework reexec path belongs to macOS."),
}
_reports: list[dict[str, Any]] = []


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *arguments: str) -> str:
    if any(os.environ.get(key) for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_TEMPLATE_DIR", "GIT_CONFIG_COUNT")):
        raise ValueError("Controlled source inventory rejects inherited Git namespace overrides.")
    environment = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(["git", "-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false", *arguments],
                          cwd=root, env=environment, text=True, capture_output=True, check=True).stdout


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


def validate_stage(root: Path, environment: dict[str, str]) -> dict[str, Any]:
    """Validate the actual stage; a caller flag or missing corpus is insufficient."""
    root = root.absolute()
    assert_private_absent(root, environment)
    for key, expected in (("SCIPLOT_REPO", root), ("SCIPLOT_SOURCE_ROOT", root / "src"),
                          ("SCIPLOT_RUNTIME_REPO", root), ("SCIPLOT_VEUSZ_ROOT", root / "third_party/veusz")):
        if environment.get(key) != str(expected) or expected.resolve() != expected:
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
    loaded = Path(__file__).resolve()
    expected_module = root / "src/sciplot_core/verification/public_stage.py"
    if loaded != expected_module or _hash(loaded) != receipt["source_bytes"].get(str(loaded.relative_to(root))):
        raise ValueError("Controlled public validator is not the bound loaded source.")
    return receipt


def create_stage(root: Path, output: Path, environment: dict[str, str]) -> tuple[Path, dict[str, str], dict[str, Any]]:
    """Copy public tracked source and exact native helpers, preserving origin."""
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


def run_public_stage(root: Path, output: Path, profile: str) -> dict[str, Any]:
    if profile not in {"public-focused", "public-comprehensive", "public-all"}:
        raise ValueError("Only exact public profiles may execute in a source stage.")
    root = root.expanduser().resolve()
    output = output.expanduser()
    output = output if output.is_absolute() else root / output
    environment = dict(os.environ)
    if environment.get("PYTEST_ADDOPTS", "").strip():
        raise ValueError("Controlled public profiles reject PYTEST_ADDOPTS filters/options.")
    stage, child_environment, before = create_stage(root, output, environment)
    finish = output / "finish.json"
    command = [sys.executable, "-m", "pytest", "-q", "-p", "sciplot_core.verification.pytest_finish",
               "-p", "sciplot_core.verification.public_stage", "--input-scope", profile]
    child_environment["SCIPLOT_VERIFY_FINISH"] = str(finish)
    child_environment["SCIPLOT_PUBLIC_STAGE_REPORT"] = str(output / "reports.json")
    with (output / "command.log").open("xb") as log:
        process = subprocess.run(command, cwd=stage, env=child_environment, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, close_fds=True, check=False)
    issues = []
    checks: dict[str, bool | None] = dict.fromkeys(("private_namespace_absent", "stage_source_equal", "origin_source_equal",
                                                "stage_head_equal", "origin_head_equal", "runtime_equal", "stage_runtime_equal"))
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
        if not all(checks.values()):
            raise ValueError("Actual source/stage/runtime closure drift after execution.")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        issues.append(str(error))
    marker = json.loads(finish.read_bytes()) if finish.is_file() else {}
    reports = json.loads((output / "reports.json").read_bytes()) if (output / "reports.json").is_file() else {}
    issues.extend(review_stage_reports(marker, reports, platform=sys.platform))
    from sciplot_core.verification.input_scope import load_manifest
    manifest = load_manifest(stage / "src/sciplot_core/verification/input_scope_manifest.json")
    expected = set(manifest["scopes"]["public"])
    if profile != "public-all":
        expected.intersection_update(manifest["tiers"][profile.removeprefix("public-")])
    if set(marker.get("selected_tests", [])) != expected:
        issues.append("Actual execution omitted or added an exact public profile node.")
    complete = not issues
    result = {"kind": "sciplot_public_source_stage_execution", "profile": profile, "claim": CLAIM,
              "status": "PASS" if process.returncode == 0 and complete and not issues else "BLOCKED",
              "actual_exit_code": process.returncode, "execution_argv": command, "stage_root": str(stage),
              "origin_head": before["origin_head"], "stage_head": before["stage_head"], "issues": issues,
              "finish": marker, "binding_checks": checks,
              "source_before_after_equal": all(checks[key] is True for key in ("stage_source_equal", "origin_source_equal")),
              "scientific_acceptance": False, "access_capture_complete": False}
    (output / "result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def review_stage_reports(marker: dict[str, Any], reports: dict[str, Any], *, platform: str) -> list[str]:
    """Every selected node needs actual successful reports or an exact OS skip."""
    selected = marker.get("selected_tests")
    if (marker.get("complete") is not True or marker.get("exit_code") != 0 or not isinstance(selected, list)
            or not selected or len(selected) != len(set(selected)) or reports.get("selected_tests") != selected
            or reports.get("exit_code") != 0):
        return ["Actual public stage session finish is absent, incomplete or mismatched."]
    rows = reports.get("reports")
    if not isinstance(rows, list) or any(not isinstance(row, dict) or row.get("nodeid") not in selected
                                         or row.get("when") not in {"setup", "call", "teardown"} for row in rows):
        return ["Unknown public stage report scope."]
    passed = [row["nodeid"] for row in rows if row.get("when") == "call" and row.get("outcome") == "passed"]
    if passed != marker.get("executed_tests") or len(passed) != len(set(passed)):
        return ["Actual public call reports differ from successful body finish."]
    for node in selected:
        actual = [row for row in rows if row["nodeid"] == node]
        setup = [row for row in actual if row.get("when") == "setup"]
        call = [row for row in actual if row.get("when") == "call"]
        teardown = [row for row in actual if row.get("when") == "teardown"]
        skips = [row for row in actual if row.get("outcome") == "skipped"]
        if (len(setup) != 1 or len(teardown) != 1 or teardown[0].get("outcome") != "passed"
                or any(row.get("outcome") not in {"passed", "skipped"} for row in actual)):
            return ["Public stage setup/teardown/failure reports are incomplete."]
        if skips:
            expected = PLATFORM_SKIPS.get(node) if platform != "darwin" else None
            if (len(skips) != 1 or expected != (skips[0].get("when"), skips[0].get("skip_reason"))
                    or len(call) != (1 if skips[0].get("when") == "call" else 0)):
                return ["Unexpected public stage skip or omitted body."]
        elif len(call) != 1 or node not in passed or setup[0].get("outcome") != "passed":
            return ["A selected public body did not execute successfully."]
    return []


def pytest_sessionstart(session: Any) -> None:
    _reports.clear()


def pytest_runtest_logreport(report: Any) -> None:
    reason = str(report.longrepr[2]) if report.skipped and isinstance(report.longrepr, tuple) else None
    _reports.append({"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome, "skip_reason": reason})


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    from sciplot_core.verification.evidence import atomic_json

    destination = os.environ.get("SCIPLOT_PUBLIC_STAGE_REPORT")
    if destination:
        atomic_json(Path(destination), {"selected_tests": [item.nodeid for item in session.items],
                                        "exit_code": int(exitstatus), "reports": list(_reports)})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--profile", choices=("public-focused", "public-comprehensive", "public-all"), default="public-comprehensive")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    try:
        result = run_public_stage(root, arguments.out, arguments.profile)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        result = {"kind": "sciplot_public_source_stage_execution", "status": "BLOCKED", "error": str(error), "executed_test_count": 0}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 4


if __name__ == "__main__":
    sys.exit(main())
