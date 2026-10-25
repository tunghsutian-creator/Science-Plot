"""Canonical managed snapshots and exact per-plot scientific input closure."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.plot_document import validate_document
from sciplot_core.plot_document.errors import DocumentError
from sciplot_core.plot_transforms import builtin_files, require_builtin

from .content_store import referenced_files, resolve_document_content
from .errors import EngineError
from .managed_source_groups import add_input
from .storage import digest, read, write
from sciplot_core.project_lifecycle.context import exists


def is_managed(document: dict[str, Any]) -> bool:
    return document.get("plot_type") == "ManagedPlot"


def input_files(document: dict[str, Any]) -> dict[str, str]:
    files: dict[str, str] = {}
    for source in document["scientific"]["data_sources"]:
        add_input(files, source["path"], source["sha256"])
    registry = document["scientific"]["provenance"]["managed"].get("executors", {})
    for executor in registry.values():
        add_input(files, executor["executable"], executor["identity"]["executable_sha256"])
        add_input(files, executor["script"], executor["identity"]["script_sha256"])
    builtins = [node for node in document["scientific"]["transforms"] if node["executor"]["kind"] == "builtin"]
    for node in builtins:
        try:
            require_builtin(node)
            implementation = builtin_files(node["kind"], node["executor"])
        except (OSError, DocumentError) as exc:
            changed = getattr(exc, "reason_code", None) == "transform_runtime_changed"
            raise EngineError("managed_builtin_executor_changed" if changed else "managed_builtin_executor_unavailable",
                              "Restore the saved immutable builtin version before scientific reconstruction.",
                              action="restore_builtin_executor", targets=["transform:" + node["id"]],
                              automatic_refresh=False, automatic_retry=False) from exc
        for path, sha256 in implementation.items():
            add_input(files, path, sha256)
    return files


def require_inputs(document: dict[str, Any]) -> None:
    changed = [path for path, sha in input_files(document).items()
               if existing_file_sha256(source_input_path(document, path, sha)) != sha]
    if changed:
        raise EngineError("managed_inputs_changed", "Only explicitly bound current scientific inputs may be compiled.",
                          action="refresh_scientific_binding", changed=changed)


def source_input_path(document: dict[str, Any], path: str, sha256: str) -> Path:
    """Resolve source IO only; implementation and executor pins stay host paths."""
    matching = [source for source in document["scientific"]["data_sources"] if source["path"] == path]
    if not matching:
        return Path(path)
    locations = {resolve_source_path(path, expected_sha256=sha256, source_id=source["source_id"]) for source in matching}
    if len(locations) != 1:
        raise EngineError("managed_source_locator_conflict", "One sealed original file cannot resolve to conflicting physical versions.")
    return next(iter(locations))


def resolved_ir(root: Path, document: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.plot_ir import compile_document

    expanded = resolve_document_content(root, document)
    datasets = expanded["scientific"]["provenance"]["datasets"]
    from sciplot_core.project_lifecycle.context import capability_profile

    return compile_document(document, datasets, capabilities=capability_profile())


def make_binding(root: Path, document: dict[str, Any], *, output: Path) -> dict[str, Any]:
    from sciplot_core.plot_transforms.graph import dependency_graph

    document = validate_document(document)
    if not is_managed(document):
        raise EngineError("managed_authority_required", "Only an explicit ManagedPlot can own disposable backend artifacts.")
    require_inputs(document)
    expanded = resolve_document_content(root, document)
    ir = resolved_ir(root, document)
    model_path = root / "models" / (digest(document) + ".json")
    ir_path = root / "ir" / (ir["ir_hash"] + ".json")
    for path, value in ((model_path, document), (ir_path, ir)):
        if exists(path) and read(path) != value:
            raise EngineError("managed_state_corrupt", "An immutable managed state file changed.")
        if not exists(path):
            write(path, value)
    native = output / "artifacts" / ir["ir_hash"] / "document.vsz"
    files = input_files(document)
    return {"kind": "sciplot_managed_binding", "version": 1, "root": str(root), "output": str(output),
            "canonical_document": str(model_path), "canonical_sha256": digest(document),
            "ir_path": str(ir_path), "ir_hash": ir["ir_hash"], "document": str(native),
            "scientific_content_files": referenced_files(root, document),
            "fingerprint": {"files": files, "artifacts": {str(native): ir["ir_hash"]}},
            "graph": dependency_graph(document, expanded["scientific"]["provenance"]["datasets"])}


def read_canonical(binding: dict[str, Any]) -> dict[str, Any]:
    document = validate_document(read(Path(binding["canonical_document"])))
    if digest(document) != binding["canonical_sha256"]:
        raise EngineError("managed_state_corrupt", "The canonical document no longer matches its bound immutable identity.")
    return document


def scientific_binding(binding: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    """Update acknowledged scientific guards while retaining the old native baseline."""
    result = deepcopy(binding)
    result["fingerprint"]["files"] = input_files(document)
    return result
