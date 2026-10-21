"""Small capability discovery and source-bound on-demand task schemas."""

from copy import deepcopy
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.studio_core.annotation_schema import annotation_operation_capabilities
from sciplot_core.task_choice_schema import table_region_schema
from sciplot_core.task_contract import TaskControlError, task_request_schema, task_response_schema
from sciplot_core.task_schema_compaction import compact_schema


def _schemas() -> dict[str, Any]:
    from sciplot_core.task_common_edits import common_edit_schema
    from sciplot_core.task_paper_contract import paper_request_schema

    from sciplot_core.task_semantic_contract import intent_schema

    return {"semantic_intent": intent_schema(), "request": task_request_schema(), "response": task_response_schema(),
            "table_region": table_region_schema(),
            "common_edit": common_edit_schema(), "paper_request": paper_request_schema(),
            "operations": annotation_operation_capabilities()["operations_schema"]}


def edit_context_capabilities(operations: list[str]) -> dict[str, Any]:
    """Project only requested operations into the existing edit request schema."""
    schemas = _schemas()
    variants = {item["properties"]["op"]["const"]: item
                for item in schemas["operations"]["items"]["oneOf"]}
    if (not operations or any(not isinstance(name, str) or name not in variants for name in operations)):
        raise TaskControlError("unknown_capability_name", "Choose one or more advertised edit operations.")
    names = list(dict.fromkeys(operations))
    request = deepcopy(next(item for item in schemas["request"]["oneOf"]
                            if item["properties"]["action"]["const"] == "edit"))
    request["properties"]["operations"]["items"]["oneOf"] = [variants[name] for name in names]
    response = next(item for item in schemas["response"]["oneOf"] if "accept_preview" in item["required"])
    return {"kind": "sciplot_task_capabilities", "version": 2,
            "contract_sha256": canonical_json_sha256(schemas), "task_version": 1,
            "operation_names": names, "request_schema": compact_schema(request),
            "response_schema": compact_schema(response)}


