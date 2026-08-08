"""Resolve one auditable ordinary-series palette for every render request."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sciplot_core.policy.contract_loader import load_plot_contract
from sciplot_core.policy.visual_identity import (
    DEFAULT_PALETTE_COLORS,
    DEFAULT_PALETTE_PRESET,
    DEFAULT_SCALAR_FIELD_COLORMAP_ID,
    DEFAULT_SCALAR_FIELD_COLORS,
)


PALETTE_RESOLUTION_KIND = "sciplot_palette_resolution"
PALETTE_RESOLUTION_VERSION = 1


def _clean_palette_id(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _string_colors(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    colors = tuple(str(item).strip() for item in value if str(item).strip())
    return colors if len(colors) >= 2 else ()


def _render_options(request: Mapping[str, Any]) -> dict[str, Any]:
    value = request.get("render_options")
    return dict(value) if isinstance(value, dict) else {}


def _explicit_option_provenance(
    request: Mapping[str, Any],
) -> tuple[set[str], bool]:
    value = request.get("explicit_render_option_keys")
    if not isinstance(value, list | tuple | set):
        return set(), False
    return {str(item) for item in value}, True


@dataclass(frozen=True)
class PaletteResolution:
    """Final palette plus the request authority that selected it."""

    palette_id: str
    colors: tuple[str, ...]
    source: str
    explicit: bool
    template_id: str | None
    ignored_non_authoritative_palette_id: str | None = None
    custom_colors: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": PALETTE_RESOLUTION_KIND,
            "version": PALETTE_RESOLUTION_VERSION,
            "palette_id": self.palette_id,
            "colors": list(self.colors),
            "source": self.source,
            "explicit": self.explicit,
            "template_id": self.template_id,
            "custom_colors": self.custom_colors,
            "authority_order": [
                "explicit_render_option",
                "direct_render_option",
                "shared_project_default",
            ],
            "shared_project_default": DEFAULT_PALETTE_PRESET,
        }
        if self.ignored_non_authoritative_palette_id is not None:
            payload["ignored_non_authoritative_palette_id"] = (
                self.ignored_non_authoritative_palette_id
            )
        if self.template_id == "heatmap":
            payload["scalar_field_exception"] = {
                "colormap_id": DEFAULT_SCALAR_FIELD_COLORMAP_ID,
                "colors": list(DEFAULT_SCALAR_FIELD_COLORS),
                "reason": "heatmap_scalar_field_semantics",
            }
        return payload


def resolve_palette_authority(
    request: Mapping[str, Any],
    *,
    template_id: str | None = None,
    resolved_render_options: Mapping[str, Any] | None = None,
) -> PaletteResolution:
    """Resolve palette selection without promoting inherited defaults to intent.

    A request with explicit-option provenance may select a palette only when the
    palette key is present in that provenance.  A direct low-level request has no
    provenance envelope, so values it supplies are explicit by definition.
    Everything else follows the one shared project default.
    """

    options = _render_options(request)
    explicit_keys, provenance_present = _explicit_option_provenance(request)
    requested_id = _clean_palette_id(options.get("palette_preset"))
    requested_colors = _string_colors(options.get("palette_colors"))
    palette_is_explicit = (
        "palette_preset" in explicit_keys
        or not provenance_present
        and requested_id is not None
    )
    colors_are_explicit = (
        "palette_colors" in explicit_keys
        or not provenance_present
        and bool(requested_colors)
    )

    if palette_is_explicit or colors_are_explicit:
        palette_id = (
            requested_id
            if palette_is_explicit and requested_id
            else DEFAULT_PALETTE_PRESET
        )
        source = (
            "explicit_render_option" if provenance_present else "direct_render_option"
        )
    else:
        palette_id = DEFAULT_PALETTE_PRESET
        source = "shared_project_default"

    contract = load_plot_contract()
    palette = contract.palettes.get(palette_id)
    if palette is None or not palette.public:
        raise ValueError(
            f"Unknown palette_preset `{palette_id}`; select a public SciPlot palette."
        )
    colors = requested_colors if colors_are_explicit else tuple(palette.categorical)
    if palette_id == DEFAULT_PALETTE_PRESET and not colors_are_explicit:
        colors = tuple(DEFAULT_PALETTE_COLORS)

    ignored = (
        requested_id
        if requested_id is not None
        and not palette_is_explicit
        and requested_id != palette_id
        else None
    )
    resolution = PaletteResolution(
        palette_id=palette_id,
        colors=colors,
        source=source,
        explicit=palette_is_explicit or colors_are_explicit,
        template_id=(str(template_id).strip() or None) if template_id else None,
        ignored_non_authoritative_palette_id=ignored,
        custom_colors=colors_are_explicit,
    )

    if resolved_render_options is not None:
        actual_id = _clean_palette_id(resolved_render_options.get("palette_preset"))
        actual_colors = _string_colors(resolved_render_options.get("palette_colors"))
        if actual_id != resolution.palette_id:
            raise ValueError(
                "palette_resolution_mismatch: resolved render options do not match "
                "the request palette authority."
            )
        if resolution.custom_colors and actual_colors != resolution.colors:
            raise ValueError(
                "palette_resolution_mismatch: custom palette colors changed after "
                "request resolution."
            )
    return resolution


__all__ = [
    "PALETTE_RESOLUTION_KIND",
    "PALETTE_RESOLUTION_VERSION",
    "PaletteResolution",
    "resolve_palette_authority",
]
