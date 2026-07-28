"""Native Veusz assistant bridge API."""

from pathlib import Path
from typing import Any

from sciplot_core.assistant_provider import AssistantProvider
from sciplot_gui.assistant_runtime import resolve_assistant_provider
from sciplot_gui.studio_assistant.bridge import (
    StudioAssistantBridge,
    attach_studio_assistant as _attach_studio_assistant,
)


def attach_studio_assistant(
    window: Any,
    document_path: Path,
    *,
    provider: AssistantProvider | None = None,
    resolve_provider: bool = True,
) -> StudioAssistantBridge:
    """Attach the bridge through the legacy injectable provider seam."""

    return _attach_studio_assistant(
        window,
        document_path,
        provider=provider,
        resolve_provider=resolve_provider,
        provider_resolver=resolve_assistant_provider,
    )


__all__ = ["StudioAssistantBridge", "attach_studio_assistant"]
