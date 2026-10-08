"""Explicit managed scientific updates and ordinary semantic patches share one wire contract."""

from copy import deepcopy
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_document import apply_patch, seal_document, validate_patch
from sciplot_core.plot_document.errors import fail

from .errors import EngineError

SPECIAL = {"theme", "source.sha256", "transform.parameters", "transform.executor", "executor.registration"}


def prepare_update(document: dict[str, Any], request: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str, bool]:
    request = validate_patch(request)
    if request["plot_id"] != document["plot_id"] or request["base_revision"] != document["revision"]:
        raise EngineError("document_revision_conflict", "The managed patch must identify the current plot and revision.",
                          current_revision=document["revision"])
    from sciplot_core.plot_ir.figure_document import is_figure
    from .figure_updates import PROPERTIES, prepare_figure_update

    if is_figure(document) and any(change["property"] in PROPERTIES for change in request["changes"]):
        return prepare_figure_update(document, request)
    if not any(change["property"] in SPECIAL for change in request["changes"]):
        updated, diff, risk = apply_patch(document, request)
        return updated, diff, risk, False
    if any(change["property"] not in SPECIAL for change in request["changes"]):
        raise EngineError("managed_mixed_update", "Keep a scientific/theme update separate from ordinary object style changes.")
    result = deepcopy(document)
    if any(change["property"] == "theme" for change in request["changes"]) and any(
        change["property"] != "theme" for change in request["changes"]
    ):
        raise EngineError("managed_mixed_update", "Keep theme changes separate from scientific source/executor updates.")
    diff = []
    touched: set[tuple[str, str]] = set()
    science = False
    for change in request["changes"]:
        if len(change["target"]) != 1:
            raise EngineError("managed_update_target", "Each scientific or theme update names exactly one stable target.")
        target, prop, value = change["target"][0], change["property"], change["value"]
        if (target, prop) in touched:
            raise EngineError("document_duplicate_change", "Set each managed target/property once per transaction.")
        touched.add((target, prop))
        if prop == "theme":
            if target != "figure:main":
                raise EngineError("managed_update_target", "A whole-figure theme names figure:main.")
            from sciplot_core.plot_ir import apply_theme

            before = deepcopy(result["presentation"])
            result = apply_theme(result, value)
            after = deepcopy(result["presentation"])
        else:
            if request["intent_class"] != "scientific":
                fail("document_scientific_edit_unsupported", "Source and transform updates require explicit scientific intent.",
                     "/intent_class", "scientific_intent")
            science = True
            before = _scientific(result, target, prop, value)
            after = deepcopy(value)
        if canonical_json_sha256(before, allow_nan=False) != canonical_json_sha256(after, allow_nan=False):
            diff.append({"target": target, "property": prop, "before": before,
                         "after": after, "risk": "scientific" if science else "presentation"})
    result = seal_document(result)
    if not diff and any(result[field] != document[field] for field in ("scientific_hash", "presentation_hash")):
        raise EngineError("managed_update_unreported_change", "A no-op update cannot alter a canonical domain hash.")
    return result, diff, "scientific" if science else "presentation", science


def _scientific(document: dict[str, Any], target: str, prop: str, value: Any) -> Any:
    scientific = document["scientific"]
    if prop == "source.sha256":
        from sciplot_core.plot_document.schema import DIGEST
        from sciplot_core.plot_document.validation import validate_wire

        validate_wire(value, DIGEST, code="managed_source_hash_invalid")
        source = next((item for item in scientific["data_sources"] if target == "source:" + item["source_id"]), None)
        if source is None:
            raise EngineError("document_unknown_target", "Name an existing source:<source_id>.")
        before, source["sha256"] = source["sha256"], value
        return before
    if prop in {"transform.parameters", "transform.executor"}:
        from sciplot_core.plot_transforms import builtin_executor, validate_node

        node = next((item for item in scientific["transforms"] if target == "transform:" + item["id"]), None)
        if node is None:
            raise EngineError("document_unknown_target", "Name an existing transform:<transform_id>.")
        field = "parameters" if prop == "transform.parameters" else "executor"
        if prop == "transform.executor" and (node["executor"]["kind"] != "builtin" or value != builtin_executor()):
            raise EngineError("managed_builtin_executor_identity", "Bind exactly the current builtin executor descriptor; external executors use executor.registration.")
        before, node[field] = deepcopy(node[field]), deepcopy(value)
        validate_node(node)
        return before
    if prop == "executor.registration":
        from sciplot_core.plot_transforms import ExternalExecutor

        registry = scientific["provenance"]["managed"].get("executors", {})
        identifier = target.removeprefix("executor:")
        if target != "executor:" + identifier or identifier not in registry:
            raise EngineError("document_unknown_target", "Name an existing executor:<executor_id>.")
        executor = ExternalExecutor.from_dict(value)
        if executor.descriptor(identifier) != value["identity"]:
            raise EngineError("managed_executor_identity", "The new executor definition must retain its stable executor ID.")
        before, registry[identifier] = deepcopy(registry[identifier]), deepcopy(value)
        for node in scientific["transforms"]:
            if node["executor"].get("id") == identifier:
                node["executor"] = deepcopy(value["identity"])
        return before
    raise EngineError("managed_update_unsupported", "This managed scientific update is not supported.")
