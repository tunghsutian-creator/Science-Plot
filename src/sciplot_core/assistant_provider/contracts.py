"""Declare versioned assistant contracts, limits, and capability sets."""

from __future__ import annotations

import re


ASSISTANT_PROVIDER_DESCRIPTOR_KIND = "sciplot_assistant_provider_descriptor"


ASSISTANT_PROVIDER_DESCRIPTOR_VERSION = 1


ASSISTANT_REQUEST_KIND = "sciplot_assistant_request"


ASSISTANT_REQUEST_VERSION = 1


ASSISTANT_PROGRESS_KIND = "sciplot_assistant_progress"


ASSISTANT_PROGRESS_VERSION = 1


ASSISTANT_RESPONSE_KIND = "sciplot_assistant_response"


ASSISTANT_RESPONSE_VERSION = 1


ASSISTANT_PROPOSAL_KINDS = frozenset({"veusz_setting_operation_batch"})


ASSISTANT_PROVIDER_CAPABILITIES = frozenset({*ASSISTANT_PROPOSAL_KINDS, "cancellation"})


ASSISTANT_PROGRESS_STAGES = frozenset(
    {
        "queued",
        "understanding",
        "planning",
        "proposing",
        "validating",
        "waiting",
    }
)


ASSISTANT_RESPONSE_STATUSES = frozenset(
    {
        "proposal",
        "needs_human_confirmation",
        "needs_rule_repair",
        "cancelled",
    }
)


ASSISTANT_CONTEXT_KIND = "sciplot_veusz_assistant_context"


ASSISTANT_CONTEXT_VERSION = 3


ASSISTANT_CONTEXT_COMPATIBLE_VERSIONS = frozenset({2, ASSISTANT_CONTEXT_VERSION})


ASSISTANT_DATA_POLICY = "structured_context_no_raw_dataset_arrays"


ASSISTANT_VISUAL_PREVIEW_MAX_BYTES = 4 * 1024 * 1024


ASSISTANT_EDITABLE_FIELD_EDITORS = frozenset(
    {
        "boolean",
        "choice",
        "color",
        "distance",
        "float_list",
        "integer",
        "number",
        "number_or_auto",
        "scalar_list",
        "text",
    }
)


_SAFE_PROVIDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")


_SHA256 = re.compile(r"[0-9a-f]{64}")


ASSISTANT_MAX_INTENT_LENGTH = 4000


_MAX_UNDERSTANDING_LENGTH = 2000


_MAX_PROGRESS_MESSAGE_LENGTH = 320


_MAX_WARNING_LENGTH = 500


_MAX_CONTEXT_BYTES = 256_000


_MAX_CONTEXT_OBJECTS = 100_000


_MAX_CONTEXT_OBJECT_TYPES = 128


_MAX_REVIEW_ANNOTATIONS = 128


_MAX_QA_IDS = 256


_MAX_EDITING_CAPABILITIES = 128


_MAX_CAPABILITY_CHOICES = 256


_MAX_CAPABILITY_VALUE_ITEMS = 128


_MAX_CAPABILITY_VALUE_BYTES = 16_384


_MAX_VISUAL_PREVIEW_BASE64_LENGTH = ((ASSISTANT_VISUAL_PREVIEW_MAX_BYTES + 2) // 3) * 4
