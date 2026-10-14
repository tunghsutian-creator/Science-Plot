"""Trusted default closure for opt-in changed-owner evidence on the local Mac.

This policy binds the repository's scientific fixture namespaces and executable
runtime. It does not certify a new private-access audit or scientific acceptance.
No CLI caller can supply synthetic status, omitted domains or arbitrary paths.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, cast

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.verification.evidence import load_receipt
from sciplot_core.verification.evidence_identity import (
    PUBLIC_GOLDEN_REASON, PUBLIC_INPUT_POLICY, PUBLIC_RAW_REASON,
    capture_identity, digest, discover_files, public_test_members,
)
from sciplot_core.verification.evidence_runtime import QT_MODULES, native_dependencies, qt_import_bindings, runtime_inputs
from sciplot_core.verification.input_scope import MANIFEST, PROFILES, load_manifest

POLICY = "changed-owner-repository-runtime-closure-v1"
_CHECKS = {"pytest_changed_owners": "pytest", "ruff_changed_python": "ruff",
           "mypy_owned_scope": "mypy", "diff_whitespace": "git",
           **{f"pytest_{tier}": "pytest" for tier in ("focused", "comprehensive", "full", *PROFILES)}}
_PLUGIN = "sciplot_core.verification.pytest_finish"


def _validate_check(plan: dict[str, Any], check: dict[str, Any], root: Path) -> str:
    if plan.get("unowned_paths") or plan.get("status") in {"failed", "BLOCKED", "NO_TESTS"}:
        raise ValueError("unknown or empty changed-owner scope")
    check_id = check.get("check_id")
    if check_id not in _CHECKS or not any(
        row.get("check_id") == check_id and row.get("command") == check.get("command")
        for row in plan.get("checks", [])
    ):
        raise ValueError("check is not part of the current owner plan")
    command = check.get("command")
    module = _CHECKS[check_id]
    if not isinstance(command, list) or not command or not all(isinstance(arg, str) for arg in command):
        raise ValueError("invalid planned command")
    if module == "git":
        if command[:3] != ["git", "diff", "--check"]:
            raise ValueError("unexpected Git check scope")
    elif command[:3] != [sys.executable, "-m", module]:
        raise ValueError("planned command does not use the current checked runtime")
    if check_id in {f"pytest_{tier}" for tier in ("focused", "comprehensive", "full", *PROFILES)}:
        tier = check_id.removeprefix("pytest_")
        selector = ["--input-scope", tier] if tier in PROFILES else (["-m", tier] if tier != "full" else [])
        expected = [sys.executable, "-m", "pytest", "-q", *selector]
        if command != expected:
            raise ValueError("suite command does not match its reviewed profile")
    if not root.is_dir():
        raise ValueError("source checkout is unavailable")
    return module


def collect_check_tests(command: list[str], *, repo_root: Path,
                        environment: dict[str, str]) -> list[str]:
    """Collect exact selected pytest nodes without running test bodies."""
    (repo_root / ".tmp_verify").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="collection-", dir=repo_root / ".tmp_verify") as directory:
        finish = Path(directory) / "finish.json"
        result = subprocess.run([*command, "--collect-only"], cwd=repo_root,
                                env={**environment, "SCIPLOT_VERIFY_FINISH": str(finish)},
                                capture_output=True, text=True, timeout=90, check=False)
        marker = load_receipt(finish)
    if result.returncode not in {0, 5} or not isinstance(marker, dict) or marker.get("complete") is not True:
        raise ValueError("exact selected test collection did not complete")
    nodes = marker.get("selected_tests")
    if not isinstance(nodes, list) or not all(isinstance(node, str) and node.startswith("tests/") and "::" in node for node in nodes) or len(set(nodes)) != len(nodes):
        raise ValueError("invalid or duplicate collected test identifiers")
    return nodes


def _reviewed_noncandidate_sources(root: Path, environment: dict[str, str], nodes: list[str],
                                   inventory: dict[str, Any], inventory_path: Path) -> str:
    """Prove pure siblings against the complete reviewed collection/source set."""
    from sciplot_core.verification.private_corpus_audit import (
        nodeids_sha256, test_sources_sha256, validate_access_audit,
    )
    review = inventory["collection_audit"]
    if review.get("test_sources_sha256") != test_sources_sha256(root):
        raise ValueError("selected case has no reviewed private/synthetic disposition")
    complete = nodes
    if len(nodes) != review.get("nodeid_count") or nodeids_sha256(nodes) != review.get("nodeids_sha256"):
        complete = collect_check_tests([sys.executable, "-m", "pytest", "-q", "-p", _PLUGIN],
                                       repo_root=root, environment=environment)
    _, issues = validate_access_audit(inventory=inventory, inventory_path=inventory_path,
                                     repo_root=root, collected_nodeids=set(complete),
                                     dependencies={}, access_audit_path=None)
    if (len(set(complete)) != len(complete) or not set(nodes) <= set(complete)
            or [issue[0] for issue in issues] != ["access_audit_required"]):
        raise ValueError("selected case has no reviewed private/synthetic disposition")
    return cast(str, review["test_sources_sha256"])


def _corpus_paths(root: Path, environment: dict[str, str], nodes: list[str], *,
                  reviewed_sources: dict[str, str] | None = None) -> tuple[list[Path], Path]:
    inventory_path = root / "src/sciplot_core/verification/private_corpus_inventory.json"
    inventory = load_receipt(inventory_path)
    if not isinstance(inventory, dict) or inventory.get("kind") != "sciplot_private_corpus_dependencies":
        raise ValueError("scientific fixture inventory is missing or malformed")
    review = inventory.get("collection_audit", {})
    if not isinstance(review, dict) or review.get("static_review_complete") is not True:
        raise ValueError("scientific fixture namespace review is unavailable")
    cases = inventory.get("cases")
    candidates = review.get("candidate_nodeids")
    if not isinstance(cases, list) or not isinstance(candidates, list):
        raise ValueError("scientific fixture dispositions are unavailable")
    declared = {case["nodeid"] for case in cases if isinstance(case, dict) and isinstance(case.get("nodeid"), str)}
    if len(declared) != len(cases) or not all(isinstance(node, str) for node in candidates):
        raise ValueError("scientific fixture dispositions are malformed")
    synthetic = review.get("synthetic_candidates", [])
    if not isinstance(synthetic, list) or not all(
        isinstance(row, dict) and isinstance(row.get("nodeid"), str)
        and isinstance(row.get("reason"), str) and row["reason"].strip() for row in synthetic
    ):
        raise ValueError("scientific fixture dispositions are malformed")
    excluded = {row["nodeid"] for row in synthetic}
    if (len(set(candidates)) != len(candidates) or len(excluded) != len(synthetic)
            or declared & excluded or set(candidates) != declared | excluded):
        raise ValueError("scientific fixture dispositions are not an exact partition")
    modules = {node.split("::", 1)[0] for node in candidates}
    if any(node.split("::", 1)[0] in modules and node not in candidates for node in nodes):
        reviewed_hash = _reviewed_noncandidate_sources(root, environment, nodes, inventory, inventory_path)
        if reviewed_sources is not None:
            reviewed_sources["reviewed_test_sources_sha256"] = reviewed_hash
    selected_private = sorted(declared.intersection(nodes))
    if selected_private:
        from sciplot_core.verification.private_corpus import private_corpus_preflight
        # This checks actual declared fixtures without inventing a full collection.
        report = private_corpus_preflight(repo_root=root, inventory_path=inventory_path,
                                          selected_nodeids=selected_private, collected_nodeids=None)
        expected = {"collection_unverified", "inventory_incomplete", "static_audit_incomplete",
                    "access_audit_required", "stale_static_audit"}
        if any(issue["code"] not in expected for issue in report["issues"]):
            raise ValueError("selected scientific fixtures are missing, unsafe or unmapped")
    raw = [root / "tests/fixtures"]
    local = Path(environment.get("SCIPLOT_REFERENCE_DATA", str(root / ".local/reference_data"))).expanduser()
    local = local if local.is_absolute() else root / local
    raw.append(local)
    if not local.exists() and environment.get("SCIPLOT_REFERENCE_DATA"):
        raise ValueError("configured scientific fixture namespace is missing")
    return raw, inventory_path


def _repository_inputs(root: Path, nodes: list[str]) -> dict[str, list[Path]]:
    listing = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                             cwd=root, capture_output=True, text=True, check=True).stdout
    tracked = [root / name for name in listing.split("\0") if name and (root / name).is_file()]
    # Tests which inspect documentation must bind it; unrelated prose commits do
    # not invalidate executable-only scope. Conservative whole-module detection.
    selected_files = {root / node.split("::", 1)[0] for node in nodes}
    documents_needed = any(".md" in path.read_text(encoding="utf-8") or '"docs"' in path.read_text(encoding="utf-8")
                           for path in selected_files)
    config = [path for path in tracked if path.relative_to(root).parts[0] not in
              {"src", "tests", "third_party", "docs", "skill"} and path.suffix != ".md"]
    config.append(root / "pyproject.toml")
    if documents_needed:
        config.extend(path for path in tracked if path.suffix == ".md" or path.is_relative_to(root / "docs"))
    return {"implementation": [root / "src", root / "skill/scripts"],
            "tests": [root / "tests"], "config": sorted(set(config)),
            "owner_policy": [root / "src/sciplot_core/verification", root / "skill/SKILL.md",
                             root / "skill/references/development.md"]}


def _validate_external_literals(root: Path, nodes: list[str], bound_files: set[Path]) -> list[Path]:
    """Refuse real literal external inputs outside the declared namespaces.

