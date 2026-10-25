"""Retained exact scalar viscosity derivation; no mutable source adapter."""
import math
import re
from .unit_formatting import format_unit_label
from .rheology_units import _unit_conversion


def validate_complex_viscosity_units(
    *,
    frequency_unit: str,
    storage_unit: str,
    loss_unit: str,
    output_unit: str = 'Pa s',
) -> tuple[float, float, float]:
    """Validate source/output dimensions even when every observation is missing."""
    factors = []
    for unit, target in (
        (frequency_unit, 'rad/s'),
        (storage_unit, 'Pa'),
        (loss_unit, 'Pa'),
    ):
        _unit, factor, method = _unit_conversion(unit, target)
        if not unit.strip() or method == 'source_unit_preserved':
            raise ValueError('Complex viscosity requires explicit supported frequency and modulus units.')
        factors.append(factor)
    _viscosity_output_factor(output_unit)
    return factors[0], factors[1], factors[2]



def derive_complex_viscosity(
    omega: float,
    storage: float,
    loss: float,
    *,
    frequency_unit: str,
    storage_unit: str,
    loss_unit: str,
    output_unit: str = 'Pa s',
) -> float:
    """Deterministic |eta*| from original G'/G'' and explicit frequency units."""
    factors = validate_complex_viscosity_units(
        frequency_unit=frequency_unit, storage_unit=storage_unit,
        loss_unit=loss_unit, output_unit=output_unit,
    )
    values = [value * factor for value, factor in zip((omega, storage, loss), factors, strict=True)]
    normalized_omega, normalized_storage, normalized_loss = values
    if not all(math.isfinite(value) for value in values):
        raise ValueError('Complex viscosity requires finite original frequency and moduli.')
    return _viscosity_from_modulus(
        normalized_omega,
        math.hypot(normalized_storage, normalized_loss),
        output_unit=output_unit,
    )



def _viscosity_output_factor(output_unit: str) -> float:
    output = re.sub(r'\s+', '·', format_unit_label(output_unit))
    if output not in {'Pa·s', 'mPa·s'}:
        raise ValueError('Complex viscosity output unit must be Pa·s or mPa·s.')
    return 1000. if output == 'mPa·s' else 1.



def _viscosity_from_modulus(omega: float, modulus: float, *, output_unit: str) -> float:
    if (
        not math.isfinite(omega) or omega <= 0
        or not math.isfinite(modulus) or modulus < 0
    ):
        raise ValueError(
            'Complex viscosity requires positive finite angular frequency and a finite nonnegative modulus at every selected row.'
        )
    value = modulus / omega * _viscosity_output_factor(output_unit)
    if not math.isfinite(value):
        raise ValueError('Derived complex viscosity is not finite.')
    return value
