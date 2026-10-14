"""Start a known suite once and inspect its original durable execution."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import subprocess
from uuid import uuid4
from typing import Any

from sciplot_core.verification.changed_evidence import _closed_directory
from sciplot_core.verification.durable_runner import run_status, start_run


from sciplot_core.verification.input_scope import PROFILES

SUITES = ("focused", "comprehensive", "full", *PROFILES)


def _audit_environment(
    root: Path, output: Path, plugin: Path | None, audit: Path | None,
) -> tuple[dict[str, str], Path | None]:
    environment = dict(os.environ, SCIPLOT_VERIFY_FINISH=str(output / "finish.json"))
    if (plugin is None) != (audit is None):
        raise ValueError("A frozen audit plugin and a separate audit output must be supplied together.")
    if plugin is None or audit is None:
        return environment, None
    plugin = _closed_directory(root, plugin)
    audit = _closed_directory(root, audit)
    if not all((plugin / filename).is_file() and not (plugin / filename).is_symlink()
               for filename in ("sciplot_closure_audit.py", "sitecustomize.py")):
        raise ValueError("The frozen audit directory must contain both observation plugins.")
    from sciplot_core.verification.private_observer import bootstrap_sources
    if any((plugin / filename).read_text(encoding="utf-8") != text for filename, text in bootstrap_sources().items()):
        raise ValueError("The observation bootstrap must match the supported source-owned implementation.")
    raw = Path(environment.get("SCIPLOT_REFERENCE_DATA", str(root / ".local/reference_data"))).expanduser()
    raw = (raw if raw.is_absolute() else root / raw).resolve()
    roots = [(root / "tests/fixtures").resolve(), raw]
    for dependency in [plugin, root / "src", root / "tests", *roots]:
        if audit.is_relative_to(dependency) or dependency.is_relative_to(audit):
            raise ValueError("Audit outputs cannot overlap any observation input.")
    if audit == output or audit.is_relative_to(output) or output.is_relative_to(audit):
        raise ValueError("The audit output must be separate from the durable execution directory.")
    if audit.exists():
        raise ValueError("The audit output already exists; inspect the original observation.")
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [str(plugin), environment.get("PYTHONPATH", "")]))
    plugins = environment.get("PYTEST_PLUGINS", "").split(",")
    environment["PYTEST_PLUGINS"] = ",".join(dict.fromkeys(filter(None, [*plugins, "sciplot_closure_audit"])))
    environment["SCIPLOT_PRIVATE_AUDIT_DIR"] = str(audit)
    environment["SCIPLOT_PRIVATE_AUDIT_ROOTS"] = json.dumps([str(path) for path in roots])
    environment["SCIPLOT_PRIVATE_AUDIT_RUN"] = uuid4().hex
    # Collection uses the same observation plugin as execution. Preserve its
    # original local output even if collection or closure discovery blocks.
    audit.mkdir(parents=True, exist_ok=False, mode=0o700)
    from sciplot_core.verification.private_observer import begin_suite_audit
    observer = begin_suite_audit(environment)
    if observer.directory != audit or observer.run != environment["SCIPLOT_PRIVATE_AUDIT_RUN"]:
        raise ValueError("The audit parent is already bound to another operation.")
    return environment, audit


def start_suite_verification(
    suite: str, *, directory: Path, repo_root: Path | None = None,
    audit_plugin_dir: Path | None = None, audit_out: Path | None = None,
) -> dict[str, Any]:
    """Prepare trusted bindings, then launch one supervised suite without waiting."""
    root = (repo_root or Path(os.environ.get("SCIPLOT_REPO", Path.cwd()))).expanduser().resolve()
    try:
        if suite not in SUITES:
            raise ValueError("Unknown verification suite.")
        if os.environ.get("PYTEST_ADDOPTS", "").strip():
            raise ValueError("Known suites require an unfiltered environment; PYTEST_ADDOPTS must be unset.")
        output = _closed_directory(root, directory)
        if output.exists():
            raise ValueError("The run directory already exists; use verify --status to inspect it.")
        if suite == "private-science":
            from sciplot_core.verification.input_scope import load_manifest
            from sciplot_core.verification.private_corpus import _collect_nodeids, declared_input_availability
            inventory_path = root / "src/sciplot_core/verification/private_corpus_inventory.json"
            manifest = load_manifest(root / "src/sciplot_core/verification/input_scope_manifest.json")
            collected = _collect_nodeids(root, inventory_path)
            availability = declared_input_availability(repo_root=root, inventory_path=inventory_path,
                                                      selected_nodeids=manifest["scopes"]["private"], collected_nodeids=collected)
            if availability["status"] == "BLOCKED":
                return {"kind": "sciplot_suite_verification", "status": "BLOCKED", "suite": suite,
                        "scientific_acceptance": False, "access_audit_complete": False,
                        "selected_test_count": availability["selected_count"], "executed_test_count": 0,
                        "error": {"reason_code": "private_inputs_unavailable", "message": "Declared private inputs are missing, unsafe or unmapped; no test bodies ran."},
                        "issues": availability["issues"]}
        environment, audit = _audit_environment(root, output, audit_plugin_dir, audit_out)
        if suite.startswith("public-"):
            from sciplot_core.verification.public_input_guard import configure_environment
            if audit_plugin_dir is not None:
                bootstrap = _closed_directory(root, audit_plugin_dir)
                # _audit_environment has already checked the common bootstrap's
                # complete bytes; it installs the observer before public guard.
            else:
                bootstrap = root / "src/sciplot_core/verification/public_guard_bootstrap"
            environment = configure_environment(root, environment, bootstrap=bootstrap)
        command = [sys.executable, "-m", "pytest", "-q"]
        if suite in PROFILES:
            command.extend(["--input-scope", suite])
        elif suite != "full":
            command.extend(["-m", suite])
        check = {"check_id": f"pytest_{suite}", "command": command, "status": "planned"}
        plan = {"kind": "sciplot_suite_verification", "version": 1,
                "suite": suite, "checks": [check], "owners": [], "changed_paths": []}
        from sciplot_core.verification.evidence_scope import build_check_spec

        spec = build_check_spec(plan, check, root, environment=environment,
                                finish_path=output / "finish.json")
        if audit is not None:
            for binding in spec["inputs"].values():
                for name in binding.get("paths", []):
                    dependency = Path(name).expanduser()
                    dependency = (dependency if dependency.is_absolute() else root / dependency).resolve()
                    if audit.is_relative_to(dependency) or dependency.is_relative_to(audit):
                        raise ValueError("Audit outputs overlap the trusted input closure.")
        result = start_run(directory=output, spec=spec)
        return {**result, "kind": "sciplot_suite_verification", "suite": suite,
                "claim": "execution_started_only", "execution_target": "current_worktree",
                "selected_test_count": len(spec["selected_tests"]),
                "scientific_acceptance": False, "audit_output": str(audit) if audit else None,
                "audit_root_pid": os.getpid() if audit else None,
                "audit_run_id": environment.get("SCIPLOT_PRIVATE_AUDIT_RUN") if audit else None}
    except (ImportError, OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        return {"kind": "sciplot_suite_verification", "status": "BLOCKED", "suite": suite,
                "reused": False, "scientific_acceptance": False,
                "error": {"reason_code": "verification_suite_unavailable", "message": str(exc)}}


def suite_verification_status(directory: Path, *, repo_root: Path | None = None) -> dict[str, Any]:
    """Read original execution proof without collecting tests or checking reuse."""
    root = (repo_root or Path(os.environ.get("SCIPLOT_REPO", Path.cwd()))).expanduser().resolve()
    try:
        output = _closed_directory(root, directory)
        result = run_status(output)
        selected = result.pop("selected_tests", [])
        scope = result.pop("scope", {})
        return {**result, "kind": "sciplot_suite_verification_status", "directory": str(output),
                "claim": "original_execution_only", "scientific_acceptance": False,
                "selected_test_count": len(selected), "check_id": scope.get("check_id")}
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        return {"kind": "sciplot_suite_verification_status", "status": "BLOCKED", "reused": False,
                "claim": "original_execution_only", "scientific_acceptance": False,
                "error": {"reason_code": "verification_status_unavailable", "message": str(exc)}}
