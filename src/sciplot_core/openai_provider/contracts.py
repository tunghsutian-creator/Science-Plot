"""Declare OpenAI provider defaults, limits, schema, and instructions."""

from __future__ import annotations

import re
from typing import Any


DEFAULT_OPENAI_MODEL = "gpt-5.6"


DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


OPENAI_PROVIDER_ID = "openai_responses"


OPENAI_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})


_MAX_STREAM_LINE_BYTES = 262_144


_MAX_STREAM_EVENT_BYTES = 524_288


_MAX_STREAM_TEXT_BYTES = 262_144


_MAX_HTTP_ERROR_BYTES = 65_536


_MAX_MODEL_OPERATIONS = 16


_MAX_MODEL_WARNINGS = 16


_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


OPENAI_ASSISTANT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                "proposal",
                "needs_human_confirmation",
                "needs_rule_repair",
            ],
        },
        "understanding": {"type": "string"},
        "proposal_kind": {
            "type": "string",
            "enum": ["veusz_setting_operation_batch", "none"],
        },
        "rationale": {"type": "string"},
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "operation_type": {
                        "type": "string",
                        "enum": ["set_setting"],
                    },
                    "target_id": {"type": "string"},
                    "setting_path": {"type": "string"},
                    "value_json": {"type": "string"},
                },
                "required": [
                    "operation_type",
                    "target_id",
                    "setting_path",
                    "value_json",
                ],
                "additionalProperties": False,
            },
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "status",
        "understanding",
        "proposal_kind",
        "rationale",
        "operations",
        "warnings",
    ],
    "additionalProperties": False,
}


_PROVIDER_INSTRUCTIONS = """\
You are the bounded proposal planner in SciPlot's Veusz assistant. Return only
the requested JSON object. Never claim that an edit was applied. SciPlot will
preview, validate, and require the user to accept it.

For a proposal, use only exact target_id and setting_path pairs listed in
context.editing_capabilities.allowed_operations. Put the proposed setting value
in value_json as valid JSON. Do not invent paths, objects, datasets, columns,
coordinates, tools, or renderer commands. Do not change data authority.

If another object must be selected or scientific meaning is missing, return
needs_human_confirmation with proposal_kind none and an empty operations list.
If the request needs a SciPlot capability or deterministic rule that is not in
the catalog, return needs_rule_repair with proposal_kind none and an empty
operations list. Keep understanding and warnings concise and user-facing.
"""
