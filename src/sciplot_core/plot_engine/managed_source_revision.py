"""Explicit whole-file source reconfirmation through the existing SHA edit."""

from copy import deepcopy
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.mapping_contract.table_metadata import metadata_confirmations_schema
from sciplot_core.plot_document.schema import DIGEST, closed
from sciplot_core.plot_document.templates import binding_schema
from sciplot_core.plot_document.validation import validate_wire

from .content_store import resolve_provenance_value
from .errors import EngineError
from .managed_source_groups import physical_path, source_groups
from .original_coordinate import _region_matches, coordinate_origins


def source_group(document: dict[str, Any], target: str) -> tuple[str, list[dict[str, Any]]]:
    for path, sources in source_groups(document).items():
        if any(target == "source:" + source["source_id"] for source in sources):
            return path, sources
    raise EngineError("document_unknown_target", "Name an existing source:<source_id>.")


def _binding(document: dict[str, Any], root: Path | None) -> dict[str, Any]:
    value = document["scientific"]["provenance"].get("binding", {})
    if value.get("kind") == "sciplot_content_reference":
        if root is None:
            raise EngineError("managed_source_context_unavailable", "Reconfirming a stored source context requires its plot root.")
        value = resolve_provenance_value(root, document, "binding")
    result: dict[str, Any] = value
    return result


def _contexts(binding: dict[str, Any], path: str) -> list[dict[str, Any]]:
    return [item for item in binding.get("semantic_task", {}).get("resolution", {}).get("bindings", [])
            if physical_path(item["source_path"]) == physical_path(path)]


