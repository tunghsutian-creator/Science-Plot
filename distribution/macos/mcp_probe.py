"""Check the packaged stdio process with the official MCP client, without a model."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from distribution.macos.welcome import DAILY_MCP_ARGS


def read_connection(directory: Path, command: Path) -> tuple[str, list[str]]:
    """Use the welcome page's actual snippets, bound to the relocated bundle."""
    wire = json.loads((directory / "mcp-server.json").read_text(encoding="utf-8"))["mcpServers"]["sciplot"]
    codex = tomllib.loads((directory / "codex-mcp.toml").read_text(encoding="utf-8"))["mcp_servers"]["sciplot"]
    expected = {"command": str(command.resolve()), "args": list(DAILY_MCP_ARGS)}
    if wire != expected or {key: codex.get(key) for key in expected} != expected:
        raise ValueError("Welcome connection snippets must agree and use the relocated bundle's daily entrypoint")
    return wire["command"], wire["args"]


def verify_mcp(command: Path, environment: dict[str, str], connection_directory: Path) -> dict:
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    executable, arguments = read_connection(connection_directory, command)

    async def scenario() -> dict:
        parameters = StdioServerParameters(command=executable, args=arguments, env=environment)
        async with Client(parameters, read_timeout_seconds=60) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            daily = {"sciplot_capabilities", "sciplot_task_capabilities", "sciplot_task_start",
                     "sciplot_task_continue", "sciplot_project_open", "sciplot_task_edit",
                     "sciplot_task_resume"}
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
            return {
                "status": "passed", "tool_count": len(names), "transport": "mcp_stdio", "model_calls": 0,
                "task_contract_sha256": task["contract_sha256"], "profile": arguments[-1],
                "claim": "bundled_connection_and_tool_catalog_not_client_or_figure_acceptance",
            }

    return anyio.run(scenario)
