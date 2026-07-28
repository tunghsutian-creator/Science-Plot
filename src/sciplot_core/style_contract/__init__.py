"""Shared style contract audit API."""

from __future__ import annotations

from sciplot_core.style_contract.template_contracts import (  # noqa: F401
    VEUSZ_IMPLEMENTED_TEMPLATE_IDS,
    VEUSZ_REQUIRED_EDITABLE_OPTIONS,
    VEUSZ_TEMPLATE_COLOR_OPTIONS,
)
from sciplot_core.style_contract.expected_values import (  # noqa: F401
    _expected_render_hard_values,
    _expected_optional_hard_values,
    _expected_contract_style_values,
    _expected_global_frame,
)
from sciplot_core.style_contract.contract_values import (  # noqa: F401
    _contract_style_values,
)
from sciplot_core.style_contract.template_validation import (  # noqa: F401
    validate_veusz_template_id,
)
from sciplot_core.style_contract.audit import (  # noqa: F401
    audit_style_template_contract,
)

__all__ = [
    "VEUSZ_IMPLEMENTED_TEMPLATE_IDS",
    "VEUSZ_REQUIRED_EDITABLE_OPTIONS",
    "VEUSZ_TEMPLATE_COLOR_OPTIONS",
    "audit_style_template_contract",
    "validate_veusz_template_id",
]
