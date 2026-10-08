"""Semantic plot CLI transport; no independent plotting or recovery decisions."""

from pathlib import Path
from typing import Any

from sciplot_core.cli.value_io import _print_json
from sciplot_core.plot_protocol.client import call
from sciplot_core.plot_protocol.rpc import MAX_REQUEST_BYTES, ProtocolError, decode


def _request(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    with path.open("rb") as stream:
        raw = stream.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise ProtocolError(-32602, "rpc_frame_too_large", "Request JSON file exceeds 1 MiB.")
    value = decode(raw)
    if not isinstance(value, dict):
        raise ProtocolError(-32602, "invalid_json_file", "Request file must contain a JSON object.",
                            issues=[{"path": "/", "constraint": "object"}])
    return value


def dispatch_plot(args: Any) -> int | None:
    if args.command != "plot":
        return None
    action = args.plot_action
    if action == "serve":
        from sciplot_core.plot_protocol.server import serve

        serve(args.socket, idle_timeout=args.idle_timeout, request_timeout=args.request_timeout)
        return 0
    params: dict[str, Any] = {}
    if action == "open":
        params["target"] = str(args.target.expanduser().resolve())
        if args.figure_id is not None:
            params["figure_id"] = args.figure_id
    elif action != "create":
        params["plot"] = str(args.plot.expanduser().resolve())
    if action in {"create", "patch", "rollback", "decide"}:
        params["request"] = _request(args.request)
        if action == "create":
            for field in ("source", "profile", "out"):
                value = params["request"].get(field)
                if isinstance(value, str) and value.strip():
                    params["request"][field] = str(Path(value).expanduser().resolve())
            binding = params["request"].get("data_binding")
            if isinstance(binding, dict) and isinstance(binding.get("data_sources"), list):
                for source in binding["data_sources"]:
                    if isinstance(source, dict) and isinstance(source.get("path"), str) and source["path"].strip():
                        source["path"] = str(Path(source["path"]).expanduser().resolve())
    method = "project.open" if action == "open" else f"plot.{action}"
    result = call(method, params, socket_path=args.socket, direct=args.direct, timeout=args.timeout)
    _print_json(result)
    return 1 if result.get("status") in {"error", "blocked"} else 0