def _frozen_schema(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return closed({key: DIGEST if key == "source_sha256" else _frozen_schema(item) for key, item in value.items()})
    return {"const": value}


def _context_schema(condition: dict[str, Any]) -> dict[str, Any]:
    """The expert owner's existing literal coordinate/context shape, not a new fact type."""
    text = {"type": "string", "minLength": 1, "maxLength": 4096}
    quantity = {"type": ["string", "null"]}
    proof = closed({"version": {"const": 1}, "quantity": text, "observed_quantity": quantity,
                    "source_header": text, "explicit_quantity_binding": {"type": "boolean"}})
    relation = closed({**{key: text for key in ("from_unit", "to_unit", "canonical_from_unit", "canonical_to_unit")},
                       "factor": {"type": "number"}, "offset": {"type": "number"},
                       "authority": {"const": "materials_rules.unit_conversion"}, "kind": {"enum": ["identity", "conversion"]}})
    coordinate = closed({"column_id": {"type": "string", "pattern": "^column:[0-9]+$"},
        "column_index": {"type": "integer", "minimum": 0}, "header": text, "quantity": text,
        "observed_quantity": quantity, "observed_unit": {"type": "string"}, "source_unit": text,
        "unit": text, "unit_relation": relation, "unit_context": proof})
    derived = closed({"quantity": {"const": "complex_viscosity"}, "unit": text,
        "derivation": closed({"quantity": {"const": "complex_viscosity"}, "unit": text,
            "method": {"const": "derived_from_storage_and_loss_modulus"},
            "formula": {"const": "hypot(storage_modulus, loss_modulus) / angular_frequency"},
            "inputs": closed({name: coordinate for name in ("angular_frequency", "storage_modulus", "loss_modulus")})})})
    region = binding_schema()["properties"]["data_sources"]["items"]["properties"]["table_selection"]
    return closed({"source_path": {"type": "string", "pattern": "^/"}, "source_sha256": DIGEST,
        "table_id": text, "block_id": text, "table_selection": region,
        "quantities": closed({"x": text, "y": text}), "condition": {"const": condition},
        "coordinates": {**closed({role: {"oneOf": [coordinate, derived]} for role in ("x", "y", "temperature")}, []), "minProperties": 1}})


def source_value(document: dict[str, Any], target: str, *, root: Path | None = None) -> dict[str, Any]:
    path, sources = source_group(document, target)
    hashes = {source["sha256"] for source in sources}
    if len(hashes) != 1:
        _reject(target, "The source group already has conflicting expected hashes.")
    return {"sha256": sources[0]["sha256"],
            "bindings": {source["source_id"]: {"metadata_confirmations": deepcopy(source.get("metadata_confirmations", []))}
                         for source in sources},
            "unit_context_bindings": deepcopy(_contexts(_binding(document, root), path))}


def source_descriptor(document: dict[str, Any], target: str, *, root: Path | None = None) -> dict[str, Any]:
    current = source_value(document, target, root=root)
    schemas = [_frozen_schema(item) for item in current["unit_context_bindings"]]
    # New explicit selector context is accepted in the owner's existing shape;
    # fresh original facts and the unchanged graph are still checked at admission.
    schemas.append(_context_schema({}))
    schemas.extend(_context_schema(item["condition"]) for item in current["unit_context_bindings"] if item.get("condition"))
    contexts = {"type": "array", "minItems": len(current["unit_context_bindings"]),
                "maxItems": len(current["unit_context_bindings"]) or 256,
                "uniqueItems": True, "items": {"anyOf": schemas}}
    complete = closed({"sha256": DIGEST, "bindings": closed({identifier: closed({
        "metadata_confirmations": metadata_confirmations_schema()}) for identifier in current["bindings"]}),
        "unit_context_bindings": contexts})
    return {"value_schema": {"oneOf": [{**DIGEST, "description": "A current-SHA no-op or a single source without existing confirmations/context; otherwise submit the complete group."}, complete]}, "risk": "scientific"}


def _reject(target: str, message: str) -> NoReturn:
    raise EngineError("managed_source_reconfirmation_required", message, action="plot.describe",
                      description={"scope": "edit", "target": target, "property": "source.sha256"},
                      target=target, property="source.sha256",
                      retry="same_unreserved_idempotency_key")


def _normalized(value: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.foundation.json_hashing import canonical_json_sha256

    result = deepcopy(value)
    for entry in result["bindings"].values():
        entry["metadata_confirmations"].sort(key=canonical_json_sha256)
    result["unit_context_bindings"].sort(key=canonical_json_sha256)
    return result


def _comparable(value: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(value)
    for binding in result["unit_context_bindings"]:
        binding["source_path"] = physical_path(binding["source_path"])
    return _normalized(result)


def _selector(binding: dict[str, Any]) -> dict[str, Any]:
    def coordinate(item: dict[str, Any], *, original: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {key: item[key] for key in ("quantity", "column_id", "column_index") if key in item}
        if not original:
            result["unit"] = item["unit"]
        if "derivation" in item:
            derived = item["derivation"]
            result["derivation"] = {key: derived[key] for key in ("quantity", "method", "formula")}
            result["derivation"]["inputs"] = {role: coordinate(leaf, original=True) for role, leaf in derived["inputs"].items()}
        return result

    return {**{key: binding[key] for key in ("table_id", "block_id", "table_selection", "quantities")},
            "source_path": physical_path(binding["source_path"]),
            "coordinates": {role: coordinate(item) for role, item in binding["coordinates"].items()}}


def prepare_source_revision(document: dict[str, Any], target: str, value: Any, *,
                            root: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mutate only the isolated candidate, after validating the complete group."""
    path, sources = source_group(document, target)
    before = source_value(document, target, root=root)
    validate_wire(value, source_descriptor(document, target, root=root)["value_schema"], code="managed_source_hash_invalid")
    if isinstance(value, str):
        if value == before["sha256"]:
            return before, deepcopy(before)
        if len(sources) != 1 or any(item["metadata_confirmations"] for item in before["bindings"].values()) or before["unit_context_bindings"]:
            _reject(target, "Submit the complete current source group and freshly confirmed metadata/context with the new SHA.")
        after = {**deepcopy(before), "sha256": value}
    else:
        after = deepcopy(value)
    sha = after["sha256"]
    if before["unit_context_bindings"]:
        from sciplot_core.foundation.json_hashing import canonical_json_sha256

        old_selectors = sorted(canonical_json_sha256(_selector(item)) for item in before["unit_context_bindings"])
        new_selectors = sorted(canonical_json_sha256(_selector(item)) for item in after["unit_context_bindings"])
        if old_selectors != new_selectors:
            _reject(target, "Reconfirm every existing source-bound block, coordinate and derivation input; source refresh cannot delete or remap its scientific facts.")
    for entry in after["bindings"].values():
        if any(item["source_sha256"] != sha for item in entry["metadata_confirmations"]):
            _reject(target, "Every submitted metadata confirmation must explicitly name the new SHA.")
    binding = _binding(document, root)
    semantic = binding.get("semantic_task", {})
    for item in after["unit_context_bindings"]:
        if (item["source_sha256"] != sha or physical_path(item["source_path"]) != path
                or not any(physical_path(item["source_path"]) == physical_path(source["path"])
                           and _region_matches(source, item, semantic) for source in sources)):
            _reject(target, "Every submitted unit context must name this new SHA and an existing exact source region.")
        for coordinate in item["coordinates"].values():
            if "derivation" in coordinate:
                continue  # Historical derived descriptors remain unchanged; the owner never uses them as a raw context.
            if coordinate["column_id"] != "column:" + str(coordinate["column_index"]):
                _reject(target, "Unit context must preserve its exact physical column selector.")
    before, after = _normalized(before), _normalized(after)
    comparable_before, comparable_after = _comparable(before), _comparable(after)
    if comparable_after == comparable_before:
        return comparable_before, comparable_after
    for source in sources:
        source["sha256"] = sha
        metadata = after["bindings"][source["source_id"]]["metadata_confirmations"]
        if metadata != source.get("metadata_confirmations", []):
            source["metadata_confirmations"] = deepcopy(metadata)
    if after["unit_context_bindings"] != before["unit_context_bindings"]:
        binding = deepcopy(binding)
        semantic = binding.setdefault("semantic_task", {})
        resolution = semantic.setdefault("resolution", {})
        resolution["bindings"] = [item for item in resolution.get("bindings", [])
                                  if physical_path(item["source_path"]) != path] + deepcopy(after["unit_context_bindings"])
        document["scientific"]["provenance"]["binding"] = binding
    return comparable_before, comparable_after


def validate_reconfirmed_contexts(document: dict[str, Any], previous: dict[str, Any], *,
                                  datasets: dict[str, dict[str, Any]], column_facts: dict[str, dict[str, Any]],
                                  source_frames: dict[str, Any] | None = None,
                                  root: Path | None = None) -> None:
    """Compare new explicit facts with the admission owner's one fresh table read."""
    from sciplot_core.plot_ir.figure_document import figure_spec, is_figure
    from sciplot_core.plot_transforms.unit_relations import resolve_unit_relation
    from sciplot_core.source_inspection.semantic_evidence import _quantity
    from .source_context_observation import literal_coordinates, mapped_derivations, observe_binding, require_derivation_origins, validate_stage_intervals

    old = {source["source_id"]: source for source in previous["scientific"]["data_sources"]}
    old_binding = _binding(previous, root)
    current_binding = document["scientific"]["provenance"].get("binding", {})
    changed = {source["source_id"]: source for source in document["scientific"]["data_sources"]
               if source["source_id"] in old and any(source.get(key) != old[source["source_id"]].get(key)
                                                     for key in ("path", "sha256", "table_selection", "metadata_confirmations"))}
    for source in document["scientific"]["data_sources"]:
        path = physical_path(source["path"])
        if _normalized_contexts(old_binding, path) != _normalized_contexts(current_binding, path):
            changed[source["source_id"]] = source
    if document["scientific"]["transforms"] != previous["scientific"]["transforms"]:
        derived_paths = {physical_path(item["source_path"])
                         for item in current_binding.get("semantic_task", {}).get("resolution", {}).get("bindings", [])
                         if any("derivation" in coordinate for coordinate in item["coordinates"].values())}
        changed.update({source["source_id"]: source for source in document["scientific"]["data_sources"]
                        if physical_path(source["path"]) in derived_paths})
    if not changed:
        return
    binding = document["scientific"]["provenance"].get("binding", {})
    semantic = binding.get("semantic_task", {})
    contexts = [item for item in semantic.get("resolution", {}).get("bindings", [])
                if any(physical_path(source["path"]) == physical_path(item["source_path"]) and _region_matches(source, item, semantic)
                       for source in changed.values())]
    if not contexts:
        return
    semantics = {layer["id"]: layer["mapping_semantics"] for view in figure_spec(document)["views"]
                 for layer in view["layers"]} if is_figure(document) else {}
    allowed: set[tuple[str, str, str, str]] = set()
    derivations = []
    for identifier, mapping in document["scientific"]["mappings"].items():
        for axis in ("x", "y"):
            quantity = semantics.get(identifier, {}).get(axis)
            if quantity is None:
                continue
            coordinate = mapping[axis]
            column = "column:" + str(coordinate["column_index"]) if "column_index" in coordinate else coordinate["column"]
            derived = mapped_derivations(document, coordinate["source_id"], column)
            if derived:
                if quantity != "complex_viscosity":
                    _reject("source:" + next(iter(changed)), "The typed derivation cannot replace the public mapping quantity.")
                derivations.extend(derived)
                continue
            for source, index, _start, _end, _context, _operations in coordinate_origins(
                    document, coordinate["source_id"], column, mapping[axis + "_unit"], quantity=quantity,
                    datasets=datasets, column_facts=column_facts, binding_sources=set()):
                allowed.add((source["source_id"], "column:" + str(index), quantity, mapping[axis + "_unit"]))
    for item in contexts:
        members = [source for source in changed.values() if physical_path(source["path"]) == physical_path(item["source_path"])
                   and _region_matches(source, item, semantic)]
        if not members:
            continue
        target = "source:" + members[0]["source_id"]
        if any(source["sha256"] != item["source_sha256"] for source in members):
            _reject(target, "A source context cannot silently retain an old SHA after reconfirmation.")
        physical = None
        if source_frames is not None and members[0]["source_id"] in source_frames:
            try:
                physical = observe_binding(source_frames[members[0]["source_id"]], members[0], item)
                for source in members:
                    validate_stage_intervals(semantic, source, item, physical[1])
            except ValueError as exc:
                _reject(target, str(exc))
        elif item["condition"] or any("derivation" in coordinate for coordinate in item["coordinates"].values()):
            _reject(target, "Source condition and derivation reconfirmation require the admission owner's original frame.")
        coordinates: list[tuple[str, dict[str, Any], bool]] = []
        for role, coordinate in item["coordinates"].items():
            try:
                leaves = literal_coordinates(coordinate, candidate=physical[0], block=physical[1], role=role) if physical else [(role, coordinate)]
                is_derived = "derivation" in coordinate
                if is_derived:
                    require_derivation_origins(document, item, semantic, leaves, derivations,
                                               datasets=datasets, column_facts=column_facts)
            except ValueError as exc:
                _reject(target, str(exc))
            coordinates.extend((quantity, leaf, is_derived) for quantity, leaf in leaves)
        for role, coordinate, is_derived in coordinates:
            if any(key not in coordinate for key in ("column_id", "header", "observed_quantity", "observed_unit",
                                                      "source_unit", "unit", "quantity", "unit_context", "unit_relation")):
                _reject(target, "Reconfirmation requires a complete literal source coordinate context.")
            if role in item["quantities"] and item["quantities"][role] != coordinate["quantity"]:
                _reject(target, "Reconfirmed source quantity must agree with its literal coordinate.")
            key = coordinate["column_id"]
            proof = coordinate.get("unit_context", {})
            for source in members:
                fact = column_facts[source["source_id"]].get(key)
                observed_quantity = _quantity(fact["raw_metadata"]["header"]) if fact else None
                if is_derived:
                    authorized = True  # The actual typed edge was matched above; raw metadata cannot authorize a different edge.
                else:
                    retained = any(old_coordinate.get("column_id") == key and old_coordinate.get("quantity") == coordinate["quantity"]
                                   and old_item["table_selection"] == item["table_selection"]
                                   for old_item in _contexts(old_binding, physical_path(source["path"]))
                                   for old_coordinate in old_item["coordinates"].values())
                    authorized = (source["source_id"], key, coordinate["quantity"], coordinate["unit"]) in allowed or retained or observed_quantity == coordinate["quantity"]
                if (fact is None or not authorized
                        or observed_quantity is not None and observed_quantity != coordinate["quantity"]
                        or coordinate["header"] != fact["raw_metadata"]["header"]
                        or coordinate["observed_quantity"] != _quantity(fact["raw_metadata"]["header"])
                        or coordinate["observed_unit"] != fact["raw_metadata"]["unit"]
                        or coordinate["source_unit"] != fact["unit"]
                        or proof.get("source_header") != coordinate["header"]
                        or proof.get("quantity") != coordinate["quantity"]
                        or proof.get("observed_quantity") != coordinate["observed_quantity"]):
                    _reject(target, "Reconfirmed context must match the fresh original column and current public mapping quantity.")
            relation = resolve_unit_relation(coordinate["source_unit"], coordinate["unit"],
                quantity=coordinate["quantity"], observed_quantity=coordinate["observed_quantity"],
                explicit_quantity_binding=proof.get("explicit_quantity_binding") is True)
            if coordinate["unit_relation"] != relation:
                _reject(target, "Reconfirmed context must retain its declared registered unit relation.")


def _normalized_contexts(binding: dict[str, Any], path: str) -> list[dict[str, Any]]:
    from sciplot_core.foundation.json_hashing import canonical_json_sha256

    items = deepcopy(_contexts(binding, path))
    for item in items:
        item["source_path"] = physical_path(item["source_path"])
    return sorted(items, key=canonical_json_sha256)
