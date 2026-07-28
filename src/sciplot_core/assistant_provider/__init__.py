"""Bounded assistant provider contract API and compatibility facade."""

from __future__ import annotations

from sciplot_core.assistant_provider.contracts import (  # noqa: F401
    ASSISTANT_PROVIDER_DESCRIPTOR_KIND,
    ASSISTANT_PROVIDER_DESCRIPTOR_VERSION,
    ASSISTANT_REQUEST_KIND,
    ASSISTANT_REQUEST_VERSION,
    ASSISTANT_PROGRESS_KIND,
    ASSISTANT_PROGRESS_VERSION,
    ASSISTANT_RESPONSE_KIND,
    ASSISTANT_RESPONSE_VERSION,
    ASSISTANT_PROPOSAL_KINDS,
    ASSISTANT_PROVIDER_CAPABILITIES,
    ASSISTANT_PROGRESS_STAGES,
    ASSISTANT_RESPONSE_STATUSES,
    ASSISTANT_CONTEXT_KIND,
    ASSISTANT_CONTEXT_VERSION,
    ASSISTANT_CONTEXT_COMPATIBLE_VERSIONS,
    ASSISTANT_DATA_POLICY,
    ASSISTANT_VISUAL_PREVIEW_MAX_BYTES,
    ASSISTANT_EDITABLE_FIELD_EDITORS,
    _SAFE_PROVIDER_ID,
    _SHA256,
    ASSISTANT_MAX_INTENT_LENGTH,
    _MAX_UNDERSTANDING_LENGTH,
    _MAX_PROGRESS_MESSAGE_LENGTH,
    _MAX_WARNING_LENGTH,
    _MAX_CONTEXT_BYTES,
    _MAX_CONTEXT_OBJECTS,
    _MAX_CONTEXT_OBJECT_TYPES,
    _MAX_REVIEW_ANNOTATIONS,
    _MAX_QA_IDS,
    _MAX_EDITING_CAPABILITIES,
    _MAX_CAPABILITY_CHOICES,
    _MAX_CAPABILITY_VALUE_ITEMS,
    _MAX_CAPABILITY_VALUE_BYTES,
    _MAX_VISUAL_PREVIEW_BASE64_LENGTH,
)
from sciplot_core.assistant_provider.text_validation import (  # noqa: F401
    _now,
    _required_text,
    _optional_text,
    _free_text,
    _uuid_text,
    _provider_id,
    _timestamp,
    _sha256,
    canonical_payload_sha256,
)
from sciplot_core.assistant_provider.visual_preview import (  # noqa: F401
    _png_dimensions,
    _validate_visual_preview,
)
from sciplot_core.assistant_provider.context_documents import (  # noqa: F401
    _text_list,
    _validate_document_inventory,
    _validate_review,
)
from sciplot_core.assistant_provider.context_qa import (  # noqa: F401
    _validate_qa,
)
from sciplot_core.assistant_provider.capabilities import (  # noqa: F401
    _validate_capability_value,
    _optional_capability_number,
    _validate_editing_capabilities,
)
from sciplot_core.assistant_provider.context_validation import (  # noqa: F401
    _validate_context,
)
from sciplot_core.assistant_provider.descriptor import (  # noqa: F401
    AssistantProviderDescriptor,
)
from sciplot_core.assistant_provider.request import (  # noqa: F401
    AssistantRequest,
)
from sciplot_core.assistant_provider.progress import (  # noqa: F401
    AssistantProgressEvent,
)
from sciplot_core.assistant_provider.response import (  # noqa: F401
    AssistantResponse,
)
from sciplot_core.assistant_provider.provider import (  # noqa: F401
    AssistantCancelled,
    AssistantCancellationToken,
    AssistantProgressCallback,
    AssistantProvider,
)

__all__ = [
    "ASSISTANT_CONTEXT_KIND",
    "ASSISTANT_CONTEXT_VERSION",
    "ASSISTANT_DATA_POLICY",
    "ASSISTANT_MAX_INTENT_LENGTH",
    "ASSISTANT_PROGRESS_STAGES",
    "ASSISTANT_PROPOSAL_KINDS",
    "ASSISTANT_PROVIDER_CAPABILITIES",
    "ASSISTANT_RESPONSE_STATUSES",
    "ASSISTANT_VISUAL_PREVIEW_MAX_BYTES",
    "AssistantCancellationToken",
    "AssistantCancelled",
    "AssistantProgressCallback",
    "AssistantProgressEvent",
    "AssistantProvider",
    "AssistantProviderDescriptor",
    "AssistantRequest",
    "AssistantResponse",
    "canonical_payload_sha256",
]
