"""Bind a full collection/source review to a local private-access audit.

Completeness is earned for the current collection and source bytes. It is not
scientific acceptance, and a static review or a successful subset cannot earn it.
The access receipt is development evidence and must remain local-only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


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


def validate_access_audit(
    *, inventory: dict[str, Any], inventory_path: Path, repo_root: Path,
    collected_nodeids: set[str] | None,
    dependencies: dict[str, list[tuple[str, str]]], access_audit_path: Path | None,
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
                or receipt.get("version") != 1):
            raise ValueError("unknown private-access receipt schema")
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
            if not any(
                path == Path(identifier)
                or (kind == "directory" and path.is_relative_to(Path(identifier)))
                for identifier, kind in dependencies.get(nodeid, [])
            ):
                issues.append(("unmapped_private_access", f"undeclared private access: {path.as_posix()}", nodeid))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        issues.append(("invalid_access_audit", str(exc), None))
    return not issues, issues
