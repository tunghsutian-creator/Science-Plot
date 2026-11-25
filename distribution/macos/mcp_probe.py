"""Check the packaged stdio process with the official MCP client, without a model."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from time import monotonic

from distribution.macos.welcome import DAILY_MCP_ARGS, FIRST_FIGURE_CSV, FIRST_FIGURE_NAME


def read_connection(directory: Path, command: Path) -> tuple[str, list[str]]:
    """Use the welcome page's actual snippets, bound to the relocated bundle."""
    wire = json.loads((directory / "mcp-server.json").read_text(encoding="utf-8"))["mcpServers"]["sciplot"]
    codex = tomllib.loads((directory / "codex-mcp.toml").read_text(encoding="utf-8"))["mcp_servers"]["sciplot"]
    expected = {"command": str(command.resolve()), "args": list(DAILY_MCP_ARGS)}
    if wire != expected or {key: codex.get(key) for key in expected} != expected:
        raise ValueError("Welcome connection snippets must agree and use the relocated bundle's daily entrypoint")
    return wire["command"], wire["args"]


async def _verify_first_figure(client, directory: Path) -> dict:
    directory = directory.resolve()
    directory.mkdir()
    source = directory / FIRST_FIGURE_NAME
    source.write_text(FIRST_FIGURE_CSV, encoding="utf-8")

    async def call(tool: str, arguments: dict) -> dict:
        result = await client.call_tool(tool, arguments)
        payload = result.structured_content
        if result.is_error or not isinstance(payload, dict):
            raise RuntimeError(f"{tool} did not return a successful synthetic first-figure result: {result.content}")
        return payload

    started = monotonic()
    pending = await call("sciplot_task_start", {
        "request": {"version": 1, "action": "create", "sources": [str(source)],
                    "intent": {"x": {"quantity": "time"}, "y": {"quantity": "mass"}}},
        "task_dir": str(directory / "task"),
    })
    choices = pending.get("question", {}).get("plan", {}).get("decisions", [])
    if (pending["status"] != "needs_input"
            or [(item["field"], item["options"]) for item in choices] != [("y_header", ["Mass", "Weight"])]):
        raise RuntimeError("The training CSV must ask for exactly one original response column choice")
    question_at = monotonic()
    answer = {**pending["next_step"]["response_template"], "choices": {"y_header": "Mass"}}
    completed = await call("sciplot_task_resume", {"task": pending["task_dir"], "response": answer})
    if completed["status"] != "complete" or completed["ready_to_use"] is not True:
        raise RuntimeError(f"The training task did not finish its real exports: {completed.get('blocker')}")
    delivered = monotonic()
    next_step = completed["next_step"]
    files = next_step["files"]
    if len(files) != 1 or not all(Path(files[0][name]).is_file() for name in ("pdf", "tiff_300", "editable")):
        raise RuntimeError("The training task did not deliver a PDF, a TIFF and an editable VSZ")
    if next_step["images"] != [files[0]["tiff_300"]] or not next_step["plotting_data"]:
        raise RuntimeError("The training task did not expose its figure and plotted data")
    opened = await call("sciplot_project_open", {
        "target": completed["project"], "description": {"scope": "summary"},
    })
    saved = completed["result"]
    if (opened["plot_type"] != "ManagedPlot" or opened["description_scope"] != "summary"
            or any(opened[key] != saved[key] for key in (
                "plot", "plot_id", "revision", "scientific_hash", "presentation_hash"))
            or opened["object_operations"]["patch"]["available"] is not True
            or source.read_text(encoding="utf-8") != FIRST_FIGURE_CSV):
        raise RuntimeError("The training result did not reopen the same editable project with the original source intact")
    return {
        "status": "passed", "claim": "synthetic_first_figure_over_stdio_not_real_ai_client_acceptance",
        "project": completed["project"], "files": files[0], "plotting_data": next_step["plotting_data"],
        "summary_labels": {
            "axes": [opened["edit_targets"][axis]["label"] for axis in ("axis:x", "axis:y")],
            "series": [target["label"] for target in opened["edit_targets"].values() if target["kind"] == "layer"],
        },
        "tool_calls": 3, "scripted_user_choices": 1, "model_calls": completed["model_calls_by_sciplot"],
        "seconds_to_question": question_at - started, "seconds_to_delivery": delivered - started,
    }


def verify_mcp(command: Path, environment: dict[str, str], connection_directory: Path, *,
               first_figure_directory: Path | None = None) -> dict:
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    executable, arguments = read_connection(connection_directory, command)

    async def scenario() -> dict:
        parameters = StdioServerParameters(command=executable, args=arguments, env=environment)
        async with Client(parameters, read_timeout_seconds=180 if first_figure_directory is not None else 60) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            daily = {"sciplot_capabilities", "sciplot_task_capabilities", "sciplot_task_start",
                     "sciplot_task_continue", "sciplot_project_open", "sciplot_task_edit",
                     "sciplot_task_resume", "sciplot_project_legacy_redraw", "sciplot_project_legacy_convert"}
            if not daily <= names or "sciplot_plot_create" in names:
                raise RuntimeError("The bundled MCP server did not advertise its daily creation, continuation and edit catalog")
            result = await client.call_tool("sciplot_capabilities", {})
            payload = result.structured_content
            if result.is_error or not isinstance(payload, dict) or payload.get("transport") != "mcp_stdio":
                raise RuntimeError("The bundled MCP capabilities call failed")
            if payload.get("model_configuration_required") is not False:
                raise RuntimeError("The bundled MCP server unexpectedly requires a model")
            task_result = await client.call_tool("sciplot_task_capabilities", {})
            task = task_result.structured_content
            if (task_result.is_error or not isinstance(task, dict)
                    or task.get("kind") != "sciplot_task_capabilities" or not task.get("contract_sha256")):
                raise RuntimeError("The bundled task capabilities call failed")
            report = {
                "status": "passed", "tool_count": len(names), "transport": "mcp_stdio", "model_calls": 0,
                "task_contract_sha256": task["contract_sha256"], "profile": arguments[-1],
                "claim": "bundled_connection_and_tool_catalog_not_client_or_figure_acceptance",
            }
            if first_figure_directory is not None:
                report["first_figure"] = await _verify_first_figure(client, first_figure_directory)
            return report

    return anyio.run(scenario)
