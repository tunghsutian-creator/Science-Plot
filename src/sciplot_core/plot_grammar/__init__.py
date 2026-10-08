"""Backend-neutral scientific Figure/View/Layer/Mark grammar, version 2."""
from .capabilities import require_capabilities
from .compiler import compile_figure
from .ir import ir_schema_v2, seal_ir_v2, validate_ir_v2
from .projection import merge_figure_spec, split_figure_spec
from .schema import figure_spec_schema
from .validation import validate_bound_data, validate_figure_spec

__all__ = ["compile_figure", "figure_spec_schema", "ir_schema_v2", "merge_figure_spec", "require_capabilities",
           "seal_ir_v2", "split_figure_spec", "validate_bound_data", "validate_figure_spec", "validate_ir_v2"]
