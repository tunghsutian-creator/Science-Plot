"""Closed JSON-RPC commands shared by socket, CLI and direct local clients."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from sciplot_core.task_error_feedback import exception_feedback

MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class Service(Protocol):
    def open(self, target: Path, figure_id: str | None = None) -> dict[str, Any]: ...
    def describe(self, plot: Path) -> dict[str, Any]: ...
    def patch(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]: ...
    def render(self, plot: Path) -> dict[str, Any]: ...
    def export(self, plot: Path) -> dict[str, Any]: ...
    def rollback(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]: ...
    def create(self, request: dict[str, Any]) -> dict[str, Any]: ...
    def decide(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]: ...


class ProtocolError(ValueError):
    def __init__(self, code: int, reason_code: str, message: str,
                 *, issues: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.reason_code = reason_code
        self.issues = issues or []


class RemoteError(ValueError):
    def __init__(self, error: dict[str, Any]) -> None:
        super().__init__(str(error.get("message", "Local plot operation failed.")))
        self.rpc_code = error.get("code", -32000)
        data = error.get("data", {})
        self.reason_code = str(data.get("reason_code", "plot_execution_failed"))
        self.issues = data.get("issues", [])
        self.repair = data.get("repair")
        self.diagnostics = data.get("diagnostics")


def _reject_constant(value: str) -> Any:
    raise ValueError(f"Nonfinite JSON number {value} is not allowed.")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON object keys are not allowed.")
        value[key] = item
    return value


def decode(raw: bytes) -> Any:
    try:
        return json.loads(raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ProtocolError(-32700, "invalid_json", "Request must contain one valid, finite JSON object.") from exc


def encode(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode() + b"\n"


def validate_call(value: Any) -> tuple[str | int, str, dict[str, Any]]:
    if (not isinstance(value, dict) or value.get("jsonrpc") != "2.0"
            or set(value) - {"jsonrpc", "id", "method", "params"}
            or not isinstance(value.get("id"), (str, int)) or isinstance(value.get("id"), bool)
            or not isinstance(value.get("method"), str)):
        raise ProtocolError(-32600, "invalid_rpc_request", "A JSON-RPC 2.0 call with an explicit string or integer id is required.")
    params = value.get("params", {})
    if not isinstance(params, dict):
        raise ProtocolError(-32602, "invalid_rpc_params", "Use named object parameters.")
    return value["id"], value["method"], params


def validate_params(method: str, params: dict[str, Any]) -> None:
    fields: dict[str, tuple[set[str], set[str]]] = {
        "project.open": ({"target"}, {"target", "figure_id"}),
        "plot.create": ({"request"}, {"request"}),
        "plot.describe": ({"plot"}, {"plot"}),
        "plot.render": ({"plot"}, {"plot"}),
        "plot.export": ({"plot"}, {"plot"}),
        "plot.patch": ({"plot", "request"}, {"plot", "request"}),
        "plot.rollback": ({"plot", "request"}, {"plot", "request"}),
        "plot.decide": ({"plot", "request"}, {"plot", "request"}),
    }
    if method not in fields:
        raise ProtocolError(-32601, "rpc_method_not_found", "Unknown semantic plot method.",
                            issues=[{"path": "/method", "allowed": sorted(fields)}])
    required, allowed = fields[method]
    issues: list[dict[str, Any]] = []
    if required - params.keys():
        issues.append({"path": "/params", "constraint": "required", "missing": sorted(required - params.keys())})
    if params.keys() - allowed:
        issues.append({"path": "/params", "constraint": "additionalProperties", "allowed": sorted(allowed)})
    for key in ("target", "plot", "figure_id"):
        if key in params and (not isinstance(params[key], str) or not params[key].strip()):
            issues.append({"path": f"/params/{key}", "constraint": "nonempty_string"})
        elif key in {"target", "plot"} and key in params and not Path(params[key]).is_absolute():
            issues.append({"path": f"/params/{key}", "constraint": "absolute_path"})
    if "request" in params and not isinstance(params["request"], dict):
        issues.append({"path": "/params/request", "constraint": "object"})
    if issues:
        raise ProtocolError(-32602, "invalid_rpc_params", "Correct the indicated method parameters.", issues=issues)


def invoke(service: Service, method: str, params: dict[str, Any]) -> dict[str, Any]:
    validate_params(method, params)
    if method == "project.open":
        return service.open(Path(params["target"]).expanduser().resolve(), figure_id=params.get("figure_id"))
    if method == "plot.create":
        return service.create(params["request"])
    plot = Path(params["plot"]).expanduser().resolve()
    if method == "plot.describe":
        return service.describe(plot)
    if method == "plot.render":
        return service.render(plot)
    if method == "plot.export":
        return service.export(plot)
    if method == "plot.patch":
        return service.patch(plot, params["request"])
    if method == "plot.rollback":
        return service.rollback(plot, params["request"])
    return service.decide(plot, params["request"])


def error_response(request_id: str | int | None, exc: Exception) -> dict[str, Any]:
    feedback = exception_feedback(exc)
    reason = getattr(exc, "reason_code", None)
    if not isinstance(reason, str):
        reason = "path_not_found" if isinstance(exc, FileNotFoundError) else "plot_execution_failed"
    data = {"reason_code": reason, **{k: v for k, v in feedback.items() if k != "message"}}
    repair = getattr(exc, "repair", None)
    if repair is not None:
        data["repair"] = repair
    diagnostics = getattr(exc, "diagnostics", None)
    if diagnostics is not None:
        data["diagnostics"] = diagnostics
    code = exc.code if isinstance(exc, ProtocolError) else -32000
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": feedback["message"], "data": data}}


def handle(service: Service, value: Any) -> dict[str, Any]:
    request_id: str | int | None = None
    try:
        request_id, method, params = validate_call(value)
        return {"jsonrpc": "2.0", "id": request_id, "result": invoke(service, method, params)}
    except Exception as exc:
        return error_response(request_id, exc)
