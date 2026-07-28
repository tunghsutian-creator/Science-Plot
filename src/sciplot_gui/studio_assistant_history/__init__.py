"""Assistant history API and compatibility facade."""

from __future__ import annotations

from sciplot_gui.studio_assistant_history.contracts import (  # noqa: F401
    ASSISTANT_HISTORY_KIND,
    ASSISTANT_HISTORY_VERSION,
    ASSISTANT_HISTORY_FILENAME,
    ASSISTANT_HISTORY_STATUSES,
    ASSISTANT_HISTORY_REASON_CODES,
    _SHA256,
    _EVENT_FIELDS,
    _REQUIRED_EVENT_FIELDS,
    _SELECTED_OBJECT_FIELDS,
    _OPERATION_FIELDS,
)
from sciplot_gui.studio_assistant_history.values import (  # noqa: F401
    _now,
    _required_text,
    _optional_text,
    _uuid_text,
    _sha256,
    canonical_value_sha256,
    assistant_history_path,
)
from sciplot_gui.studio_assistant_history.operations import (  # noqa: F401
    _operation_payload,
)
from sciplot_gui.studio_assistant_history.builder import (  # noqa: F401
    build_assistant_history_event,
)
from sciplot_gui.studio_assistant_history.validation import (  # noqa: F401
    validate_assistant_history_event,
)
from sciplot_gui.studio_assistant_history.storage import (  # noqa: F401
    append_assistant_history_event,
    read_assistant_history,
)

__all__ = [
    "ASSISTANT_HISTORY_FILENAME",
    "ASSISTANT_HISTORY_KIND",
    "ASSISTANT_HISTORY_REASON_CODES",
    "ASSISTANT_HISTORY_STATUSES",
    "ASSISTANT_HISTORY_VERSION",
    "append_assistant_history_event",
    "assistant_history_path",
    "build_assistant_history_event",
    "canonical_value_sha256",
    "read_assistant_history",
    "validate_assistant_history_event",
]
