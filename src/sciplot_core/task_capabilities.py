"""Small capability discovery and source-bound on-demand task schemas."""

from copy import deepcopy
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.studio_core.annotation_schema import annotation_operation_capabilities
from sciplot_core.task_choice_schema import table_region_schema
from sciplot_core.task_contract import TaskControlError, task_request_schema, task_response_schema
from sciplot_core.task_schema_compaction import compact_schema


def _schemas() -> dict[str, Any]:
    return {"request": task_request_schema(), "response": task_response_schema(),
            "table_region": table_region_schema(),
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
                "table_region_query_schema": schemas["table_region"]}
    if section is not None:
        if section not in schemas:
            raise TaskControlError("unknown_capability_section", "选择 request、response、operations 或 table_region。")
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
        return {**base, "section": section, "name": name, "schema": compact_schema(schema)}
    return {**base, "sections": {
        "request": [item["properties"]["action"]["const"] for item in schemas["request"]["oneOf"]],
        "response": list(dict.fromkeys(key for item in schemas["response"]["oneOf"] for key in item["required"] if not key.startswith("expected_"))),
        "operations": [item["properties"]["op"]["const"] for item in schemas["operations"]["items"]["oneOf"]],
        "table_region": "Original cells, up to 128 rows by 64 columns, current question required."},
        "read_schema": {"cli": "task capabilities --section SECTION --name NAME --expected-contract SHA --json",
                        "mcp": "sciplot_task_capabilities", "name_optional": True,
                        "full_cli": "task capabilities --full --json"},
        "saved_edit_context": {
            "cli": "task edit-context TASK_OR_PROJECT --operation NAME [--operation NAME ...] [--figure FIGURE_ID] --json",
            "scope": "Read runtime, current saved targets and selected edit schemas once; no task or project mutation."},
        "specialized_routes": {"rheology_tts": {
            "cli": "rheology capabilities --json",
            "scope": "AI-prepared source-bound TTS plotting, exact saved export and revision-bound native style restoration; analysis is a legacy compatibility route."}},
        "validation": "Each returned schema is standalone. Complete server validation and task/document/question/review revision guards remain required."}
