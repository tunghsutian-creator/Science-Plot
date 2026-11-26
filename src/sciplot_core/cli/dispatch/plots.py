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


def dispatch_plot(args: Any, argv: list[str] | None = None) -> int | None:
    if args.command != "plot":
        return None
    action = args.plot_action
    if action == "editor":
        import sys
        from sciplot_core.studio_core.runtime import maybe_reexec_with_qt_runtime

        maybe_reexec_with_qt_runtime(sys.argv[1:] if argv is None else argv)
        from sciplot_core.plot_editor import run_editor

        return run_editor(args.plot, socket_path=args.socket, timeout=args.timeout, figure_id=args.figure)
    if action == "serve":
        from sciplot_core.plot_protocol.server import serve

        serve(args.socket, idle_timeout=args.idle_timeout, request_timeout=args.request_timeout)
        return 0
    selected_export = action == "export" and (args.tiff or args.plotted_csv or args.editable_vsz
        or any(value is not None for value in (args.output_dir, args.plot_id, args.revision)))
    params: dict[str, Any] = {}
    if action == "open":
        params["target"] = str(args.target.expanduser().absolute())
        if args.figure_id is not None:
            params["figure_id"] = args.figure_id
    elif action not in {"create", "deliver"}:
        plot = args.plot.expanduser()
        params["plot"] = str(plot.absolute() if action == "intent" or selected_export else plot.resolve())
    if action in {"open", "describe"} and any(value is not None for value in (args.scope, args.target_id, args.property)):
        params["description"] = {key: value for key, value in
            (("scope", args.scope), ("target", args.target_id), ("property", args.property)) if value is not None}
    if action in {"create", "patch", "resume", "intent", "rollback", "decide", "deliver"}:
        params["request"] = _request(args.request)
        if action == "create":
            if args.project is not None:
                params["project"] = str(args.project.expanduser().absolute())
            for field in ("source", "profile", "out"):
                value = params["request"].get(field)
                if isinstance(value, str) and value.strip():
                    params["request"][field] = str(Path(value).expanduser().resolve())
            binding = params["request"].get("data_binding")
            if isinstance(binding, dict) and isinstance(binding.get("data_sources"), list):
                for source in binding["data_sources"]:
                    if isinstance(source, dict) and isinstance(source.get("path"), str) and source["path"].strip():
                        source["path"] = str(Path(source["path"]).expanduser().resolve())
    if selected_export:
        destination = str(args.output_dir.expanduser().absolute()) if args.output_dir is not None else None
        if args.plotted_csv:
            formats = ["plotted_csv"]
        elif args.editable_vsz:
            formats = ["editable_vsz"]
        else:
            formats = ["pdf", "tiff_300"] if args.tiff else ["pdf"]
        params["handoff"] = {"output_dir": destination, "plot_id": args.plot_id, "revision": args.revision, "formats": formats}
    method = "project.open" if action == "open" else f"plot.{action}"
    result = call(method, params, socket_path=args.socket, direct=args.direct, timeout=args.timeout)
    _print_json(result)
    return 1 if result.get("status") in {"error", "blocked", "partial"} else 0
