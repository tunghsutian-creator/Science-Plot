"""MCP tool metadata projects the shared operation schemas without redefining science."""

from __future__ import annotations

from typing import Any

from mcp.types import Tool, ToolAnnotations

from sciplot_core.studio_core.annotation_schema import annotation_operation_capabilities


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


def tool_definitions() -> list[Tool]:
    from sciplot_core.task_control import task_request_schema, task_response_schema
    from sciplot_core.task_group_contract import group_request_schema, group_responses_schema

    string = {"type": "string", "minLength": 1}
    sha = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    project = {"project": {**string, "description": "Canonical project or bound delivery path returned by SciPlot."}}
    figure = {**project, "figure_id": string}
    revision = {**figure, "expected_document_sha256": sha}
    output = {"output_dir": {**string, "description": "Optional new preview directory outside the source and project."}}
    definitions: list[Tool] = []

    def add(name: str, description: str, properties: dict[str, Any], required: list[str], *, read_only: bool = False) -> None:
        definitions.append(Tool(
            name=f"sciplot_{name}", description=description,
            input_schema=object_schema(properties, required),
            output_schema={"type": "object"},
            annotations=ToolAnnotations(
                read_only_hint=read_only,
                destructive_hint=name in {"task_start", "task_resume", "group_start", "group_resume", "edit_apply", "export"},
                idempotent_hint=read_only, open_world_hint=False,
            ),
        ))

    add("capabilities", "Read the versioned local control contract. No model or provider is started.", {}, [], read_only=True)
    add("task_start", "Start one authorized local create/edit/export task. The local runner carries mechanical steps; inspect a returned needs_input or needs_review state before resuming.",
        {"request": task_request_schema(), "task_dir": string}, ["request"])
    add("task_inspect", "Resume context from a saved task. This does not rerun or certify its historical result.",
        {"task": string}, ["task"], read_only=True)
    add("task_find", "Find creation receipts by exact original source path in the source-adjacent task history or an explicit tasks_root. Returns candidates and source currentness; inspect the selected task/project before continuing. Does not create or choose a project.",
        {"source": string, "tasks_root": string, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
        ["source"], read_only=True)
    add("task_resume", "Continue a saved task with a choice, bound preview response, or replacement operations. Use expected_operation_id for a ready preview; only blocked/previewing corrections use expected_preview_revision. Identical revision retries do not rerun. Existing user intent authorizes edits.",
        {"task": string, "response": task_response_schema()}, ["task", "response"])
    add("group_start", "Run 1–32 independent experiment tasks from an explicit list. Optional shared sample_style_preset applies to each created figure through ordinary reviewed edits. One item needing judgment does not stop others. Returns a local overview and native PNG resources; no model calls.",
        {"request": group_request_schema(), "group_dir": string}, ["request", "group_dir"])
    add("group_inspect", "Refresh an experiment group's current evidence and cached native previews. Does not advance tasks. Generated overview is read-only; pending candidates are marked separately from saved figures.",
        {"group": string}, ["group"])
    add("group_resume", "Continue pending/interrupted experiment tasks or supply per-item responses bound to each current task_dir. Preview responses require expected_operation_id. Never accepts previews or answers scientific questions automatically.",
        {"group": string, "responses": group_responses_schema()}, ["group"])
    add("project_inspect", "Query saved figures, current hashes and independent source/QA/delivery evidence. Pass figure_id for objects and exact editable field values; status ok is not readiness certification.",
        {**figure, "object_path": string, "full": {"type": "boolean", "default": False}}, ["project"], read_only=True)
    add("preview", "Render the current saved figure without changing it. Returns a PNG resource URI; use read_result to inspect the image on demand.",
        {**figure, **output}, ["project"])
    add("annotation_inspect", "Read current annotation IDs, coordinate units and graph bounds before creating or replacing annotations.",
        figure, ["project"], read_only=True)
    add("sample_style_capture", "Save reusable ordinary sample colors and line widths from the current audited figure. Returns a preset path and fingerprint for apply_sample_style_preset in edit_preview or task edit. No data, axes or annotations are copied.",
        {**figure, **output, "samples": {"type": "array", "minItems": 1, "maxItems": 100,
                                        "uniqueItems": True, "items": string}}, ["project"])
    add("edit_preview", "Preview a batch of advertised native style/annotation operations against the saved SHA. Read the returned image and scientific audit before apply; no raw data is changed.",
        {**revision, **output, "operations": annotation_operation_capabilities()["operations_schema"]},
        ["project", "expected_document_sha256", "operations"])
    add("edit_apply", "Apply the exact reviewed preview. Close all writable native project windows. Reusing the same preview safely checks its recorded outcome; apply does not export.",
        {**project, "review_path": string}, ["project", "review_path"])
    add("peaks", "Find local observed peak candidates in an explicit x window. Uses measured values without smoothing or scientific peak assignment; choose only returned candidates.",
        {**revision, "object_path": string,
         "window": object_schema({"min": {"type": "number"}, "max": {"type": "number"}, "unit": {"type": "string"}}, ["min", "max", "unit"]),
         "polarity": {"enum": ["maximum", "minimum"]}},
        ["project", "figure_id", "expected_document_sha256", "object_path", "window", "polarity"], read_only=True)
    add("export", "Export and publish the exact current complete project as PDF and 300 dpi TIFF. Read ready_to_use and current delivery evidence before handoff.", project, ["project"])
    add("operation", "Query a durable edit outcome after an uncertain reply. The current document may have changed since that operation.",
        {**project, "operation_id": sha}, ["project", "operation_id"], read_only=True)
    add("read_result", "Read a full JSON result or PNG image by a URI returned in this server connection. Arbitrary filesystem paths are not accepted.",
        {"uri": {"type": "string", "pattern": "^sciplot://result/[a-f0-9]{64}$"}}, ["uri"], read_only=True)
    return definitions
