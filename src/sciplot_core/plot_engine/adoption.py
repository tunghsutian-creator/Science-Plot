"""Adopt explicit template series identities before a new plot's first revision."""

from copy import deepcopy
from typing import Any

from sciplot_core.plot_document import seal_document, validate_document

from .errors import EngineError
from .storage import digest


def adoption_identity(series_ids: dict[str, str], recipe: dict[str, Any]) -> dict[str, Any]:
    return {"series_ids": dict(series_ids), "recipe_sha256": digest(recipe)}


def require_adoption(binding: dict[str, Any], series_ids: dict[str, str], recipe: dict[str, Any]) -> None:
    if binding.get("template_adoption") != adoption_identity(series_ids, recipe):
        raise EngineError("document_template_adoption_conflict",
                          "This existing document was imported with a different template identity.",
                          action="use_original_creation_request")


def adopt(document: dict[str, Any], binding: dict[str, Any], *,
          series_ids: dict[str, str], recipe: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    document, binding = validate_document(document), deepcopy(binding)
    if document["revision"] != 0 or "template_adoption" in binding:
        raise EngineError("document_template_adoption_conflict", "Template identities can only be adopted at initial import.")
    objects = document["presentation"]["objects"]
    series = {identifier: obj for identifier, obj in objects.items() if obj["kind"] == "series"}
    labels = [obj["label"] for obj in series.values()]
    if len(set(labels)) != len(labels) or set(labels) != set(series_ids):
        raise EngineError("document_template_series_mismatch",
                          "Every template series must match exactly one created native sample.",
                          action="correct_binding", actual_labels=labels, expected_labels=list(series_ids))
    renamed = {identifier: series_ids[obj["label"]] for identifier, obj in series.items()}
    new_ids = [renamed.get(identifier, identifier) for identifier in objects]
    if len(set(new_ids)) != len(new_ids):
        raise EngineError("document_template_identity_collision", "Template series IDs collide with another object.")
    targets = binding["targets"]
    if not set(renamed) <= set(targets):
        raise EngineError("document_template_backend_mismatch", "The native binding does not cover every requested series.")
    document["presentation"]["objects"] = {renamed.get(identifier, identifier): obj for identifier, obj in objects.items()}
    binding["targets"] = {renamed.get(identifier, identifier): target for identifier, target in targets.items()}
    # Explicit original-cell bindings augment native import provenance. The native
    # numerical audit still owns proof that created coordinates match those cells.
    data_binding = recipe.get("data_binding")
    if not isinstance(data_binding, dict):
        raise EngineError("document_template_binding_missing", "An adopted template requires its exact scientific binding.")
    document["scientific"]["provenance"]["template_data_binding"] = deepcopy(data_binding)
    binding["template_adoption"] = adoption_identity(series_ids, recipe)
    return seal_document(document), binding
