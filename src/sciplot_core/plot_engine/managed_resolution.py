"""Journal scientific executor outcomes before native compilation or publication."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.plot_transforms import ExternalExecutor, resolve_transforms

from .content_store import intern_document, resolve_document_content
from .errors import EngineError
from .managed_sources import load_sources
from .managed_state import require_inputs, scientific_binding
from .storage import digest, persist, read, write


def resolve_science(root: Path, document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    document = resolve_document_content(root, document)
    require_inputs(document)
    marker = document["scientific"]["provenance"]["managed"]
    registry = {name: ExternalExecutor.from_dict(value) for name, value in marker.get("executors", {}).items()}
    cache = {}
    cache_root = root / "transform-cache"
    for path in cache_root.glob("*.result.json"):
        record = read(path)
        if record["sha256"] != digest(record["dataset"]):
            raise EngineError("managed_transform_cache_corrupt", "Persisted scientific output no longer matches its content identity.")
        cache[record["key"]] = record["dataset"]

    def before_execute(node: dict[str, Any], key: str) -> None:
        # An external process may have finished before its response was durably
        # adopted. No implicit second invocation is safe in that uncertain window.
        path = cache_root / (key + ".started.json")
        if node["kind"] == "external" and path.exists():
            raise EngineError("external_transform_outcome_unknown", "A prior fixed executor invocation has no durable result; inspect it before a new scientific request.",
                              action="inspect_external_executor", evidence=str(path))
        write(path, {"key": key, "node": node, "status": "started"})

    def on_result(key: str, dataset: dict[str, Any]) -> None:
        path = cache_root / (key + ".result.json")
        record = {"key": key, "dataset": dataset, "sha256": digest(dataset), "status": "complete"}
        if path.exists() and read(path) != record:
            raise EngineError("managed_transform_nondeterministic", "A deterministic executor returned different output for the same sealed request.")
        write(path, record)

    result = resolve_transforms(document, load_sources(document, marker["rule_id"]), cache=cache,
                                external_executors=registry, before_execute=before_execute, on_result=on_result)
    require_inputs(result["document"])
    return intern_document(root, result["document"]), {
        "executed": result["executed"], "reused": result["reused"], "graph": result["graph"]}


def resolve_transaction(root: Path, tx: dict[str, Any]) -> None:
    resolved, evidence = resolve_science(root, tx["document"])
    tx["document"] = resolved
    tx["binding"] = scientific_binding(tx["binding"], resolved)
    tx["resolution"] = evidence
    tx["phase"] = "planned"
    persist(root, tx)


def resolved_metadata(document: dict[str, Any], *, rule_id: str,
                      executors: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.plot_document import seal_document

    result = deepcopy(document)
    marker = result["scientific"]["provenance"]["managed"]
    marker.update({"rule_id": rule_id, "executors": deepcopy(executors)})
    used = {node["executor"]["id"] for node in result["scientific"]["transforms"] if node["kind"] == "external"}
    if set(executors) != used:
        raise EngineError("managed_executor_membership", "Register exactly the fixed executors used by this plot's transform closure.")
    for identifier, value in executors.items():
        executor = ExternalExecutor.from_dict(value)
        if executor.descriptor(identifier) != value["identity"]:
            raise EngineError("managed_executor_identity", "Executor resource keys must match their declared stable identity.")
    return seal_document(result)
