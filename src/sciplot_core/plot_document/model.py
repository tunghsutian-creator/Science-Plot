"""Canonical scientific and presentation state, independent of backend bytes."""

from copy import deepcopy
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256

from .errors import fail
from .properties import validate_capability, validate_value
from .schema import document_schema
from .validation import pointer_part, validate_wire


def _validate(document: Any, *, verify_hashes: bool) -> dict[str, Any]:
    validate_wire(document, document_schema(), code="document_invalid")
    assert isinstance(document, dict)
    if document.get("plot_type") == "ManagedPlot" and document["coverage"]["mode"] != "managed":
        fail("document_authority_conflict", "ManagedPlot requires complete managed coverage.", "/coverage", "managed_authority")
    if document.get("plot_type") == "LegacyPlot" and document["coverage"]["mode"] == "managed":
        fail("document_authority_conflict", "LegacyPlot cannot claim document-authoritative coverage.", "/coverage", "legacy_authority")
    for identifier, obj in document["presentation"]["objects"].items():
        path = "/presentation/objects/" + pointer_part(identifier)
        if set(obj["properties"]) != set(obj["capabilities"]):
            fail("document_invalid_capability", "Every editable property must have exactly one capability.",
                 path, "property_capability_equality")
        for prop, capability in obj["capabilities"].items():
            validate_capability(obj, prop, capability, path + "/capabilities/" + pointer_part(prop))
            validate_value(prop, obj["properties"][prop], capability, path + "/properties/" + pointer_part(prop))
    if verify_hashes:
        for domain in ("scientific", "presentation"):
            digest = document.get(domain + "_hash")
            if digest is not None and digest != canonical_json_sha256(document[domain], allow_nan=False):
                fail("document_hash_mismatch", "The stored document content does not match its seal.",
                     "/" + domain + "_hash", "content_hash")
    return deepcopy(document)


def validate_document(document: Any) -> dict[str, Any]:
    """Return an isolated, strictly validated snapshot; verify any stored seals."""
    return _validate(document, verify_hashes=True)


def seal_document(document: Any) -> dict[str, Any]:
    """Compute domain seals after a trusted state change; runtime metadata is outside."""
    result = _validate(document, verify_hashes=False)
    for domain in ("scientific", "presentation"):
        result[domain + "_hash"] = canonical_json_sha256(result[domain], allow_nan=False)
    return result
