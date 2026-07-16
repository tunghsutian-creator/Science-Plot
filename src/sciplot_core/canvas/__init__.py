"""Pure, renderer-independent contracts for the SciPlot live canvas."""

from sciplot_core.canvas.annotations import (
    ReviewAnnotation,
    ReviewAnnotationStyle,
)
from sciplot_core.canvas.assistant_contract import (
    DataColumnMapping,
    DataMappingConfirmation,
    DataMappingProposal,
    DataSourceReference,
    DeclarativeTransformation,
)
from sciplot_core.canvas.model import (
    CanvasDataPointSelection,
    CanvasObjectRecord,
    CanvasSelection,
    CanvasSession,
    CanvasTransaction,
    CanvasViewport,
    ObjectIdentityRegistry,
)
from sciplot_core.canvas.operations import CanvasOperation, CanvasOperationBatch
from sciplot_core.canvas.provider import (
    ASSISTANT_MAX_INTENT_LENGTH,
    AssistantCancellationToken,
    AssistantCancelled,
    AssistantProgressEvent,
    AssistantProvider,
    AssistantProviderDescriptor,
    AssistantRequest,
    AssistantRequestRecord,
    AssistantResponse,
)

__all__ = [
    "CanvasObjectRecord",
    "CanvasDataPointSelection",
    "CanvasOperation",
    "CanvasOperationBatch",
    "CanvasSelection",
    "CanvasSession",
    "CanvasTransaction",
    "CanvasViewport",
    "ASSISTANT_MAX_INTENT_LENGTH",
    "AssistantCancellationToken",
    "AssistantCancelled",
    "AssistantProgressEvent",
    "AssistantProvider",
    "AssistantProviderDescriptor",
    "AssistantRequest",
    "AssistantRequestRecord",
    "AssistantResponse",
    "DataColumnMapping",
    "DataMappingConfirmation",
    "DataMappingProposal",
    "DataSourceReference",
    "DeclarativeTransformation",
    "ObjectIdentityRegistry",
    "ReviewAnnotation",
    "ReviewAnnotationStyle",
]
