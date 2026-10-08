"""Pure, versioned SciPlot scientific document and semantic-edit contract."""

from .errors import DocumentError
from .model import seal_document, validate_document
from .patch import apply_patch, validate_patch
from .schema import document_schema, patch_schema
from .dependency import artifact_build_key, build_keys, dependency_schema, invalidated_nodes, validate_dependency_graph
from .templates import (binding_schema, instantiate_template, template_schema, theme_schema,
                        validate_binding, validate_template, validate_theme)

__all__ = ["DocumentError", "apply_patch", "document_schema", "patch_schema",
           "seal_document", "validate_document", "validate_patch", "artifact_build_key", "build_keys",
           "dependency_schema", "invalidated_nodes", "validate_dependency_graph", "binding_schema",
           "instantiate_template", "template_schema", "theme_schema", "validate_binding",
           "validate_template", "validate_theme"]
