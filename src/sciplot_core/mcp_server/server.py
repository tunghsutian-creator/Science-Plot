"""Official MCP stdio transport around serialized deterministic domain calls."""

from __future__ import annotations

import base64
import json
import sys
from contextlib import redirect_stdout
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path
from typing import Any

import anyio
from jsonschema import Draft202012Validator
from mcp import MCPError
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    BlobResourceContents,
    CallToolResult,
    ImageContent,
    ListResourcesResult,
    ListToolsResult,
    ReadResourceResult,
    Resource,
    ResourceLink,
    TextContent,
    TextResourceContents,
)

from sciplot_core.mcp_server.errors import AdapterError, error_payload
from sciplot_core.mcp_server.resources import ResourceSnapshot, ResourceStore
from sciplot_core.mcp_server.schemas import ToolProfile, discovery_tool, tool_definitions
from sciplot_core.mcp_server.services import invoke_owner
from sciplot_core.studio_core.control_results import compact_result

INSTRUCTIONS = (
    "SciPlot executes local scientific plotting without calling a model. Prefer "
    "task_start for new attachment plotting, with sources plus a small semantic intent "
    "for coordinates, exact Test/block selection, stages and display choices. The task expands original source "
    "facts and existing Managed contracts; task_resume answers only advertised "
    "scientific decisions, revises a rejected draft or resumes its frozen attempt. "
    "Do not write a low-level FigureTemplate for this workflow. Explicit expert "
    "Template/Binding construction uses plot_create; source-only compatibility "
    "creation remains available. Use project_open for saved-figure edits. For a "
    "previously identified ManagedPlot, open with description "
    "scope summary, then request only the chosen target/property with plot_describe "
    "scope edit before plot_patch. For an exact FigureSpec v2 axis title, major tick list or "
    "annotation text, plot_intent plan then apply uses the same patch transaction. "
    "Creation plot_objects also continues supported bound native suite figures: "
    "inspect object_operations and current advertised values, then send only legal "
    "presentation deltas. Do not resend coordinates or recreate unselected figures. "
    "If authority is unknown or LegacyPlot without advertised scoped support, use the full open; retain its native "
    "coverage, never convert it just for compact reads. Use a .sciplot file summary for plot_intent "
    "axis, legend display name or ordinary XY line color edits, or selected PDF/TIFF handoff through plot_export. Archived native plots returned as read_only require "
    "a separate converted copy for new edits. Check status, changed "
    "inputs and pending work before editing. Use returned stable IDs and revision; "
    "keep idempotency_key unchanged on retry. Follow local decision and export "
    "receipts instead of reapplying committed work. plot_deliver packages exact current "
    "ManagedPlot revisions as independent native snapshots. For relocation of an exact "
    "existing Store, use project_bundle_export and project_bundle_import for a directory bundle, or "
    "project_bundle_export with single_file true for one directly openable .sciplot file. Both pack the whole "
    "project with its history and exclude host permissions. In an ordinary XY task_start, use project_file for a new .sciplot "
    "file or append_to with expected_generation from project_open for an existing file. Use the saved figure ID to reopen. "
    "Inspect existing saved "
    "projects instead of creating them again. Compatibility native-edit tools "
    "require real figure/object IDs and the saved SHA. Read candidate PNG resources and scientific "
    "audits before accepting previews. Keep raw values, units and sample identities. "
    "Ask only for unresolved meaning or scope. Queries and edits do not certify "
    "delivery; handoff requires ready export evidence. Resource URIs are immutable "
    "snapshots limited to this server connection; inspect again for current state."
)


