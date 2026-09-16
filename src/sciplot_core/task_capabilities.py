"""Small capability discovery and source-bound on-demand task schemas."""

from copy import deepcopy
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.studio_core.annotation_schema import annotation_operation_capabilities
from sciplot_core.task_choice_schema import table_region_schema
from sciplot_core.task_contract import TaskControlError, task_request_schema, task_response_schema
from sciplot_core.task_schema_compaction import compact_schema


def task_capabilities(*, section: str | None = None, name: str | None = None,
                      expected_contract_sha256: str | None = None, full: bool = False) -> dict[str, Any]:
    schemas = {"request": task_request_schema(), "response": task_response_schema(),
               "table_region": table_region_schema(),
               "operations": annotation_operation_capabilities()["operations_schema"]}
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
        "validation": "Each returned schema is standalone. Complete server validation and task/document/question/review revision guards remain required."}
