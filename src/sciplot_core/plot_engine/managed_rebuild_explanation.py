"""Bounded read-only explanation of a managed revision's observed invalidation.

This is a projection of the existing description, not a scheduler or cache-hit
prediction. In particular, bound graph keys do not validate a future source,
native scientific audit, or publication inventory.
"""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_io import read_json_object

_MAX_NOT_MARKED_IDS = 32


def _native_receipt(binding: dict[str, Any], artifact_status: str) -> str:
    """Check cheap persisted evidence; do not inspect, compile or render native state."""
    native = Path(binding["document"])
    if artifact_status == "missing":
        return "native_missing"
    if artifact_status == "changed":
        # The existing backend fingerprint already assessed the native bytes.
        return "native_changed"
    receipt = read_json_object(native.parent / "build.json")
    if receipt is None:
        return "receipt_unavailable"
    if receipt.get("ir_hash") != binding["ir_hash"]:
        return "receipt_ir_mismatch"
    if not isinstance(receipt.get("document_sha256"), str):
        return "receipt_invalid"
    try:
        from sciplot_core.plot_backends.managed import compiler_identity

        current_identity = compiler_identity()
    except (OSError, ValueError):
        return "renderer_identity_unavailable"
    if receipt.get("compiler_identity") != current_identity:
        return "renderer_identity_mismatch"
    # A byte-sealed receipt is not the native scientific audit performed on use.
    return "byte_sealed_receipt"


def explain_rebuild(result: dict[str, Any], document: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    """Explain *observed* changed inputs and this saved graph's descendants.

    The description has already calculated changed_inputs and invalidated; this
    function never changes those owner decisions or loads raw scientific data.
    """
    changed = set(result["changed_inputs"])
    reasons: list[dict[str, Any]] = []
    claimed: set[str] = set()

    for source in document["scientific"]["data_sources"]:
        path = source["path"]
        if path in changed:
            reasons.append({"code": "source_missing" if not Path(path).is_file() else "source_changed",
                            "input": path, "node": "source:" + source["source_id"]})
            claimed.add(path)

    registry = document["scientific"]["provenance"]["managed"].get("executors", {})
    executor_nodes: dict[str, list[str]] = {}
    for node in document["scientific"]["transforms"]:
        executor = registry.get(node["executor"].get("id"))
        if executor is None:
            continue
        for field in ("script", "executable"):
            path = executor[field]
            if path in changed:
                executor_nodes.setdefault(path, []).append("transform:" + node["id"])
    for path, nodes in sorted(executor_nodes.items()):
        reasons.append({"code": "executor_missing" if not Path(path).is_file() else "executor_changed",
                        "input": path, "nodes": nodes})
        claimed.add(path)

    source_paths = {source["path"] for source in document["scientific"]["data_sources"]}
    external_paths = {executor[field] for executor in registry.values() for field in ("script", "executable")}
    builtin_changes = changed & (set(binding["fingerprint"]["files"]) - source_paths - external_paths)
    for path in sorted(builtin_changes):
        nodes = ["transform:" + node["id"] for node in document["scientific"]["transforms"]
                 if node["executor"]["kind"] == "builtin"]
        if nodes:
            reasons.append({"code": "builtin_executor_missing" if not Path(path).is_file()
                            else "builtin_executor_changed", "input": path, "nodes": nodes})
            claimed.add(path)

    native = binding["document"]
    if result["artifact_status"] == "missing":
        reasons.append({"code": "native_artifact_missing", "node": "render"})
        claimed.add(native)
    elif native in changed:
        reasons.append({"code": "native_artifact_changed", "input": native, "node": "render"})
        claimed.add(native)

    # Internal scientific content references or unknown fingerprint members may
    # be stale without a node mapping. Do not invent affected DAG descendants.
    for path in sorted(changed - claimed):
        reasons.append({"code": "unmapped_input_changed", "input": path})

    receipt = _native_receipt(binding, result["artifact_status"])
    if receipt == "renderer_identity_mismatch":
        # _ensure may replace a byte-sealed product from an older renderer;
        # renderer identity is outside the saved scientific DAG.
        reasons.append({"code": "renderer_identity_mismatch", "evidence": "native_receipt"})

    affected = result["dependencies"]["invalidated"]
    affected_set = set(affected)
    unmapped = any(reason["code"] == "unmapped_input_changed" for reason in reasons)
    not_marked = ([] if unmapped else [node["id"] for node in binding["graph"]["nodes"]
                                      if node["id"] not in affected_set])
    unknown = ["future_cache_reuse_requires_validation"]
    if unmapped:
        unknown.append("unmapped_affected_nodes")
    if any(reason["code"].startswith("source_") or reason["code"] == "unmapped_input_changed"
           for reason in reasons):
        unknown.append("source_content_requires_validation")
    if any(reason["code"].startswith("executor_") or reason["code"].startswith("builtin_executor_")
           for reason in reasons):
        unknown.append("executor_requires_validation")
    if receipt != "byte_sealed_receipt":
        unknown.append("native_receipt_requires_resolution")
    unknown.extend(["native_scientific_audit_on_use", "export_inventory_on_use"])
    return {"basis": "saved_revision_and_observed_inputs", "why_dirty": reasons,
            "affected_nodes": affected, "not_marked_invalid_by_saved_graph": not_marked[:_MAX_NOT_MARKED_IDS],
            "not_marked_invalid_count": None if unmapped else len(not_marked),
            "verified_reused_nodes": [], "native_receipt": receipt, "unknown": unknown}