DAILY_INSTRUCTIONS = (
    "SciPlot plots locally without calling a model. For new source data use "
    "task_start; retrieve only the needed contract section from task_capabilities. "
    "Answer only current scientific questions with task_resume and returned guard IDs. "
    "For an existing figure use project_open first if its authority is unknown. "
    "A sciplot_project_file_summary identifies the saved figure in a .sciplot file. "
    "Pass the file as plot and choose from its edit_targets for an axis title, major tick, legend display name or ordinary XY line color edit via plot_intent. "
    "To save the first ordinary XY figure, use task_start with sources, intent and project_file. To append to an existing .sciplot, "
    "use append_to and expected_generation from project_open instead. No request file or export is needed. Open the new figure using next_step.arguments. "
    "To add a curve to that same saved figure instead, use project_file_add_series: plan, inspect the exact source selection, then apply. "
    "For a selected PDF/TIFF handoff use plot_export. "
    "If it returns an archived read_only native figure, call sciplot_project_legacy_redraw with its target and a new output directory; "
    "for an edit, use sciplot_project_legacy_convert to create a separate supported XY copy first. "
    "For an editable figure use task_edit for common changes, or plot_describe for exact "
    "capabilities. Use summary/edit scopes only when advertised. "
    "Review preview resources before accepting; follow returned recovery and export "
    "receipts without reapplying an edit. After reconnecting, reopen the same figure to read "
    "its pending preview in this connection. plot_deliver makes paper snapshots; "
    "project_bundle_export with single_file true saves the same whole project in one .sciplot file; "
    "for a directory bundle use project_bundle_export then project_bundle_import. "
    "project_save_as makes one selected Managed figure an independent editable copy. "
    "project_file_save_as creates a new independently editable .sciplot with all supported current figures. "
    "For existing PDF diagrams use compose with "
    "export-pdf for a standalone PDF. Resources are scoped to this server connection. "
    "For specialized workflows or the full upfront schemas reconnect with --profile expert."
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
    if (payload.get("kind") == "sciplot_plot_description" and payload.get("plot_type") == "ManagedPlot"
            and payload.get("status") == "current"):
        recovery = payload.get("recovery")
        if isinstance(recovery, dict) and recovery.get("phase") == "needs_review":
            preview = recovery.get("preview")
            if (isinstance(preview, dict) and isinstance(preview.get("path"), str)
                    and isinstance(preview.get("sha256"), str)):
                return preview
    # Task receipts may wrap the native edit review, but never inspect their
    # request payload for paths: only owner-generated result metadata is eligible.
    review = payload.get("review")
    if isinstance(review, dict):
        return _preview_artifact(review)
    return None


class Adapter:
    def __init__(self, profile: ToolProfile = "expert") -> None:
        self.profile = profile
        full = {item.name: item for item in tool_definitions(profile)}
        self.tools = {name: discovery_tool(item) for name, item in full.items()} if profile == "daily" else full
        self.validators = {name: Draft202012Validator(item.input_schema) for name, item in full.items()}
        self.resources = ResourceStore()
        self.lock = anyio.Lock()

    def _repair_result(self, payload: dict[str, Any]) -> CallToolResult:
        """A rejected old answer still exposes the current owner-bound review."""
        payload = deepcopy(payload)
        repair = payload.get("repair")
        links: list[ResourceSnapshot] = []
        if isinstance(repair, dict):
            preview = _preview_artifact(repair)
            artifacts = ([{"preview": preview}] if preview is not None else [])
            artifacts.extend(repair.get("previews") or [])
            for artifact in artifacts:
                try:
                    preview = artifact["preview"]
                    snapshot = self.resources.add_preview(Path(preview["path"]), expected_sha256=preview.get("sha256"))
                    if "previews" in repair:
                        entry: dict[str, Any] = {key: artifact[key] for key in ("figure_id", "scope") if key in artifact}
                        entry["uri"] = snapshot.uri
                        repair.setdefault("preview_resources", []).append(entry)
                    else:
                        repair["preview_resource"] = snapshot.uri
                    links.append(snapshot)
                except (AdapterError, OSError) as exc:
                    payload.setdefault("resource_warnings", []).append(str(exc))
        result = _text_result(payload, is_error=True)
        result.content.extend(ResourceLink(**item.metadata()) for item in links)
        return result

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
        artifacts = ([{"preview": preview_artifact}] if preview_artifact is not None else [])
        comparison = payload.get("kind") == "sciplot_task_comparison_result"
        grouped = comparison or payload.get("kind") == "sciplot_task_group_result"
        source_revision = payload.get("kind") == "sciplot_task" and isinstance(payload.get("previews"), list)
        if grouped or source_revision:
            artifacts = payload["previews"]
        group_resources = []
        for artifact in artifacts:
            try:
                preview = artifact["preview"]
                snapshot = self.resources.add_preview(Path(preview["path"]), expected_sha256=preview.get("sha256"))
                if grouped or source_revision:
                    keys = (("figure_id", "scope") if source_revision else
                            ("candidate_id", "figure_id", "scope") if comparison else ("item_id", "figure_id", "scope"))
                    group_resources.append({**{key: artifact[key] for key in keys}, "uri": snapshot.uri})
                else:
                    compact = {**compact, "preview_resource": snapshot.uri}
                links.append(snapshot)
            except (AdapterError, OSError) as exc:
                # Resource presentation failure does not turn a completed domain
                # mutation into an ambiguous failed action.
                warnings.append(str(exc))
        if grouped or source_revision:
            compact = {**compact, "preview_resources": group_resources}
        if warnings:
            compact = {**compact, "resource_warnings": warnings}
        result = _text_result(compact, is_error=compact.get("status") in {"error", "failed", "blocked", "partial"})
        result.content.extend(ResourceLink(**item.metadata()) for item in links)
        return result

    async def call(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        try:
            if name not in self.tools:
                hint = " For specialized tools, reconnect with --profile expert." if self.profile == "daily" else ""
                raise AdapterError("unknown_tool", "Use a tool returned by tools/list." + hint)
            self.validators[name].validate(arguments)
            async with self.lock:
                if name == "sciplot_read_result":
                    return _read_result(self.resources.get(arguments["uri"]))
                return await anyio.to_thread.run_sync(self._execute, name, arguments)
        except Exception as exc:  # noqa: BLE001 - MCP must encode all owner failures as tool errors.
            payload = error_payload(exc)
            from jsonschema.exceptions import ValidationError

            if isinstance(exc, ValidationError) and name in {"sciplot_task_start", "sciplot_task_resume"}:
                from sciplot_core.task_repair import adapter_repair

                repair = await anyio.to_thread.run_sync(adapter_repair, name, arguments, exc)
                if repair is not None:
                    payload["repair"] = repair
            async with self.lock:
                return self._repair_result(payload)


def create_server(profile: ToolProfile = "expert") -> Server[Any]:
    adapter = Adapter(profile)

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
        "SciPlot", version=version("sciplot-core"), instructions=DAILY_INSTRUCTIONS if profile == "daily" else INSTRUCTIONS,
        on_list_tools=list_tools, on_call_tool=call_tool,
        on_list_resources=list_resources, on_read_resource=read_resource,
    )


async def serve_stdio(profile: ToolProfile = "expert") -> None:
    server = create_server(profile)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
