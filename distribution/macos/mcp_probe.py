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
            return {"status": "passed", "tool_count": len(names), "transport": "mcp_stdio", "model_calls": 0}

    return anyio.run(scenario)
