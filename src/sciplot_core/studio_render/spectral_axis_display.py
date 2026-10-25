"""Freeze the qualitative XRD recipe's display at an actual new creation.

Saved axes and request replays consume their recorded value. Arbitrary-unit
text, response labels and measured numeric ranges never select this default.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sciplot_core.studio_render.template_resolution import _explicit_render_options


def freeze_new_spectral_axis_display(
    request: dict[str, Any],
    *,
    rule_id: str,
    template: str,
    transform_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project only a known ordinary XRD recipe into its existing render option."""
    result = deepcopy(request)
    if "intent" in request or rule_id != "xrd_pattern" or template != "curve":
        return result
    options = dict(request.get("render_options") or {})
    if "show_y_ticks" in options:
        return result
    explicit = _explicit_render_options(request)
    contract = transform_contract or {}
    normalizer_payload = contract.get("normalizer")
    normalizer = normalizer_payload if isinstance(normalizer_payload, dict) else {}
    axes = contract.get("axis_compatibility")
    y_axis = axes.get("y") if isinstance(axes, dict) else None
    compatibility = y_axis if isinstance(y_axis, dict) else {}
    qualitative = (
        contract.get("semantic_family") == rule_id
        and normalizer.get("scope") == "none"
        and normalizer.get("operation") == "none"
        and compatibility.get("registered_scale") == "linear"
        and options.get("yscale", "linear") == "linear"
        and not {"y_ticks", "y_min", "y_max"}.intersection(explicit)
    )
    options["show_y_ticks"] = not qualitative
    result["render_options"] = options
    # An effective default is persistent state, not a new user declaration.
    if "explicit_render_option_keys" not in result:
        result["explicit_render_option_keys"] = sorted(explicit)
    return result


def spectral_y_ticks(
    request: dict[str, Any],
    *,
    series_count: int,
) -> bool:
    """Consume a recorded override; retain the old missing-field stack fallback."""
    options = request.get("render_options")
    value = options.get("show_y_ticks") if isinstance(options, dict) else None
    return value if isinstance(value, bool) else series_count <= 1