def task_capabilities(*, section: str | None = None, name: str | None = None,
                      expected_contract_sha256: str | None = None, full: bool = False) -> dict[str, Any]:
    schemas = _schemas()
    digest = canonical_json_sha256(schemas)
    if expected_contract_sha256 is not None and expected_contract_sha256 != digest:
        raise TaskControlError("stale_task_capabilities", "能力定义已变化，请重新读取当前能力索引。")
    if full and (section is not None or name is not None) or name is not None and section is None:
        raise TaskControlError("invalid_capability_query", "--full 与分节读取互斥；--name 需要 --section。")
    base = {"kind": "sciplot_task_capabilities", "version": 2,
            "contract_sha256": digest, "task_version": 1, "model_configuration_required": False}
    if full:
        return {**base, "request_schema": compact_schema(schemas["request"]),
                "response_schema": compact_schema(schemas["response"]),
                "table_region_query_schema": schemas["table_region"],
                "common_edit_schema": compact_schema(schemas["common_edit"]),
                "paper_request_schema": compact_schema(schemas["paper_request"])}
    if section is not None:
        if section not in schemas:
            raise TaskControlError("unknown_capability_section", "选择 request、response、operations、table_region、common_edit 或 paper_request。")
        schema = deepcopy(schemas[section])
        if name is not None:
            if section == "request":
                variants = [item for item in schema["oneOf"] if item["properties"]["action"]["const"] == name]
            elif section == "response":
                variants = [item for item in schema["oneOf"] if name in item["required"]]
            elif section == "operations":
                variants = [item for item in schema["items"]["oneOf"] if item["properties"]["op"]["const"] == name]
            else:
                variants = []
            if not variants:
                raise TaskControlError("unknown_capability_name", "名称不属于所选能力分节，请读取当前索引。")
            if section == "operations":
                schema["items"] = {"oneOf": variants}
            else:
                schema = variants[0] if len(variants) == 1 else {"oneOf": variants}
        response = {**base, "section": section, "name": name, "schema": compact_schema(schema)}
        if section == "common_edit":
            from sciplot_core.task_common_edits import common_edit_capabilities

            response["capabilities"] = common_edit_capabilities()
        if section == "request" and name == "create":
            from sciplot_core.materials_rules.catalog import get_rule
            from sciplot_core.materials_rules.impact_presentation import impact_statistics_by_template

            impact = get_rule("impact_metric")
            response["scientific_presentation"] = {
                "requirements": "curve_display and summary_statistic constrain existing execution; unsupported meanings are rejected before native creation.",
                "ordinary_impact": {"statistics_by_template": impact_statistics_by_template(), "templates": list(impact.presentation_templates),
                                    "raw_only_selection": {"templates": ["box", "box_strip"], "summary_calculation": "none"},
                                    "mean_sample_sd_n_selection": {"templates": ["bar"], "source_shape": "wide_metric_unit_sample_rows",
                                        "minimum_valid_n": 2, "missing_values": "explicit_exclude_when_missing",
                                        "n_disclosure": "source_spec_bound_summary_csv"}},
                "semantic_xy": {"curve_display": "raw_overlay", "summary_statistic": "raw_only", "x_scale": "numeric",
                                "omitted_rule_id": "ordinary_xy", "source_context": "Optional user acquisition context is archived verbatim; it does not select an experiment or calculation."},
                "ordinary_categorical": {"request_field": "categorical", "rule_id": None,
                    "source": "one_original_file_and_explicit_table_columns",
                    "given_values": "point_line_without_errors_or_aggregation",
                    "replicates": "existing_mean_sample_sd_bar_minimum_valid_n_2",
                    "mean_sample_sd_n": "source_spec_bound_summary_csv",
                    "units": "explicit_per_selected_value_column_same_axis_unit",
                    "series_style_fields": {"given_values": ["color", "marker", "marker_fill_mode"],
                        "mean_sample_sd": ["color"], "mean_sample_sd_n": ["color"]},
                    "legend_columns_and_corners": "given_values_native_key_only; summaries retain existing fixed categorical legend",
                    "missing_values": "explicit_exclude_when_missing"},
                "limitations": ["arbitrary categorical pivot", "row- or Metric-scoped unit inference", "mechanical curve-only figure set"],
            }
        return response
    return {**base, "sections": {
        "request": list(dict.fromkeys(item["properties"]["action"]["const"] for item in schemas["request"]["oneOf"])),
        "semantic_intent": "Coordinates/stages/display.",
        "response": list(dict.fromkeys(key for item in schemas["response"]["oneOf"] for key in item["required"] if not key.startswith("expected_"))),
        "operations": [item["properties"]["op"]["const"] for item in schemas["operations"]["items"]["oneOf"]],
        "common_edit": "Bounded presentation intents; coverage-specific.",
        "paper_request": "Ordered figures and version guards.",
        "table_region": "Original cells <=128x64."},
        "read_schema": {"cli": "task capabilities --section SECTION --name NAME --expected-contract SHA --json",
                        "mcp": "sciplot_task_capabilities", "name_optional": True,
                        "full_cli": "task capabilities --full --json"},
        "saved_edit_context": {
            "cli": "task edit-context TASK_OR_PROJECT --operation NAME [--operation NAME ...] [--figure FIGURE_ID] --json",
            "scope": "Read current targets and selected edit schemas together."},
        "typed_entries": {
            "edit": "task edit TARGET --intent EXACT --task-dir STABLE_PATH --json",
            "continue": "task continue SOURCE [--search-root ROOT --target EXACT] --json",
            "paper": "task paper capabilities [--project PROJECT --figure ID] --json",
            "create": "task create SOURCE [--rule RULE --template TEMPLATE --profile PATH --out PATH] --json",
            "semantic_create": "task create --source FILE ... --x time --y mass ... --json",
            "style": "task style TARGET (--all-samples | --sample EXACT ...) [--width WIDTH] [--color COLOR] [--figure FIGURE_ID] --json",
            "accept_preview": "task resume TASK --accept-preview --expected-operation-id CURRENT_ID --json",
            "retry": "task resume TASK --retry --json",
            "scope": "Existing guards apply; review previews."},
        "specialized_routes": {"rheology_tts": {
            "cli": "rheology capabilities --json",
            "scope": "AI-prepared TTS/export/style; compatibility analysis."}},
        "validation": "Complete validation remains active."}
