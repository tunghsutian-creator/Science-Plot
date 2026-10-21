"""Project registered unit relations without changing the sealed executor."""

import re
from typing import Literal, TypedDict

from sciplot_core.materials_rules.unit_conversion import convert_value
from sciplot_core.materials_rules.unit_data import _UNIT_RULES
from sciplot_core.plot_document.errors import fail


class UnitRelation(TypedDict):
    from_unit: str
    to_unit: str
    canonical_from_unit: str
    canonical_to_unit: str
    factor: float
    offset: float
    authority: Literal["materials_rules.unit_conversion"]
    kind: Literal["identity", "conversion"]


def _registered_endpoint(unit: str, *, temperature: bool) -> str | None:
    """Recognize finite spellings of actual endpoints, without display inference."""
    endpoints = {endpoint for pair in _UNIT_RULES for endpoint in pair}
    token = unit.strip()
    if len(token) >= 2 and (token[0], token[-1]) in {("[", "]"), ("(", ")")}:
        token = token[1:-1].strip()
    # These are spelling identities, not additional conversions. Each result
    # must still be an endpoint in the unchanged numeric registry below.
    aliases = {"Pa·s": "Pa.s", "Pa s": "Pa.s", "mPa·s": "mPa.s", "mPa s": "mPa.s",
               "rad s⁻¹": "rad/s", "rad·s⁻¹": "rad/s", "rad s^-1": "rad/s",
               "Å⁻¹": "A^-1", "A⁻¹": "A^-1", "A$^{-1}$": "A^-1", "Å^-1": "A^-1",
               "nm⁻¹": "nm^-1", "nm$^{-1}$": "nm^-1", "µm": "um", "μm": "um"}
    token = aliases.get(token, token)
    if token in {"C", "°C"}:
        return "C" if temperature else None
    return token if token in endpoints else None


def requires_unit_context(from_unit: str, to_unit: str) -> bool:
    """Identify the bounded historical C interpretation/formatting boundary."""
    return any(_registered_endpoint(unit, temperature=True) == "C"
               or "/" in unit and re.search(r"(?<![\w°])C(?!\w)", unit) is not None
               for unit in (from_unit, to_unit))


def resolve_unit_relation(from_unit: str, to_unit: str, *, quantity: str | None = None,
                          observed_quantity: str | None = None,
                          explicit_quantity_binding: bool = False) -> UnitRelation:
    """Admit current bindings to the unchanged registered numeric conversions.

    An unregistered unit can retain its exact original spelling and values.
    Legacy C means Celsius only in a source-supported or explicitly selected
    temperature binding. Display formatting never supplies physical identity.
    This admission helper does not replace the historical builtin executor.
    """
    if not from_unit.strip() or not to_unit.strip():
        fail("transform_unit_incompatible", "Both original and target units must be explicitly declared.",
             "/parameters/to_unit", "declared_units", from_unit=from_unit, to_unit=to_unit)
    temperature = quantity == "temperature" and (observed_quantity == "temperature"
                    or observed_quantity is None and explicit_quantity_binding)
    if (requires_unit_context(from_unit, to_unit) and quantity is not None
            and observed_quantity is not None and quantity != observed_quantity):
        fail("transform_unit_incompatible", "The unit interpretation cannot replace an observed scientific quantity.",
             "/parameters/to_unit", "observed_quantity_identity", from_unit=from_unit, to_unit=to_unit)
    if quantity == "temperature" and not temperature and requires_unit_context(from_unit, to_unit):
        fail("transform_unit_incompatible", "A temperature interpretation requires observed temperature metadata or an exact selected user quantity binding.",
             "/parameters/to_unit", "confirmed_temperature_quantity", from_unit=from_unit, to_unit=to_unit)
    if not temperature and any("/" in unit and re.search(r"(?<![\w°])C(?!\w)", unit)
                               for unit in (from_unit, to_unit)):
        fail("transform_unit_context_unsupported", "The historical compound-unit formatter cannot preserve non-temperature C. This current binding is unsupported until contextual formatting is migrated.",
             "/parameters/to_unit", "contextual_compound_unit", from_unit=from_unit, to_unit=to_unit, quantity=quantity)
    source, target = (_registered_endpoint(unit, temperature=temperature) for unit in (from_unit, to_unit))
    if source is None or target is None:
        if from_unit != to_unit:
            fail("transform_unit_incompatible", "A unit projection requires registered endpoints or the exact same original unit.",
                 "/parameters/to_unit", "registered_unit_conversion", from_unit=from_unit, to_unit=to_unit)
        source = target = from_unit
    try:
        offset = convert_value(0, source, target)
        factor = convert_value(1, source, target) - offset
    except ValueError as exc:
        fail("transform_unit_incompatible", str(exc), "/parameters/to_unit", "registered_unit_conversion",
             from_unit=from_unit, to_unit=to_unit)
    return {"from_unit": from_unit, "to_unit": to_unit,
            "canonical_from_unit": source, "canonical_to_unit": target,
            "factor": factor, "offset": offset, "authority": "materials_rules.unit_conversion",
            "kind": "identity" if source == target and factor == 1 and offset == 0 else "conversion"}
