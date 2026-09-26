"""Check the packaged stdio process with the official MCP client, without a model."""

from __future__ import annotations

from pathlib import Path


def verify_mcp(command: Path, environment: dict[str, str]) -> dict:
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    async def scenario() -> dict:
        parameters = StdioServerParameters(command=str(command), args=["mcp"], env=environment)
        async with Client(parameters, read_timeout_seconds=60) as client:
            tools = await client.list_tools()
            names = [tool.name for tool in tools.tools]
            if "sciplot_capabilities" not in names:
                raise RuntimeError("The bundled MCP server did not advertise SciPlot capabilities")
            result = await client.call_tool("sciplot_capabilities", {})
            payload = result.structured_content
            if result.is_error or payload.get("transport") != "mcp_stdio":
                raise RuntimeError("The bundled MCP capabilities call failed")
            if payload.get("model_configuration_required") is not False:
                raise RuntimeError("The bundled MCP server unexpectedly requires a model")
            if "sciplot_task_capabilities" not in names:
                raise RuntimeError("The bundled MCP server has no task interface")
            task_result = await client.call_tool("sciplot_task_capabilities", {})
            task = task_result.structured_content
            if task_result.is_error or task.get("kind") != "sciplot_task_capabilities" or not task.get("contract_sha256"):
                raise RuntimeError("The bundled task capabilities call failed")
            return {
                "status": "passed", "tool_count": len(names), "transport": "mcp_stdio", "model_calls": 0,
                "task_contract_sha256": task["contract_sha256"],
            }

    return anyio.run(scenario)
