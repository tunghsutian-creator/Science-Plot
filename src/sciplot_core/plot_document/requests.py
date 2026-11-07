"""Owned request values; immutable identity is separate from domain permission."""

from dataclasses import InitVar, dataclass, field
import json
from typing import Any, cast, final

from sciplot_core.foundation.json_hashing import canonical_json_sha256

from .schema import patch_schema
from .validation import finite_json, pointer_part, validate_schema, validate_wire


def _snapshot(value: Any, path: str = "") -> Any:
    """Capture strict JSON without invoking user-defined copy/coercion hooks."""
    if type(value) is list:
        return [_snapshot(item, f"{path}/{index}") for index, item in enumerate(value)]
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: _snapshot(item, f"{path}/{pointer_part(key)}") for key, item in value.items()}
    finite_json(value, path)
    return value


@final
@dataclass(frozen=True)
class RequestBody:
    value: InitVar[dict[str, Any]]
    _json: str = field(init=False, repr=False, compare=False)
    digest: str = field(init=False)

    def __post_init__(self, value: dict[str, Any]) -> None:
        if type(value) is not dict:
            raise ValueError("A command request must be a finite JSON object.")
        snapshot = _snapshot(value)
        object.__setattr__(self, "_json", json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        object.__setattr__(self, "digest", canonical_json_sha256(snapshot, allow_nan=False))

    def to_payload(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self._json))


@final
@dataclass(frozen=True)
class PatchRequest:
    value: InitVar[RequestBody | dict[str, Any]]
    body: RequestBody = field(init=False)

    def __post_init__(self, value: RequestBody | dict[str, Any]) -> None:
        if type(value) is RequestBody:
            body = value
        else:
            if type(value) is not dict:
                # Preserve the public raw-patch diagnostics for finite scalars,
                # arrays and non-JSON objects before making an object snapshot.
                validate_wire(value, patch_schema(), code="document_invalid_patch")
            body = RequestBody(value)
        validate_schema(body.to_payload(), patch_schema(), code="document_invalid_patch")
        object.__setattr__(self, "body", body)

    @property
    def digest(self) -> str:
        return self.body.digest

    def to_payload(self) -> dict[str, Any]:
        return self.body.to_payload()


def admit_patch(value: Any) -> PatchRequest:
    """A concrete owned patch proves wire shape, never target or IO permission."""
    return value if type(value) is PatchRequest else PatchRequest(value)


RequestInput = RequestBody | PatchRequest | dict[str, Any]
