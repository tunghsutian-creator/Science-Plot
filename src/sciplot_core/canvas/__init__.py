"""Pure, renderer-independent contracts for the SciPlot live canvas."""

from sciplot_core.canvas.annotations import (
    ReviewAnnotation,
    ReviewAnnotationStyle,
)
from sciplot_core.canvas.assistant_contract import (
    DataMappingProposal,
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

__all__ = [
    "CanvasObjectRecord",
    "CanvasDataPointSelection",
    "CanvasOperation",
    "CanvasOperationBatch",
    "CanvasSelection",
    "CanvasSession",
    "CanvasTransaction",
    "CanvasViewport",
    "DataMappingProposal",
    "DeclarativeTransformation",
    "ObjectIdentityRegistry",
    "ReviewAnnotation",
    "ReviewAnnotationStyle",
]
