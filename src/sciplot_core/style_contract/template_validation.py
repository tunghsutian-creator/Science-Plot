"""Validate public Veusz template identifiers."""

from __future__ import annotations


from sciplot_core.style_contract.template_contracts import (
    VEUSZ_IMPLEMENTED_TEMPLATE_IDS,
)


def validate_veusz_template_id(template: object) -> str:
    """Return a production template id or fail before document generation."""

    normalized = str(template or "").strip()
    if normalized not in VEUSZ_IMPLEMENTED_TEMPLATE_IDS:
        known = ", ".join(sorted(VEUSZ_IMPLEMENTED_TEMPLATE_IDS))
        raise ValueError(
            f"Template `{normalized or template}` is not implemented by SciPlot's "
            f"Veusz document builder. Supported templates: {known}."
        )
    return normalized
