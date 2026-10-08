"""Exact byte currentness and compact dependency invalidation without a renderer."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.delivery.filesystem_metadata import is_delivery_finder_metadata
from sciplot_core.plot_document import build_keys, invalidated_nodes
from sciplot_core.studio_core.source_update_commit import file_inventory

from .backend import PlotBackend
from .errors import EngineError
from .storage import digest


def changed_inputs(backend: PlotBackend, binding: dict[str, Any]) -> list[str]:
    expected = {**binding["fingerprint"], "scientific_content": binding.get("scientific_content_files", {})}
    actual = {**backend.fingerprint(binding), "scientific_content": {
        path: existing_file_sha256(Path(path)) for path in binding.get("scientific_content_files", {})}}
    changed: list[str] = []
    for group in set(expected) | set(actual):
        before, after = expected.get(group, {}), actual.get(group, {})
        changed.extend(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    return sorted(set(changed))


def require_current(backend: PlotBackend, binding: dict[str, Any]) -> None:
    changed = changed_inputs(backend, binding)
    if changed:
        raise EngineError("document_inputs_changed", "Source or saved native inputs changed; this revision is no longer current.",
                          action="resolve_input_conflict", changed=changed[:16],
                          changed_count=len(changed), invalidated=["compile", "render", "export"])


def dependency_state(document: dict[str, Any], binding: dict[str, Any], changed: list[str]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    changed_ids: list[str] = []
    inputs = {**binding["fingerprint"], "scientific_content": binding.get("scientific_content_files", {})}
    for group, files in inputs.items():
        for path, sha in files.items():
            identifier = "input:" + digest([group, path])[:16]
            nodes.append({"id": identifier, "kind": "source", "dependencies": [], "parameters": {"path": path},
                          "version": "1", "content_hash": sha or digest(None)})
            if path in changed:
                changed_ids.append(identifier)
    input_ids = [node["id"] for node in nodes]
    nodes.extend([
        {"id": "compile", "kind": "compile", "dependencies": input_ids, "version": "1",
         "parameters": {"scientific_hash": document["scientific_hash"], "presentation_hash": document["presentation_hash"]}},
        {"id": "render", "kind": "render", "dependencies": ["compile"], "version": "1", "parameters": {}},
        {"id": "export", "kind": "export", "dependencies": ["render"], "version": "1",
         "parameters": document["presentation"]["export_configuration"]},
    ])
    graph = {"kind": "sciplot_dependency_graph", "schema_version": 1, "nodes": nodes}
    return {"build_keys": build_keys(graph), "invalidated": invalidated_nodes(graph, changed_ids)}


def artifact_files(payload: Any) -> dict[str, str]:
    """Collect output file byte seals, never confuse input build keys with byte hashes."""
    found: dict[str, str] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "path" and isinstance(value, str):
                path = Path(value)
                if path.is_absolute() and path.is_file():
                    sha = existing_file_sha256(path)
                    if sha is not None:
                        found[value] = sha
            elif isinstance(value, (dict, list)):
                found.update(artifact_files(value))
    elif isinstance(payload, list):
        for value in payload:
            found.update(artifact_files(value))
    return found


def evidence_current(files: dict[str, str], inventories: dict[str, list[str]] | None = None) -> bool:
    """Verify bytes and exact inventory; newly added visible data invalidates a cache."""
    if not files:
        return False
    checked: set[str] = set()
    try:
        for name, expected in (inventories or {}).items():
            root = Path(name)
            if not root.is_absolute():
                return False
            actual = {name: sha for name, sha in file_inventory(root).items()
                      if not is_delivery_finder_metadata(root / name)}
            if sorted(actual) != expected:
                return False
            for relative, sha in actual.items():
                path = str(root / relative)
                if files.get(path) != sha:
                    return False
                checked.add(path)
        return all(Path(path).is_absolute() and isinstance(sha, str)
                   and existing_file_sha256(Path(path)) == sha for path, sha in files.items() if path not in checked)
    except (OSError, ValueError):
        return False
