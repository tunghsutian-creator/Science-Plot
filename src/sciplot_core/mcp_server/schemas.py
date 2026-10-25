"""MCP tool metadata projects the shared operation schemas without redefining science."""

from __future__ import annotations

from typing import Any

from mcp.types import Tool, ToolAnnotations

from sciplot_core.studio_core.annotation_schema import annotation_operation_capabilities
from sciplot_core.task_schema_compaction import compact_schema


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


def tool_definitions() -> list[Tool]:
    from sciplot_core.plot_document.schema import patch_schema
    from sciplot_core.plot_engine.contracts import (
        create_schema,
        decide_schema,
        resume_schema,
        rollback_schema,
    )
    from sciplot_core.plot_engine.typed_intent import intent_schema
    from sciplot_core.plot_engine.managed_delivery_contract import managed_delivery_schema
    from sciplot_core.task_choice_schema import table_region_schema
    from sciplot_core.task_comparison_contract import (
        comparison_request_schema,
        comparison_selection_schema,
    )
    from sciplot_core.task_control import task_request_schema, task_response_schema
    from sciplot_core.task_common_edits import common_edit_schema
    from sciplot_core.task_paper_contract import paper_request_schema
    from sciplot_core.task_group_contract import (
        group_request_schema,
        group_responses_schema,
    )

    string = {"type": "string", "minLength": 1}
    sha = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    full = {"type": "boolean", "default": False, "description": "Return the detailed response. Default receipts are compact; full JSON is also available through the returned resource URI."}
    project = {"project": {**string, "description": "Canonical project or bound delivery path returned by SciPlot."}}
    figure = {**project, "figure_id": string}
    revision = {**figure, "expected_document_sha256": sha}
    output = {"output_dir": {**string, "description": "Optional new preview directory outside the source and project."}}
    definitions: list[Tool] = []

    def add(name: str, description: str, properties: dict[str, Any], required: list[str], *,
            read_only: bool = False, idempotent: bool = False, destructive: bool = False) -> None:
        definitions.append(Tool(
            name=f"sciplot_{name}", description=description,
            input_schema=compact_schema(object_schema(properties, required)),
            output_schema={"type": "object"},
            annotations=ToolAnnotations(
                read_only_hint=read_only,
                destructive_hint=destructive or name in {"task_start", "task_resume", "group_start", "group_resume", "comparison_resume", "comparison_select", "edit_apply", "export"},
                idempotent_hint=read_only or idempotent, open_world_hint=False,
            ),
        ))

    semantic_path = {**string, "pattern": "^/"}
    description = {"oneOf": [
        object_schema({"scope": {"const": "summary"}}, ["scope"]),
        object_schema({"scope": {"const": "edit"}, "target": string, "property": string},
                      ["scope", "target", "property"]),
    ], "description": "Use summary or edit only when object_operations advertises that scope. Edit selects one advertised stable target/property. Omit for unknown authority or a full response; LegacyPlot native coverage remains explicit."}
    semantic_plot = {"plot": {**semantic_path, "description": "Exact absolute plot target returned in plot_objects or project_open: a document directory or a supported bound native figure VSZ."}}
    add("plot_deliver", "Package an ordered list of exact current ManagedPlot revisions into a new native-snapshot delivery and ZIP. Reuses per-plot audited export and native Save, retains original source bytes, reports partial completion and resumes the identical request. Never replaces an existing destination or claims a portable ManagedPlot registry. Local semantic continuation and independent native editing remain distinct.",
        {"request": managed_delivery_schema()}, ["request"], idempotent=True)
    add("project_open", "Open one existing saved figure. A known ManagedPlot or supported bound native suite object advertises summary/edit scopes and legal deltas in object_operations. A multi-figure suite requires figure_id or its exact returned VSZ. Unknown authority uses full open. Does not overwrite or promote native coverage.",
        {"target": semantic_path, "figure_id": string, "description": description}, ["target"], idempotent=True)
    add("plot_describe", "Read current object capabilities and values without rebuilding science. When advertised, use scope edit for one target/property and its exact schema. Supported native suite values come from the current selected VSZ. Omit description for full state; stale inputs and pending work remain explicit.",
        {**semantic_plot, "description": description}, ["plot"], read_only=True)
    add("plot_create", "Expert Template/Binding creation through the existing semantic lifecycle; ordinary attachment plotting uses task_start sources+intent. Source-only compatibility remains. Keep idempotency_key unchanged on retry; unresolved scientific choices return a decision.",
        {"request": create_schema(), "project": {**semantic_path, "description": "Optional explicit existing project root for attached Managed Template/Binding creation; outside the scientific request. No project discovery, initialization or repair."}}, ["request"], idempotent=True, destructive=True)
    add("plot_patch", "Apply one atomic semantic change batch to exact stable object IDs and base_revision. Local engine classifies risk, checks scientific invariants and compiles/exports. Reuse the identical idempotency_key after a lost reply; never swap data bindings through a presentation patch.",
        {**semantic_plot, "request": patch_schema()}, ["plot", "request"], idempotent=True, destructive=True)
    add("plot_intent", "After current ManagedPlot FigureSpec v2 state, plan then apply one literal axis label or annotation text edit. Select an advertised stable target ID or unique exact current label, plot ID, revision and idempotency key. Plan is read-only and returns unit/anchor context; apply uses the existing plot patch transaction. Not for LegacyPlot.",
        {**semantic_plot, "request": intent_schema()}, ["plot", "request"], idempotent=True, destructive=True)
    add("plot_resume", "Explicitly continue one existing semantic transaction using its original plot ID, base revision and idempotency key after a lost reply or daemon restart. Does not create a transaction or accept a pending review. Original source/native guards and export-only recovery remain active.",
        {**semantic_plot, "request": resume_schema()}, ["plot", "request"], idempotent=True, destructive=True)
    add("plot_render", "Render the current semantic document through its native backend; reuses valid current cache and preserves the saved scientific state.",
        semantic_plot, ["plot"], idempotent=True)
    add("plot_export", "Export the current selected object through its authority owner. A supported bound native figure exports independently of optional suite figures. A prior export failure continues without applying a patch again. Handoff requires ready evidence.",
        semantic_plot, ["plot"], idempotent=True, destructive=True)
    add("plot_rollback", "Restore an explicit historical presentation as a new revision, bound to base_revision and idempotency_key. Preserves revision history and scientific state.",
        {**semantic_plot, "request": rollback_schema()}, ["plot", "request"], idempotent=True, destructive=True)
    add("plot_decide", "Answer the specific current local decision. A review uses decision_id and base_revision; a creation question carries its existing source-bound response. Never invent scientific choices.",
        {**semantic_plot, "request": decide_schema()}, ["plot", "request"], idempotent=True, destructive=True)
    add("capabilities", "Read the versioned local control contract. No model or provider is started.", {}, [], read_only=True)
    from sciplot_core.panel_assembly.service import composition_request_schema

    add("compose_capabilities", "Read the compact local panel assembly intent contract. Placement never calls a model or changes scientific state.", {}, [], read_only=True)
    add("compose", "Create, inspect, arrange or export a local panel layout. Add/replace binds exact existing figures/images locally; apply requires expected_revision. Export reflows supported native panels at target mm, preserves text sizes and rejects source drift. Dragging and spacing use the same deterministic local owner.",
        {"request": composition_request_schema()}, ["request"], destructive=True)
    add("task_capabilities", "Read a small task capability index or one exact schema. Pass its contract_sha256 as expected_contract_sha256 when fetching sections; server validation remains complete.",
        {"section": {"enum": ["request", "response", "operations", "table_region", "common_edit", "paper_request", "semantic_intent"]}, "name": string,
         "expected_contract_sha256": sha, "full": {"type": "boolean"}}, [], read_only=True)
    add("task_start", "Start one authorized local create/edit/export/update_source task. Semantic create uses sources+small intent, returns one original-source plan and scientific decisions; the program expands Binding/FigureSpec locally. Answer source-bound column questions; inspect all returned source-update or edit candidate PNGs before resuming.",
        {"request": task_request_schema(), "task_dir": string, "full": full}, ["request"])
    common_schema = common_edit_schema()
    add("task_edit", "Execute exact common palette, typography or supported legend clauses through the existing plot transaction. Preserve data/scientific state. For recovery after a lost first reply, choose a stable task_dir before the first call and reuse it with identical intent. Existing pending/review/export continuations remain authoritative; unavailable properties are rejected.",
        common_schema["properties"], common_schema["required"], destructive=True)
    add("task_continue", "Read current saved originals within explicit bounded search_roots, distinguish export snapshots and return existing guarded edit/recovery arguments. Exact source hashes only filter candidates; copies/versions need explicit target selection. No rebinding, edit or regeneration occurs.",
        {"source": string, "search_roots": {"type": "array", "minItems": 1, "maxItems": 20, "items": string},
         "tasks_root": string, "target": string, "figure_id": string}, ["source"], read_only=True)
    add("paper_capabilities", "Read the closed paper-selection schema; with exact project and figure_id, obtain current source/native version guards. No exports or source changes.",
        {"project": string, "figure_id": string}, [], read_only=True)
    add("paper_start", "Package an ordered list of exact selected figures across projects as PDF/TIFF, portable editable VSZ and sealed source-version evidence. Original projects stay unchanged; existing destinations are rejected. Reuse paper_dir with the identical request after an uncertain reply.",
        {"request": paper_request_schema(), "paper_dir": string}, ["request", "paper_dir"], idempotent=True, destructive=True)
    add("paper_inspect", "Inspect the original paper execution and current selected-source/delivery evidence. Historical completion is separate from currentness; no export or retry occurs.",
        {"paper": string}, ["paper"], read_only=True)
    add("paper_resume", "Resume only unfinished exact selected-figure exports or publication in the original paper_dir. Sealed items are rechecked and reused; changed sources or destination contents are blocked. Does not select new versions or overwrite an existing unrelated package.",
        {"paper": string}, ["paper"], idempotent=True, destructive=True)
    add("task_inspect", "Resume context from a saved task. This does not rerun or certify its historical result.",
        {"task": string, "full": full}, ["task"], read_only=True)
    add("task_table_region", "Read up to 128 original rows by 64 columns, bound to the current table question and source bytes. Does not change the question or select cells.",
        {"task": string, "query": table_region_schema()}, ["task", "query"], read_only=True)
    add("task_find", "Find creation receipts by exact original source path in the source-adjacent task history or an explicit tasks_root. Returns candidates and source currentness; inspect the selected task/project before continuing. Does not create or choose a project.",
        {"source": string, "tasks_root": string, "search_roots": {"type": "array", "minItems": 1, "maxItems": 20, "items": string},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
        ["source"], read_only=True)
    add("task_resume", "Continue a saved task. Semantic confirm_plan uses expected_question_id and listed choices; revise_intent uses the current intent_revision and retains prior attempts. Retry resumes the same frozen attempt/export. Column answers require expected_question_id; source-update decisions require expected_revision_id. Style previews use expected_operation_id and blocked preview corrections use expected_preview_revision. Existing user intent authorizes the requested work.",
        {"task": string, "response": task_response_schema(), "full": full}, ["task", "response"])
    add("group_start", "Run 1–32 independent experiment tasks from an explicit list. Optional shared sample_style_preset applies to each created figure through ordinary reviewed edits. One item needing judgment does not stop others. Returns a local overview and native PNG resources; no model calls.",
        {"request": group_request_schema(), "group_dir": string}, ["request", "group_dir"])
    add("group_inspect", "Refresh an experiment group's current evidence and cached native previews. Does not advance tasks. Generated overview is read-only; pending candidates are marked separately from saved figures.",
        {"group": string}, ["group"])
    add("group_resume", "Continue pending/interrupted experiment tasks or supply per-item responses bound to each current task_dir. Preview responses require expected_operation_id. Never accepts previews or answers scientific questions automatically.",
        {"group": string, "responses": group_responses_schema()}, ["group"])
    add("comparison_start", "Generate 2–8 independent native alternatives from the same saved figure baseline. No candidate is applied. Returns original/candidate PNG resources, compact factual differences and a local comparison page. Caller supplies and judges supported operations; no model calls.",
        {"request": comparison_request_schema(), "comparison_dir": string}, ["request", "comparison_dir"])
    add("comparison_inspect", "Read frozen alternatives, their validity and current project evidence. Does not render or advance tasks; queries reuse stored native images.",
        {"comparison": string}, ["comparison"])
    add("comparison_resume", "Resume interrupted candidate generation, or finish a previously frozen explicit selection. Never chooses a candidate. A changed baseline requires a new comparison.",
        {"comparison": string}, ["comparison"])
    add("comparison_select", "After viewing alternatives, select exactly one candidate or baseline using the current comparison_id. Only this candidate is applied, with optional export from the original request. Repeating the same selection is recoverable; choosing a second candidate is rejected.",
        {"comparison": string, "selection": comparison_selection_schema()}, ["comparison", "selection"])
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
