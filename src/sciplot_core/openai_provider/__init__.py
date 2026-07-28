"""OpenAI Responses assistant provider API and compatibility facade."""

from __future__ import annotations

from sciplot_core.openai_provider.contracts import (  # noqa: F401
    DEFAULT_OPENAI_MODEL,
    DEFAULT_OPENAI_BASE_URL,
    OPENAI_PROVIDER_ID,
    OPENAI_REASONING_EFFORTS,
    _MAX_STREAM_LINE_BYTES,
    _MAX_STREAM_EVENT_BYTES,
    _MAX_STREAM_TEXT_BYTES,
    _MAX_HTTP_ERROR_BYTES,
    _MAX_MODEL_OPERATIONS,
    _MAX_MODEL_WARNINGS,
    _WINDOWS_ABSOLUTE_PATH,
    OPENAI_ASSISTANT_OUTPUT_SCHEMA,
    _PROVIDER_INSTRUCTIONS,
)
from sciplot_core.openai_provider.errors import (  # noqa: F401
    OpenAIProviderError,
    _AssistantContextUnavailable,
)
from sciplot_core.openai_provider.validation import (  # noqa: F401
    _required_text,
    _free_text,
    _is_loopback,
    _redact,
)
from sciplot_core.openai_provider.config import (  # noqa: F401
    OpenAIResponsesConfig,
)
from sciplot_core.openai_provider.transport_helpers import (  # noqa: F401
    _StreamResult,
    _error_message,
    _response_content,
    _connection,
)
from sciplot_core.openai_provider.sse_client import (  # noqa: F401
    _ResponsesSSEClient,
)
from sciplot_core.openai_provider.model_output import (  # noqa: F401
    _json_loads_strict,
    _model_envelope,
    _finite_number,
    _check_range,
    _coerce_value,
    _provider_safe_context,
)
from sciplot_core.openai_provider.provider import (  # noqa: F401
    OpenAIResponsesProvider,
)
from sciplot_core.openai_provider.environment import (  # noqa: F401
    load_openai_provider_from_environment,
)

__all__ = [
    "DEFAULT_OPENAI_BASE_URL",
    "DEFAULT_OPENAI_MODEL",
    "OPENAI_ASSISTANT_OUTPUT_SCHEMA",
    "OPENAI_PROVIDER_ID",
    "OpenAIProviderError",
    "OpenAIResponsesConfig",
    "OpenAIResponsesProvider",
    "load_openai_provider_from_environment",
]
