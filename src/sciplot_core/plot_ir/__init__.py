"""Backend-neutral, deterministic scientific plot compilation."""

from .schema import ir_schema, layout_schema, seal_ir, validate_ir
from .compiler import SemanticCompiler, compile_document
from .managed import apply_theme, create_managed_document, validate_managed

__all__ = ["SemanticCompiler", "apply_theme", "compile_document", "create_managed_document",
           "ir_schema", "layout_schema", "seal_ir", "validate_ir", "validate_managed"]
