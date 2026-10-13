"""Preflight for declared local-only scientific test inputs.

This is a development diagnostic. It does not select, skip, or run test bodies,
but collection imports test modules. Structural presence does not certify data.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from sciplot_core._paths import local_reference_root, resolve_fixture_path
from sciplot_core.materials_rules import get_rule

GATE = "private_corpus_preflight"
INVENTORY = Path(__file__).with_name("private_corpus_inventory.json")
DIRECTORY_RULE_IDS = frozenset({
    "gpc_sec_chromatogram", "rheology_creep", "rheology_frequency_sweep",
    "rheology_strain_sweep", "rheology_stress_relaxation",
    "rheology_stress_sweep", "rheology_temperature_sweep",
    "rheology_time_sweep", "tensile_curve", "torque_curve",
})
FIXTURE_PREFIX = Path("tests/fixtures/real_world")


def _issue(code: str, why: str, *, nodeid: str | None = None,
           path: str | None = None) -> dict[str, str]:
    issue = {"gate": GATE, "code": code, "why": why}
    if nodeid is not None:
        issue["nodeid"] = nodeid
    if path is not None:
        issue["path"] = path
    return issue


def _safe_fixture_identifier(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.parts[:3] != FIXTURE_PREFIX.parts:
        return None
    if len(path.parts) <= 3 or any(part in {"", "."} for part in path.parts):
        return None
    return path


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _resolved_fixture(identifier: Path, repo_root: Path) -> Path | None:
    candidate = resolve_fixture_path(identifier, repo_root=repo_root)
    tracked = repo_root / FIXTURE_PREFIX
    local = local_reference_root(repo_root=repo_root) / "real_world"
    return candidate if _within(candidate, tracked) or _within(candidate, local) else None


def _readable_nonempty_file(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    with path.open("rb") as handle:
        return bool(handle.read(1))


def _directory_has_safe_file(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    found = False
    for child in directory.rglob("*"):
        if child.is_symlink() or not _within(child, directory):
            return False
        if _readable_nonempty_file(child):
            found = True
    return found


def _load_inventory(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("kind") != "sciplot_private_corpus_dependencies":
        raise ValueError("inventory kind is missing or incorrect")
    if payload.get("version") != 1 or payload.get("gate") != GATE:
        raise ValueError("inventory version or gate is missing or incorrect")
    if not isinstance(payload.get("inventory_complete"), bool):
        raise TypeError("inventory_complete must be a boolean")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("inventory cases must be a nonempty list")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"nodeid", "dependencies", "evidence"}:
            raise ValueError("every case needs nodeid, dependencies, and evidence")
        nodeid = case["nodeid"]
        module_path = Path(nodeid.split("::", 1)[0]) if isinstance(nodeid, str) else Path("")
        if (not isinstance(nodeid, str) or not nodeid.startswith("tests/")
                or ".py::test_" not in nodeid or nodeid in seen
                or module_path.is_absolute() or module_path.parts[0] != "tests"
                or ".." in module_path.parts or module_path.suffix != ".py"
                or len(module_path.parts) < 2):
            raise ValueError(f"invalid or duplicate collected node ID: {nodeid!r}")
        seen.add(nodeid)
        if not isinstance(case["evidence"], str) or not case["evidence"]:
            raise ValueError(f"missing evidence for {nodeid}")
        dependencies = case["dependencies"]
        if not isinstance(dependencies, list) or not dependencies:
            raise ValueError(f"missing dependencies for {nodeid}")
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                raise TypeError(f"invalid dependency for {nodeid}")
            if set(dependency) == {"rule_id"}:
                if not isinstance(dependency["rule_id"], str) or not dependency["rule_id"]:
                    raise ValueError(f"invalid rule dependency for {nodeid}")
            elif set(dependency) in ({"path", "kind"}, {"path", "kind", "listed_sources"}):
                if (_safe_fixture_identifier(dependency["path"]) is None
                        or dependency["kind"] not in {"file", "directory"}):
                    raise ValueError(f"unsafe or invalid path dependency for {nodeid}")
                if "listed_sources" in dependency and (
                    dependency["kind"] != "file" or dependency["listed_sources"] != "source_files"
                ):
                    raise ValueError(f"invalid listed_sources dependency for {nodeid}")
            else:
                raise ValueError(f"unknown dependency kind for {nodeid}")
    return payload


def _case_dependencies(case: dict[str, Any]) -> list[tuple[Path, str, str | None]]:
    result: list[tuple[Path, str, str | None]] = []
    for dependency in case["dependencies"]:
        if "rule_id" in dependency:
            rule = get_rule(dependency["rule_id"])
            if rule.fixture_status != "ready":
                raise ValueError(f"rule {rule.rule_id} is not ready")
            identifier = _safe_fixture_identifier(rule.fixture_path)
            if identifier is None:
                raise ValueError(f"rule {rule.rule_id} has no safe fixture identifier")
            kind = "directory" if rule.rule_id in DIRECTORY_RULE_IDS else "file"
            result.append((identifier, kind, None))
        else:
            identifier = _safe_fixture_identifier(dependency["path"])
            if identifier is None:
                raise ValueError(f"unsafe fixture identifier: {dependency['path']!r}")
            result.append((identifier, dependency["kind"], dependency.get("listed_sources")))
    return result


def _listed_source_issues(path: Path, identifier: Path, repo_root: Path,
                          nodeid: str) -> list[dict[str, str]]:
    try:
        provenance = json.loads(path.read_text(encoding="utf-8"))
        records = provenance["source_files"]
        if not isinstance(records, list) or not records:
            raise ValueError("source_files must be a nonempty list")
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return [_issue("invalid_provenance", f"cannot read source_files: {exc}",
                       nodeid=nodeid, path=identifier.as_posix())]
    issues: list[dict[str, str]] = []
    for record in records:
        member = record.get("fixture_file") if isinstance(record, dict) else None
        if not isinstance(member, str) or not member or Path(member).is_absolute() or ".." in Path(member).parts:
            issues.append(_issue("unsafe_source_member", f"invalid fixture_file: {member!r}",
                                 nodeid=nodeid, path=identifier.as_posix()))
            continue
        member_id = identifier.parent / member
        try:
            resolved = _resolved_fixture(member_id, repo_root)
        except OSError as exc:
            issues.append(_issue("unreadable_source_member", f"cannot resolve listed source: {exc}",
                                 nodeid=nodeid, path=member_id.as_posix()))
            continue
        if resolved is None:
            issues.append(_issue("unsafe_source_member", "source member escapes fixture roots",
                                 nodeid=nodeid, path=member_id.as_posix()))
        else:
            try:
                valid = _readable_nonempty_file(resolved)
            except OSError:
                valid = False
            if not valid:
                issues.append(_issue("missing_or_empty_source_member", "listed source file is missing, unreadable, or empty",
                                     nodeid=nodeid, path=member_id.as_posix()))
    return issues


def private_corpus_preflight(*, repo_root: Path,
                             inventory_path: Path = INVENTORY,
                             selected_nodeids: list[str] | None = None,
                             collected_nodeids: set[str] | None = None) -> dict[str, Any]:
    """Diagnose declared case inputs without claiming complete private acceptance."""
    issues: list[dict[str, str]] = []
    try:
        inventory = _load_inventory(inventory_path)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        issues.append(_issue("invalid_inventory", str(exc), path=inventory_path.name))
        inventory = {"cases": [], "inventory_complete": False}
    cases = {case["nodeid"]: case for case in inventory["cases"]}
    if collected_nodeids is None:
        issues.append(_issue("collection_unverified", "current pytest collection was not checked"))
    else:
        for nodeid in cases.keys() - collected_nodeids:
            issues.append(_issue("stale_inventory_nodeid", "declared case is absent from current pytest collection",
                                 nodeid=nodeid))
    selected = list(cases) if selected_nodeids is None else selected_nodeids
    if not selected:
        issues.append(_issue("empty_selection", "no collected test node IDs were selected"))
    if len(set(selected)) != len(selected):
        issues.append(_issue("duplicate_selection", "selected node IDs contain duplicates"))
    rows: list[dict[str, Any]] = []
    for nodeid in dict.fromkeys(selected):
        case = cases.get(nodeid)
        if case is None:
            issues.append(_issue("unmapped_nodeid", "selected collected case has no declared dependency mapping",
                                 nodeid=nodeid))
            continue
        try:
            dependencies = _case_dependencies(case)
        except ValueError as exc:
            issues.append(_issue("invalid_dependency", str(exc), nodeid=nodeid))
            continue
        checked: list[dict[str, str]] = []
        for identifier, kind, listed_sources in dependencies:
            relative = identifier.as_posix()
            try:
                resolved = _resolved_fixture(identifier, repo_root)
            except OSError as exc:
                issues.append(_issue("unreadable_fixture", f"cannot resolve fixture: {exc}",
                                     nodeid=nodeid, path=relative))
                checked.append({"path": relative, "kind": kind, "status": "blocked"})
                continue
            if resolved is None:
                issues.append(_issue("unsafe_fixture", "resolved fixture escapes allowed roots",
                                     nodeid=nodeid, path=relative))
                checked.append({"path": relative, "kind": kind, "status": "blocked"})
                continue
            try:
                if kind == "file":
                    valid = _readable_nonempty_file(resolved)
                    reason = "required file is missing, wrong type, unreadable, or empty"
                else:
                    valid = _directory_has_safe_file(resolved)
                    reason = "required directory is missing, wrong type, empty, unreadable, or contains unsafe links"
            except OSError as exc:
                valid = False
                reason = f"cannot inspect required {kind}: {exc}"
            checked.append({"path": relative, "kind": kind,
                            "status": "present" if valid else "blocked"})
            if not valid:
                issues.append(_issue("missing_or_invalid_fixture", reason,
                                     nodeid=nodeid, path=relative))
            elif listed_sources:
                issues.extend(_listed_source_issues(resolved, identifier, repo_root, nodeid))
        rows.append({"nodeid": nodeid, "evidence": case["evidence"],
                     "dependencies": checked})
    declared_present = not issues
    if not inventory["inventory_complete"]:
        issues.append(_issue("inventory_incomplete",
                             "preliminary node-level mapping does not cover every private test or transitive source"))
    return {
        "kind": "sciplot_private_corpus_preflight", "version": 1, "gate": GATE,
        "status": "BLOCKED" if issues else "READY_FOR_SELECTED_TESTS",
        "inventory_complete": inventory["inventory_complete"],
        "collection_verified": collected_nodeids is not None,
        "declared_inputs_status": "present" if declared_present else "blocked",
        "scientific_acceptance": False, "ordinary_runtime_required": False,
        "selected_count": len(selected), "cases": rows, "issues": issues,
    }


def _collect_nodeids(repo_root: Path, inventory_path: Path) -> set[str]:
    if not inventory_path.is_file():
        raise ValueError("source-controlled private-corpus inventory is unavailable; run from a SciPlot source checkout")
    inventory = _load_inventory(inventory_path)
    modules = sorted({case["nodeid"].split("::", 1)[0] for case in inventory["cases"]})
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        (str(repo_root / "src"), str(repo_root / "tests"), env.get("PYTHONPATH", ""))
    )
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *modules],
        cwd=repo_root, env=env, capture_output=True, text=True, check=False,
        timeout=90,
    )
    if completed.returncode != 0:
        raise ValueError(f"pytest collection failed (exit {completed.returncode}): {completed.stderr[-1000:]}")
    return {line for line in completed.stdout.splitlines() if line.startswith("tests/") and "::" in line}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--nodeids-file", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        selected = (args.nodeids_file.read_text(encoding="utf-8").splitlines()
                    if args.nodeids_file else None)
        collected = _collect_nodeids(args.repo_root.resolve(), INVENTORY)
        payload = private_corpus_preflight(
            repo_root=args.repo_root.resolve(), selected_nodeids=selected,
            collected_nodeids=collected,
        )
    except (OSError, UnicodeError, TypeError, ValueError, subprocess.TimeoutExpired) as exc:
        payload = {"kind": "sciplot_private_corpus_preflight", "version": 1,
                   "gate": GATE, "status": "BLOCKED", "inventory_complete": False,
                   "collection_verified": False, "scientific_acceptance": False,
                   "ordinary_runtime_required": False,
                   "issues": [_issue("invalid_input_or_collection", str(exc),
                                      path=args.nodeids_file.name if args.nodeids_file else None)]}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{GATE}: {payload['status']}")
        for issue in payload["issues"]:
            print(f"  {issue.get('path') or issue.get('nodeid') or GATE}: {issue['why']}")
    return 0 if payload["status"] == "READY_FOR_SELECTED_TESTS" else 1


if __name__ == "__main__":
    sys.exit(main())