Synthetic nonexistent paths used for negative tests do not become dependencies.
Generated tmp_path outputs remain command results, not pre-existing source data.
"""
    system_files = []
    for path in {root / node.split("::", 1)[0] for node in nodes}:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/") and "\n" not in node.value:
                candidate = Path(node.value)
                try:
                    exists = candidate.is_file()
                except OSError:
                    continue
                if exists and candidate.resolve() not in bound_files:
                    if candidate.parts[1] in {"bin", "sbin"} or str(candidate).startswith(("/usr/bin/", "/usr/sbin/", "/System/Library/")):
                        system_files.append(candidate.resolve())
                    else:
                        raise ValueError("selected test refers to an unbound existing external file")
    return system_files


def _git_inputs(root: Path) -> list[Path]:
    listing = subprocess.run(["git", "ls-files", "--cached", "-z"], cwd=root,
                             capture_output=True, text=True, check=True).stdout
    paths = [root / name for name in listing.split("\0") if name]
    symbolic = subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=root,
                              capture_output=True, text=True, check=False).stdout.strip()
    for name in ["HEAD", "index", "packed-refs", "refs", *([symbolic] if symbolic else [])]:
        value = subprocess.run(["git", "rev-parse", "--git-path", name], cwd=root,
                               capture_output=True, text=True, check=True).stdout.strip()
        paths.append((root / value).absolute())
    return paths


def build_check_spec(plan: dict[str, Any], check: dict[str, Any], repo_root: Path, *,
                     environment: dict[str, str], finish_path: Path) -> dict[str, Any]:
    """Build the sole trusted CLI default, with fresh discovery on every call."""
    root = repo_root.expanduser().resolve()
    module = _validate_check(plan, check, root)
    environment = dict(environment, SCIPLOT_VERIFY_FINISH=str(finish_path.resolve()),
                       SCIPLOT_VERIFY_QT_MODULES=json.dumps(sorted(QT_MODULES)))
    if not finish_path.resolve().is_relative_to(root / ".tmp_verify"):
        raise ValueError("completion evidence must stay in ignored local storage")
    if environment.get("SCIPLOT_PYTHON") and Path(environment["SCIPLOT_PYTHON"]).resolve() != Path(sys.executable).resolve():
        raise ValueError("secondary Python runtime closure is unknown")
    command = list(check["command"])
    if module == "pytest":
        command[3:3] = ["-p", _PLUGIN]
        nodes = collect_check_tests(command, repo_root=root, environment=environment)
    else:
        nodes = []
    discovery_bindings = {digest(str(path.resolve())): file_sha256(path)
                          for path in {root / node.split("::", 1)[0] for node in nodes} | {Path(__file__).resolve()}}
    paths = _repository_inputs(root, nodes)
    reviewed_sources = {}
    exclusions = {}
    public_profile = check["check_id"].removeprefix("pytest_").startswith("public-")
    if public_profile:
        manifest_path = root / MANIFEST.relative_to(Path(__file__).parents[3])
        manifest = load_manifest(manifest_path)
        if not set(nodes).issubset(manifest["scopes"]["public"]):
            raise ValueError("Public suite selected a private or unknown test body.")
        inventory = root / "src/sciplot_core/verification/private_corpus_inventory.json"
        # Include importable/generated public helpers while never entering the
        # four private namespaces. Capture rechecks this membership every time.
        public_tests, public_layout = public_test_members(root)
        public_fixtures = [path for path in public_tests if path.is_relative_to(root / "tests/fixtures")]
        paths["tests"] = public_tests
        private = [root / "tests/fixtures" / name for name in
                   ("real_world", "rendering_profiles", "polymer_corpus", "archived_output_raw_data")]
        paths["config"] = [path for path in paths["config"] if not any(path.is_relative_to(base) for base in private)]
        paths.update(raw=public_fixtures, golden=[],
                     corpus_policy=[inventory, manifest_path, Path(__file__).resolve()], inventory=[inventory, manifest_path])
        reviewed_sources["input_scope"] = check["check_id"].removeprefix("pytest_")
        reviewed_sources["excluded_input_domains"] = {
            "private_raw": "not_applicable: exact public node partition, generated/public behavior only",
            "private_goldens": "not_applicable: real scientific/native golden nodes retained in private/full",
        }
        exclusions["golden"] = PUBLIC_GOLDEN_REASON
        if not paths["raw"]:
            exclusions["raw"] = PUBLIC_RAW_REASON
        reviewed_sources["public_inputs"] = {
            "policy": PUBLIC_INPUT_POLICY, "profile": reviewed_sources["input_scope"],
            "manifest_path_sha256": digest(str(manifest_path.resolve())), "manifest_sha256": file_sha256(manifest_path),
            "selected_tests_sha256": digest(sorted(nodes)),
            "tests_layout_sha256": public_layout,
            "raw": "not_applicable" if "raw" in exclusions else "bound_public_files",
        }
    else:
        raw, inventory = _corpus_paths(root, environment, nodes, reviewed_sources=reviewed_sources)
        paths.update(raw=raw, golden=[root / "tests/fixtures/rendering_profiles"],
                     corpus_policy=[inventory, Path(__file__).resolve()], inventory=[inventory])
    runtime, host = runtime_inputs(repo_root=root, environment=environment)
    paths.update(runtime)
    if public_profile:
        # These exact import roots are already sealed by implementation bytes
        # and the public test namespace; retaining tests here re-enters private
        # fixtures. Preserve every other root, including aliases and subroots.
        paths["dependencies"] = [path for path in paths["dependencies"] if path not in {root / "src", root / "tests"}]
    if module == "git":
        git = shutil.which("git", path=environment.get("PATH"))
        if not git:
            raise ValueError("Git executable is unavailable")
        paths["dependencies"].append(Path(git))
        paths["config"].extend(_git_inputs(root))
    inputs: dict[str, dict[str, Any]] = {}
    discovered: dict[str, list[str]] = {}
    layouts: dict[str, str] = {}
    for domain, roots in sorted(paths.items()):
        if domain in exclusions:
            inputs[domain] = {"not_applicable": exclusions[domain]}
            discovered[domain] = []
            continue
        files, layouts[domain] = discover_files(roots, allow_missing=True)
        inputs[domain] = {"paths": [str(path) for path in roots], "symlinks": "resolve", "allow_missing": True}
        discovered[domain] = files
    discovery_bindings.update(qt_import_bindings([root / "src", root / "tests", runtime["native"][0] / "veusz"]))
    system = _validate_external_literals(root, nodes, {Path(name) for files in discovered.values() for name in files})
    discovered["native"].extend(str(path) for path in system)
    inputs["native"]["paths"].extend(str(path) for path in system)
    aliases: dict[str, str] = {}
    native = native_dependencies(sorted({name for key in ("native", "python", "dependencies", "qt")
                                          for name in discovered[key]}),
                                 executable=Path(sys.executable), environment=environment,
                                 bindings=discovery_bindings, aliases=aliases, repo_root=root)
    inputs["native"]["paths"] = sorted(set(inputs["native"]["paths"]) | {str(path) for path in native})
    # Seal additions/alias changes during graph discovery, as well as file bytes.
    for domain, roots in paths.items():
        if domain in exclusions:
            continue
        if discover_files(roots, allow_missing=True)[1] != layouts[domain]:
            raise ValueError("dependency-discovery membership changed")
    layouts["native"] = discover_files([Path(name) for name in inputs["native"]["paths"]], allow_missing=True)[1]
    scope = {"kind": "pytest" if module == "pytest" else "process",
             "closure_policy": PUBLIC_INPUT_POLICY if public_profile else POLICY,
             "check_id": check["check_id"], "host": host, "discovery_bindings": discovery_bindings,
             "discovery_layouts": layouts, "discovery_aliases": aliases, **reviewed_sources}
    if exclusions:
        scope["excluded_domains"] = exclusions
    if module == "git":
        diff = subprocess.run(["git", "diff", "--binary", *command[3:]], cwd=root,
                              capture_output=True, check=True).stdout
        scope["git_diff_sha256"] = digest(diff.hex())
    return {"repo_root": str(root), "command": command, "scope": scope,
            "selected_tests": nodes, "inputs": inputs, "environment": environment,
            "corpus": {"mode": "synthetic" if "raw" in exclusions else "declared", "complete": True,
                       "policy": PUBLIC_INPUT_POLICY if public_profile else POLICY,
                       "fresh_access_audit": False, "scientific_acceptance": False}}


def capture_check_identity(plan: dict[str, Any], check: dict[str, Any], repo_root: Path, *,
                           environment: dict[str, str], finish_path: Path) -> dict[str, Any]:
    spec = build_check_spec(plan, check, repo_root, environment=environment, finish_path=finish_path)
    return capture_identity(**{**spec, "repo_root": Path(spec["repo_root"])})
