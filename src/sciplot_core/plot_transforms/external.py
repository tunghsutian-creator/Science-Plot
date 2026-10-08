"""Explicit fixed-file execution, never evaluation of client-supplied snippets."""

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_document.errors import fail
from sciplot_core.plot_document.schema import DIGEST, closed
from sciplot_core.plot_document.validation import validate_wire

from .datasets import dataset_schema

MAX_RESPONSE_BYTES = 32 * 1024 * 1024


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


def response_schema() -> dict[str, Any]:
    return closed({"kind": {"const": "sciplot_transform_response"}, "schema_version": {"const": 1},
                   "request_sha256": DIGEST, "columns": dataset_schema()["properties"]["columns"]})


def request_schema() -> dict[str, Any]:
    return closed({"kind": {"const": "sciplot_transform_request"}, "schema_version": {"const": 1},
                   "node_id": {"type": "string"}, "parameters": {"type": "object"},
                   "input": dataset_schema(), "request_sha256": DIGEST})


def executor_files(nodes: list[dict[str, Any]], registry: dict[str, ExternalExecutor]) -> dict[str, str]:
    files = {}
    for node in nodes:
        if node["kind"] != "external":
            continue
        identifier = node["executor"]["id"]
        if identifier not in registry:
            fail("transform_executor_unknown", "This fixed-file executor is not registered locally.", "/executor/id", "registered_executor")
        executor = registry[identifier]
        if executor.descriptor(identifier) != node["executor"]:
            fail("transform_executor_changed", "The executor bytes or parameter contract changed; bind their current hashes explicitly.",
                 "/executor", "exact_executor_identity")
        files[str(executor.executable)] = node["executor"]["executable_sha256"]
        files[str(executor.script)] = node["executor"]["script_sha256"]
    return files


def run_external(node: dict[str, Any], source: dict[str, Any], registry: dict[str, ExternalExecutor]) -> tuple[dict[str, Any], dict[str, Any]]:
    files = executor_files([node], registry)
    executor = registry[node["executor"]["id"]]
    validate_wire(node["parameters"], executor.parameter_schema, code="transform_external_parameters")
    request = {"kind": "sciplot_transform_request", "schema_version": 1, "node_id": node["id"],
               "parameters": node["parameters"], "input": source}
    request_hash = canonical_json_sha256(request, allow_nan=False)
    with tempfile.TemporaryDirectory(prefix="sciplot-transform-") as directory:
        root = Path(directory)
        request_path, response_path = root / "request.json", root / "response.json"
        request_path.write_text(json.dumps({**request, "request_sha256": request_hash}, allow_nan=False), encoding="utf-8")
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run([str(executor.executable), str(executor.script), "--request", str(request_path),
                                         "--response", str(response_path)], cwd=root, stdin=subprocess.DEVNULL,
                                        stdout=output, stderr=output, timeout=executor.timeout_seconds, check=False)
            except subprocess.TimeoutExpired:
                fail("transform_external_timeout", "The fixed executor exceeded its deadline; it was not repeated.", "/executor", "bounded_execution")
            if result.returncode != 0:
                fail("transform_external_failed", "The fixed executor failed; no derived data was accepted.",
                     "/executor", "successful_exit", returncode=result.returncode)
        executor_files([node], registry)
        if not response_path.is_file() or response_path.is_symlink() or response_path.stat().st_size > MAX_RESPONSE_BYTES:
            fail("transform_external_response", "The fixed executor must return one bounded JSON result file.", "/response", "bounded_file")
        try:
            response = json.loads(response_path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            fail("transform_external_response", "The executor response is not finite schema-valid JSON.", "/response", "json")
    validate_wire(response, response_schema(), code="transform_external_response")
    if response["request_sha256"] != request_hash:
        fail("transform_external_response", "The response belongs to a different transform request.", "/request_sha256", "request_identity")
    return {"id": node["output"], "columns": response["columns"], "provenance": source["provenance"]}, {
        "request_sha256": request_hash, "executor_files": files, "protocol_version": 1}
