"""Optional stdio adapter for SciPlot's existing local control services."""

from __future__ import annotations


def run_stdio() -> None:
    """Run the official MCP transport without making the SDK a core dependency."""
    try:
        from sciplot_core.mcp_server.server import serve_stdio
    except ModuleNotFoundError as exc:
        if exc.name is not None and (exc.name == "mcp" or exc.name.startswith("mcp.")):
            raise RuntimeError(
                "MCP support is not installed. Install sciplot-core[mcp] or use "
                "a SciPlot distribution that includes external AI support."
            ) from exc
        raise
    import anyio

    anyio.run(serve_stdio)


__all__ = ["run_stdio"]
