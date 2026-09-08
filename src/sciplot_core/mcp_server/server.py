"""Official MCP stdio transport around serialized deterministic domain calls."""

from __future__ import annotations

import base64
from contextlib import redirect_stdout
from importlib.metadata import version
import json
from pathlib import Path
import sys
from typing import Any

import anyio
from jsonschema import Draft202012Validator
from mcp import MCPError
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    BlobResourceContents, CallToolResult, ImageContent, ListResourcesResult,
    ListToolsResult, ReadResourceResult, Resource, ResourceLink, TextContent,
    TextResourceContents,
)

from sciplot_core.mcp_server.errors import AdapterError, error_payload
from sciplot_core.studio_core.control_results import compact_result
from sciplot_core.mcp_server.resources import ResourceSnapshot, ResourceStore
from sciplot_core.mcp_server.schemas import tool_definitions
from sciplot_core.mcp_server.services import invoke_owner


INSTRUCTIONS = (
    "SciPlot executes local scientific plotting without calling a model. Prefer "
    "task_start/task_resume for a complete authorized task. Inspect existing saved "
    "projects instead of creating them again. Query real figure/object IDs and "
    "the saved SHA before edits. Read candidate PNG resources and scientific "
    "audits before accepting previews. Keep raw values, units and sample identities. "
    "Ask only for unresolved meaning or scope. Queries and edits do not certify "
    "delivery; handoff requires ready export evidence. Resource URIs are immutable "
    "snapshots limited to this server connection; inspect again for current state."
)


def _text_result(payload: dict[str, Any], *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(text=json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")))],
        structured_content=payload, is_error=is_error,
    )


def _read_result(snapshot: ResourceSnapshot) -> CallToolResult:
    payload = {"kind": "sciplot_resource", "version": 1, "status": "ok", **snapshot.metadata()}
    if snapshot.mime_type == "image/png":
        result = _text_result(payload)
        result.content.append(ImageContent(data=base64.b64encode(snapshot.data).decode(), mime_type="image/png"))
        return result
    return _text_result({**payload, "result": json.loads(snapshot.data)})


def _preview_artifact(payload: dict[str, Any]) -> dict[str, Any] | None:
    preview = payload.get("preview")
    if isinstance(preview, dict) and isinstance(preview.get("path"), str):
        return preview
    if isinstance(preview, dict):
        image = preview.get("image")
        if isinstance(image, dict) and isinstance(image.get("path"), str):
            return image
    # Task receipts may wrap the native edit review, but never inspect their
    # request payload for paths: only owner-generated result metadata is eligible.
    review = payload.get("review")
    if isinstance(review, dict):
        return _preview_artifact(review)
    return None


class Adapter:
    def __init__(self) -> None:
        self.tools = {item.name: item for item in tool_definitions()}
        self.validators = {name: Draft202012Validator(item.input_schema) for name, item in self.tools.items()}
        self.resources = ResourceStore()
        self.lock = anyio.Lock()

    def _execute(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        # Native workers capture their own protocol output. Incidental prints
        # from domain owners must never corrupt the outer MCP stdio stream.
        with redirect_stdout(sys.stderr):
            payload = invoke_owner(name, arguments)
        compact = payload if arguments.get("full") else compact_result(payload)
        links: list[ResourceSnapshot] = []
        warnings: list[str] = []
        if compact != payload:
            try:
                snapshot = self.resources.add_json(payload)
                compact = {**compact, "full_result_resource": snapshot.uri}
                links.append(snapshot)
            except AdapterError as exc:
                warnings.append(str(exc))
        preview_artifact = _preview_artifact(payload)
        if preview_artifact is not None:
            try:
                snapshot = self.resources.add_preview(Path(preview_artifact["path"]), expected_sha256=preview_artifact.get("sha256"))
                compact = {**compact, "preview_resource": snapshot.uri}
                links.append(snapshot)
            except (AdapterError, OSError) as exc:
                # Resource presentation failure does not turn a completed domain
                # mutation into an ambiguous failed action.
                warnings.append(str(exc))
        if warnings:
            compact = {**compact, "resource_warnings": warnings}
        result = _text_result(compact, is_error=compact.get("status") in {"error", "failed", "blocked"})
        result.content.extend(ResourceLink(**item.metadata()) for item in links)
        return result

    async def call(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        try:
            if name not in self.tools:
                raise AdapterError("unknown_tool", "Use a tool returned by tools/list.")
            self.validators[name].validate(arguments)
            async with self.lock:
                if name == "sciplot_read_result":
                    return _read_result(self.resources.get(arguments["uri"]))
                return await anyio.to_thread.run_sync(self._execute, name, arguments)
        except Exception as exc:
            return _text_result(error_payload(exc), is_error=True)


def create_server() -> Server[Any]:
    adapter = Adapter()

    async def list_tools(context: Any, params: Any) -> ListToolsResult:
        return ListToolsResult(tools=list(adapter.tools.values()))

    async def call_tool(context: Any, params: Any) -> CallToolResult:
        return await adapter.call(params.name, params.arguments or {})

    async def list_resources(context: Any, params: Any) -> ListResourcesResult:
        async with adapter.lock:
            return ListResourcesResult(resources=[Resource(**item.metadata()) for item in adapter.resources.list()])

    async def read_resource(context: Any, params: Any) -> ReadResourceResult:
        async with adapter.lock:
            try:
                item = adapter.resources.get(str(params.uri))
            except AdapterError as exc:
                raise MCPError(-32002, str(exc), {"code": exc.code}) from exc
            content: TextResourceContents | BlobResourceContents
            if item.mime_type == "application/json":
                content = TextResourceContents(uri=item.uri, mime_type=item.mime_type, text=item.data.decode())
            else:
                content = BlobResourceContents(uri=item.uri, mime_type=item.mime_type, blob=base64.b64encode(item.data).decode())
            return ReadResourceResult(contents=[content])

    return Server(
        "SciPlot", version=version("sciplot-core"), instructions=INSTRUCTIONS,
        on_list_tools=list_tools, on_call_tool=call_tool,
        on_list_resources=list_resources, on_read_resource=read_resource,
    )


async def serve_stdio() -> None:
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
