"""Bounded internal framing for stateless native document operations."""

import json
from typing import Any

MAX_REQUEST_BYTES = 65536
MAX_STDOUT_BYTES = 16 * 1024 * 1024
MAX_STDERR_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
ALLOWED_COMMANDS = frozenset({"inspect-document-state", "audit-documents", "audit-spec-data",
                              "preview-document", "edit-document", "edit-annotations", "export-document",
                              "compile-plot-ir", "inspect-plot-ir"})


def decode(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate internal protocol key.")
            value[key] = item
        return value

    def constant(_value: str) -> None:
        raise ValueError("Non-finite internal protocol value.")

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError("Internal protocol messages must be objects.")
    return value


def encode(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def validate_request(value: dict[str, Any]) -> tuple[str, list[str]]:
    if set(value) != {"id", "argv"} or not isinstance(value["id"], str) or not 1 <= len(value["id"]) <= 64:
        raise ValueError("Invalid internal request identity.")
    argv = value["argv"]
    if (not isinstance(argv, list) or not 1 <= len(argv) <= 128
            or not all(isinstance(arg, str) and len(arg) <= 8192 and "\x00" not in arg for arg in argv)
            or argv[0] not in ALLOWED_COMMANDS):
        raise ValueError("Unsupported internal native command or argument shape.")
    return value["id"], argv


def validate_response(value: dict[str, Any], request_id: str) -> dict[str, Any]:
    if (set(value) != {"id", "returncode", "stdout", "stderr", "pid"} or value.get("id") != request_id
            or type(value.get("returncode")) is not int or type(value.get("pid")) is not int
            or not isinstance(value.get("stdout"), str) or not isinstance(value.get("stderr"), str)
            or len(value["stdout"].encode()) > MAX_STDOUT_BYTES or len(value["stderr"].encode()) > MAX_STDERR_BYTES):
        raise ValueError("Invalid or mismatched internal native response.")
    return value
