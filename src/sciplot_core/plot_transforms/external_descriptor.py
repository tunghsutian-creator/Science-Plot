"""Sealed external execution identity, independent of host authorization or launch."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_document.errors import fail
from sciplot_core.plot_document.schema import closed
from sciplot_core.plot_document.validation import validate_wire


@dataclass(frozen=True)
class ExternalExecutor:
    executable: Path
    script: Path
    parameter_schema: dict[str, Any]
    timeout_seconds: float = 30
    version: str = "1"
    side_effect_free: bool = True

    def to_dict(self, identifier: str) -> dict[str, Any]:
        return {"executable": str(self.executable), "script": str(self.script),
                "parameter_schema": self.parameter_schema, "timeout_seconds": self.timeout_seconds,
                "version": self.version, "side_effect_free": self.side_effect_free,
                "identity": self.descriptor(identifier)}

    @classmethod
    def from_dict(cls, value: Any) -> "ExternalExecutor":
        validate_wire(value, closed({"executable": {"type": "string", "minLength": 1},
            "script": {"type": "string", "minLength": 1}, "parameter_schema": {"type": "object"},
            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 120},
            "version": {"type": "string", "minLength": 1}, "side_effect_free": {"const": True},
            "identity": {"type": "object"}}), code="transform_executor_invalid")
        executor = cls(Path(value["executable"]), Path(value["script"]), value["parameter_schema"], value["timeout_seconds"], value["version"], value["side_effect_free"])
        identifier = value["identity"].get("id")
        if not isinstance(identifier, str) or executor.descriptor(identifier) != value["identity"]:
            fail("transform_executor_changed", "The saved fixed executor identity no longer matches its files.", "/identity", "exact_executor_identity")
        return executor

    def descriptor(self, identifier: str) -> dict[str, Any]:
        if self.side_effect_free is not True or not self.version:
            fail("transform_executor_contract", "Only explicitly versioned side-effect-free executors are supported.", "/executor", "declared_executor_contract")
        for path in (self.executable, self.script):
            if not path.is_absolute() or not path.is_file():
                fail("transform_executor_missing", "External executors require fixed existing absolute files.",
                     "/executor", "fixed_file")
        if not 0 < self.timeout_seconds <= 120:
            fail("transform_executor_timeout", "Executor timeout must be positive and at most 120 seconds.", "/executor", "bounded_timeout")
        if self.parameter_schema.get("type") != "object" or self.parameter_schema.get("additionalProperties") is not False:
            fail("transform_executor_schema", "An external executor needs a closed parameter-object schema.", "/executor", "closed_parameters")
        identity = {"kind": "external", "id": identifier, "executable_sha256": file_sha256(self.executable),
                "script_sha256": file_sha256(self.script), "protocol_version": 1,
                "version": self.version, "side_effect_free": self.side_effect_free,
                "parameter_schema_sha256": canonical_json_sha256(self.parameter_schema, allow_nan=False)}
        return {**identity, "content_hash": canonical_json_sha256(identity, allow_nan=False)}
