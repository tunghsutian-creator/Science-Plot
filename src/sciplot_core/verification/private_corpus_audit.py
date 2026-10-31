"""Bind a full collection/source review to a local private-access audit.

Completeness is earned for the current collection and source bytes. It is not
scientific acceptance, and a static review or a successful subset cannot earn it.
The access receipt is development evidence and must remain local-only.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from sciplot_core._paths import local_reference_root, resolve_fixture_path
from sciplot_core.verification.private_capture import review_capture
from sciplot_core.verification.private_access import access_events, file_parent_open


def nodeids_sha256(nodeids: set[str] | list[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(nodeids)) + "\n").encode()).hexdigest()


def test_sources_sha256(repo_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((repo_root / "tests").rglob("*.py")):
        relative = path.relative_to(repo_root).as_posix()
        content = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(relative.encode() + b"\0" + content.encode() + b"\n")
    return digest.hexdigest()


def implementation_sources_sha256(repo_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((repo_root / "src").rglob("*.py")):
        relative = path.relative_to(repo_root).as_posix()
        content = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(relative.encode() + b"\0" + content.encode() + b"\n")
    return digest.hexdigest()


def _validate_collection_events(
    events: object, *, repo_root: Path, fixture_roots: dict[Path, str | None] | None,
) -> None:
    """Keep collector directory enumeration separate from bound test accesses."""
    if not isinstance(events, list):
        raise ValueError("collection_events must be a list")
    for event in events:
        if (not isinstance(event, dict)
                or event.get("classification") != "collector-directory-enumeration"
                or event.get("event") not in {"os.scandir", "os.listdir"}
                or event.get("nodeid") != "" or not isinstance(event.get("path"), str)):
            raise ValueError("collection events may only record unbound collector directory enumeration")
        path = Path(event["path"])
        prefix = Path(*path.parts[:3])
        if (path.is_absolute() or ".." in path.parts or fixture_roots is None
                or prefix not in fixture_roots):
            raise ValueError("collector directory escapes the allowed fixture namespaces")
        resolved = resolve_fixture_path(path, repo_root=repo_root)
        roots = [(repo_root / prefix).resolve()]
        local_name = fixture_roots[prefix]
        if local_name is not None:
            roots.append((local_reference_root(repo_root=repo_root) / local_name).resolve())
        if not resolved.is_dir() or not any(resolved.is_relative_to(root) for root in roots):
            raise ValueError("collector directory is missing or resolves outside its fixture namespace")


def _validate_supported_streams(receipt: dict[str, Any], *, repo_root: Path,
                                nodeids: set[str], fixture_roots: dict[Path, str | None] | None) -> None:
    proof = receipt.get("capture_proof")
    if not isinstance(proof, dict):
        raise ValueError("supported raw capture proof is absent")
    from sciplot_core.verification.private_process_boundaries import root_scope, watch_roots

    if proof.get("expected_root_scope") != root_scope(watch_roots(repo_root, dict(os.environ))):
        raise ValueError("raw capture roots do not cover the current fixture and reference namespaces")
    result = review_capture(proof, expected_nodeids=nodeids)
    if not result["capture_complete"]:
        raise ValueError("supported raw capture is incomplete: " + "; ".join(result["issues"][:3]))
    aliases = []
    for prefix, local_name in (fixture_roots or {}).items():
        aliases.append(((repo_root / prefix).resolve(), prefix))
        if local_name is not None:
            aliases.append(((local_reference_root(repo_root=repo_root) / local_name).resolve(), prefix))
    raw_events, raw_collection = access_events(result, aliases)
    def normalize(rows: list[dict[str, Any]]) -> list[str]:
        return sorted(json.dumps(row, sort_keys=True) for row in rows)
    if (normalize(raw_events) != normalize(receipt.get("events", []))
            or normalize(raw_collection) != normalize(receipt.get("collection_events", []))):
        raise ValueError("receipt access or collection events differ from original raw streams")


def validate_access_audit(
    *, inventory: dict[str, Any], inventory_path: Path, repo_root: Path,
    collected_nodeids: set[str] | None,
    dependencies: dict[str, list[tuple[str, str]]], access_audit_path: Path | None,
    fixture_roots: dict[Path, str | None] | None = None,
) -> tuple[bool, list[tuple[str, str, str | None]]]:
    """Fail closed on incomplete execution, stale review, or unmapped access."""
    issues: list[tuple[str, str, str | None]] = []
    review = inventory.get("collection_audit")
    if not isinstance(review, dict) or review.get("static_review_complete") is not True:
        return False, [("static_audit_incomplete", "full collection/static dependency review is absent", None)]
    candidates = review.get("candidate_nodeids")
    synthetic = review.get("synthetic_candidates")
    declared = {case["nodeid"] for case in inventory["cases"]}
    if (not isinstance(candidates, list) or not all(isinstance(name, str) for name in candidates)
            or len(set(candidates)) != len(candidates) or not isinstance(synthetic, list)
            or not all(isinstance(row, dict) and isinstance(row.get("nodeid"), str)
                       and isinstance(row.get("reason"), str) and row["reason"] for row in synthetic)):
        return False, [("static_audit_incomplete", "candidate dispositions are missing or malformed", None)]
    excluded = {row["nodeid"] for row in synthetic}
    if (len(excluded) != len(synthetic) or declared & excluded
            or set(candidates) != declared | excluded
            or collected_nodeids is None or not set(candidates) <= collected_nodeids):
        return False, [("static_audit_incomplete", "every candidate needs one exact private or synthetic disposition", None)]
    if (collected_nodeids is None or review.get("nodeid_count") != len(collected_nodeids)
            or review.get("nodeids_sha256") != nodeids_sha256(collected_nodeids)
            or review.get("test_sources_sha256") != test_sources_sha256(repo_root)):
        return False, [("stale_static_audit", "collection or test/helper source bytes changed after review", None)]
    if access_audit_path is None:
        return False, [("access_audit_required", "full current-suite private-access receipt is required", None)]
    try:
        receipt = json.loads(access_audit_path.read_text(encoding="utf-8"))
        if (not isinstance(receipt, dict)
                or receipt.get("kind") != "sciplot_private_corpus_access_audit"
                or receipt.get("version") not in {1, 2}):
            raise ValueError("unknown private-access receipt schema")
        if receipt["version"] == 1:
            raise ValueError("legacy access receipt is diagnostic only; supported raw capture proof is required")
        if (receipt.get("inventory_sha256") != hashlib.sha256(inventory_path.read_bytes()).hexdigest()
                or receipt.get("test_sources_sha256") != review["test_sources_sha256"]
                or receipt.get("implementation_sources_sha256") != implementation_sources_sha256(repo_root)):
            raise ValueError("receipt is not bound to the current inventory/test source bytes")
        if receipt.get("capture_scope") != [
            "python.open", "python.os.scandir", "python.os.listdir", "static.fixture_dependencies",
        ]:
            raise ValueError("receipt must state its bounded Python access and static native-dependency scope")
        collected = receipt.get("collected_nodeids")
        executed = receipt.get("executed_nodeids")
        for names in (collected, executed):
            if (not isinstance(names, list) or not all(isinstance(name, str) for name in names)
                    or len(set(names)) != len(names) or set(names) != collected_nodeids):
                raise ValueError("receipt must collect and attempt every current node exactly once")
        if receipt.get("capture_complete") is not True:
            raise ValueError("private-access capture was not confirmed complete, including child processes")
        _validate_collection_events(
            receipt.get("collection_events", []), repo_root=repo_root, fixture_roots=fixture_roots,
        )
        events = receipt.get("events")
        if not isinstance(events, list):
            raise ValueError("receipt events must be a list")
        for event in events:
            if (not isinstance(event, dict) or event.get("event") not in {"open", "os.scandir", "os.listdir"}
                    or not isinstance(event.get("path"), str) or not isinstance(event.get("nodeid"), str)):
                raise ValueError("malformed private-access event")
            path = Path(event["path"])
            nodeid = event["nodeid"]
            if path.is_absolute() or ".." in path.parts or path.parts[:2] != ("tests", "fixtures"):
                raise ValueError("private-access event paths must be safe fixture-relative identifiers")
            if nodeid not in collected_nodeids:
                issues.append(("unbound_private_access", "private access is not bound to a collected test", nodeid))
                continue
            facts = event.get("open")
            raw = facts.get("raw") if isinstance(facts, dict) else None
            if isinstance(raw, dict) and raw.get("path") != raw.get("resolved_path"):
                issues.append(("unmapped_private_access", "private open uses an alias instead of its declared source", nodeid))
                continue
            case_dependencies = dependencies.get(nodeid, [])
            if not (any(
                path == Path(identifier)
                or (kind == "directory" and path.is_relative_to(Path(identifier)))
                for identifier, kind in case_dependencies
            ) or file_parent_open(event, case_dependencies)):
                issues.append(("unmapped_private_access", f"undeclared private access: {path.as_posix()}", nodeid))
        if not issues:
            _validate_supported_streams(receipt, repo_root=repo_root, nodeids=collected_nodeids,
                                        fixture_roots=fixture_roots)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        issues.append(("invalid_access_audit", str(exc), None))
    return not issues, issues
