"""Bind analysis-series roles to the shared template and encoding owners."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import re

from sciplot_core.contract import load_plot_contract
from sciplot_core.materials_rules.catalog import resolve_rule_template
from sciplot_core.policy import (
    DEFAULT_CURVE_LINE_STYLE_SEQUENCE, DEFAULT_FIGURE_SIZE, WIDE_FIGURE_SIZE, resolve_palette_authority,
)
from sciplot_core.studio_core.veusz_spec_builder import _style_spec
from sciplot_core.studio_render.models import POINT_LINE_MARKERS, StudioSeries
from sciplot_core.studio_render.series_option_context import effective_render_options
from sciplot_core.studio_render.series_options import resolve_series_encodings
from sciplot_core.studio_render.style_contract import _veusz_style_contract
from sciplot_core.studio_render.value_parsing import _size_mm, _string_list


POLICY_ID = "shared_template_roles_v1"
POLICY = {"id": POLICY_ID, "version": 1}
_RAW_STYLE_FIELDS = frozenset({"marker", "marker_size", "marker_fill", "marker_alpha",
    "marker_fill_color", "marker_line_color", "marker_line_width", "line_style", "line_width"})
_PANEL_FIELDS = frozenset({"id", "title", "rect_mm", "x_label", "y_label", "series", "legend",
    "xscale", "yscale", "x_min", "x_max", "y_min", "y_max", "x_ticks", "y_ticks", "x_tick_format",
    "y_tick_format", "x_tick_labels", "standard_frame", "reference_lines", "notes", "template_id", "rule_id"})
_SERIES_FIELDS = frozenset({"label", "x", "y", "color", "color_index", "kind", "bar_width", "legend", "role",
    "template_id", "series_id", "semantic_id", "presentation_provenance", "error_values"})
_ROLES = {
    "measured_curve": {"template_id": "point_line", "line_visible": True,
                       "marker": "template_default", "reason": "Measured or derived trace retains every observation."},
    "context_curve": {"template_id": "point_line", "line_visible": True,
                      "marker": "semantic_color_group", "marker_fill_mode": "open",
                      "reason": "The full supplied frequency curve remains visible with open markers and a guide line; it does not identify fitting membership."},
    "fitting_region_points": {"template_id": "point_line", "line_visible": False,
                              "marker": "semantic_color_group", "marker_fill_mode": "filled",
                              "reason": "Filled markers identify the caller-supplied fitting-window observations; the plotting program neither selects points nor fits them."},
    "master_points": {"template_id": "point_line", "line_visible": False,
                      "marker": "circle", "reason": "Shifted temperature blocks are observations, not an interpolating fit."},
    "observed_shift": {"template_id": "point_line", "line_visible": False,
                       "marker": "circle", "reason": "Estimated shift factors are discrete observations for the regression."},
    "regression_fit": {"template_id": "curve", "line_visible": True,
                       "marker": "none", "reason": "A fitted regression line is not a measured observation."},
    "diagnostic_curve": {"template_id": "point_line", "line_visible": True,
                         "marker": "semantic_method", "reason": "Marker shape identifies the diagnostic method."},
    "diagnostic_points": {"template_id": "point_line", "line_visible": False,
                          "marker": "semantic_method", "reason": "Discrete diagnostic summaries retain method identities."},
    "summary_bar": {"template_id": "bar", "line_visible": False,
                    "marker": "none", "reason": "Native bars summarize apparent activation energies from a zero baseline."},
}
_METHOD_MARKERS = {
    "joint": "circle", "storage_only": "square", "loss_only": "triangle",
    "common_window": "diamond", "nominal_temperature": "cross", "legacy_uncorrected": "plus",
    "modulus_rms": "circle", "channel_difference": "square",
}
_METHOD_LABELS = {
    "joint": "Joint fit", "storage_only": "G′ fit", "loss_only": "G″ fit",
    "common_window": "Joint, 150–210 °C", "nominal_temperature": "Joint, nominal T",
    "legacy_uncorrected": "Uncorrected, nominal T", "modulus_rms": "Log-modulus RMS",
    "channel_difference": "Max. channel shift difference",
}


def tts_presentation_capabilities() -> dict:
    """Project the live owners; this is not a second catalog of style defaults."""
    contract = load_plot_contract()
    palette = resolve_palette_authority({}, template_id="point_line")
    return {"policy": dict(POLICY), "roles": deepcopy(_ROLES),
        "templates": {key: {"default_options": dict(contract.templates[key].default_options)}
                      for key in ("point_line", "curve", "bar")},
        "frequency_rule": {"rule_id": "rheology_frequency_sweep",
                           "template_id": resolve_rule_template("rheology_frequency_sweep")},
        "shared_defaults": {**_style_spec(_veusz_style_contract({})),
                            "marker_cycle": list(POINT_LINE_MARKERS),
                            "line_style_cycle": list(DEFAULT_CURVE_LINE_STYLE_SEQUENCE)},
        "owners": {"style": "sciplot_core.policy",
                   "series_encoding": "sciplot_core.studio_render.series_options.resolve_series_encodings",
                   "roles": "sciplot_core.rheology_tts_style"},
        "raw_series_style_overrides": "rejected_in_governed_plans",
        "layout": {"default_size_mm": list(_size_mm(DEFAULT_FIGURE_SIZE)),
                   "wide_size_mm": list(_size_mm(WIDE_FIGURE_SIZE)),
                   "panels_per_figure": 1, "standard_frame": True,
                   "owner": "sciplot_core.policy"},
        "palette": {"id": palette.palette_id, "colors": list(palette.colors), "source": palette.source},
        "processed_plan": {
            "owner": "AI or caller completes scientific processing before plotting",
            "version": 1, "required": ["version", "source_binding", "figures"],
            "figure_required": ["id", "panels"],
            "panel_required": ["id", "x_label", "y_label", "series"],
            "series_required": ["role", "label", "x", "y"],
            "series_optional": ["template_id", "semantic_id", "kind", "bar_width", "legend", "color_index", "color", "error_values"],
            "program_owned": ["series_id", "presentation_provenance", "presentation_policy"],
            "color_binding": "Missing color uses the shared palette in series order. Optional color_index identifies repeated semantic groups. An explicit color must belong to that live palette and match its index.",
            "fitting_region_overlay": "Supply full coordinates as context_curve and selected coordinates as fitting_region_points with the same color_index. Both use that index in the shared marker cycle; context markers are open and fitting markers filled. Put all fitting_region_points before all context_curve series: native siblings paint in reverse order, so the filled overlays then remain visible in the foreground. There is no point selection or fitting performed by the program.",
            "error_values": "Optional caller-supplied finite nonnegative symmetric Y errors, in y units, paired one-to-one with the supplied coordinates; zero is allowed and no errors are calculated by the plotting program.",
            "diagnostic_semantic_ids": dict(_METHOD_MARKERS),
            "template_identity": "Derived from role when omitted; a conflicting supplied template is rejected.",
            "coordinates": "Finite paired arrays retained in supplied order; no fitting, correction, sorting or point removal.",
        },
        "legacy": "Specifications without presentation_policy retain their explicit historical styles."}


def _identity(figure: dict) -> tuple[str, list[str | None]]:
    """Recognize only the published separated plan, never infer from axis prose."""
    identifier, polymer = figure.get("id", ""), figure.get("polymer")
    if polymer not in ("HDPE", "LDPE") or len(figure.get("panels", [])) != 1:
        raise ValueError("Style governance requires a known independent single-polymer figure.")
    series = figure["panels"][0].get("series", [])
    count, expected_count, methods = len(series), None, []
    sample = rf"{polymer}_(?:Control|2UDC" + ("|6UDC" if polymer == "HDPE" else "") + ")"
    modulus = r"(?P<modulus>Gprime|Gdoubleprime)"
    match = re.fullmatch(rf"(?P<kind>FS|TTS)_{polymer}_{modulus}_210C", identifier)
    if match:
        reduced = match["kind"] == "TTS"
        quantity = ("storage" if match["modulus"] == "Gprime" else "loss") + "_modulus_" + ("reduced_Pa" if reduced else "Pa")
        basis = "temperature_reduced_master_coordinates" if reduced else "original_210C_acquisition"
        role = "master_points" if reduced else "measured_curve"
        expected_count = None if reduced else 4
    elif identifier == f"SI_Complex_viscosity_{polymer}_210C":
        quantity, basis, role = "complex_viscosity_Pa_s", "original_210C_acquisition", "measured_curve"
        expected_count = 4
    elif (match := re.fullmatch(rf"SI_(?P<kind>Original|TTS)_{sample}_{modulus}", identifier)):
        reduced = match["kind"] == "TTS"
        quantity = ("storage" if match["modulus"] == "Gprime" else "loss") + "_modulus_" + ("reduced_Pa" if reduced else "Pa")
        basis = "temperature_reduced_master_coordinates" if reduced else "original_temperature_acquisition"
        role = "master_points" if reduced else "measured_curve"
    elif re.fullmatch(rf"SI_Van_Gurp_Palmen_{sample}", identifier):
        quantity, basis, role = "phase_angle_degrees", "original_temperature_acquisition", "measured_curve"
    elif identifier == f"Tan_delta_{polymer}_0p1rad_s":
        quantity, basis, role = "loss_factor", "original_210C_acquisition", "measured_curve"
        expected_count = 1
    elif identifier in (f"Arrhenius_{polymer}", f"Ea_app_{polymer}"):
        fit = identifier.startswith("Arrhenius_")
        quantity, role = ("ln_aT", "arrhenius_pair") if fit else ("Ea_app_kJ_mol", "summary_bar")
        basis = "corrected_joint_shifts_actual_mean_temperature"
        expected_count = (3 if polymer == "HDPE" else 2) * (2 if fit else 1)
    elif re.fullmatch(rf"SI_Shift_channels_{sample}", identifier):
        quantity, basis, role = "log10_aT", "corrected_joint_and_channel_specific_shifts", "diagnostic_curve"
        methods = ["joint", "storage_only", "loss_only"]
    elif identifier == f"SI_Ea_sensitivity_{polymer}":
        quantity, basis, role = "Ea_app_kJ_mol", "explicit_corrected_and_legacy_sensitivity_fits", "diagnostic_points"
        methods = ["joint", "storage_only", "loss_only", "common_window", "nominal_temperature", "legacy_uncorrected"]
    elif identifier == f"SI_TTS_diagnostics_{polymer}":
        quantity, basis, role = "deviation_decades", "corrected_joint_TTS_diagnostics", "diagnostic_points"
        methods = ["modulus_rms", "channel_difference"]
    else:
        raise ValueError(f"Unknown separated figure identity for style governance: {identifier}")
    if figure.get("quantity") != quantity or figure.get("data_basis") != basis:
        raise ValueError(f"Figure metric/data-basis identity conflicts with its role: {identifier}")
    if methods:
        expected_count = len(methods)
        if [s.get("label") for s in series] != [_METHOD_LABELS[m] for m in methods]:
            raise ValueError(f"Diagnostic method labels conflict with the known method identities: {identifier}")
    if not count or (expected_count is not None and count != expected_count):
        raise ValueError(f"Unexpected series count for governed figure: {identifier}")
    if role == "arrhenius_pair":
        if any(series[i].get("label") or series[i]["x"] != series[i - 1]["x"]
               for i in range(1, count, 2)):
            raise ValueError("An Arrhenius fit must match its preceding observed-shift x coordinates and have no legend label.")
    if any((s.get("kind", "curve") == "bar") != (role == "summary_bar") for s in series):
        raise ValueError(f"Native series kind conflicts with its governed role: {identifier}")
    return role, methods or [None] * count


def _declarations(figure: dict) -> tuple[str, list[dict]]:
    role, methods = _identity(figure)
    declarations = []
    for index, method in enumerate(methods):
        item_role = ("regression_fit" if index % 2 else "observed_shift") if role == "arrhenius_pair" else role
        declarations.append(_declaration(item_role, index, method))
    return ("bar" if role == "summary_bar" else "point_line"), declarations


def _declaration(role: str, index: int, method: str | None) -> dict:
    if role not in _ROLES:
        raise ValueError(f"Unknown scientific series presentation role: {role}")
    definition = _ROLES[role]
    diagnostic = definition["marker"] == "semantic_method"
    if (diagnostic and method not in _METHOD_MARKERS) or (not diagnostic and method is not None):
        raise ValueError(f"Unsupported diagnostic method identity for role: {role}")
    return {"series_id": f"series_{index + 1}", "role": role,
        "template_id": definition["template_id"], "semantic_id": method,
        "presentation_provenance": {"owner": POLICY_ID, "reason": definition["reason"],
                                    "color_source": "shared_palette_semantic_index"}}


def _bind_palette(raw: dict, index: int) -> None:
    palette = resolve_palette_authority({}, template_id=_ROLES[raw["role"]]["template_id"]).colors
    supplied = raw.get("color")
    if supplied is not None and supplied not in palette:
        raise ValueError("An explicit governed color must belong to the live shared palette.")
    selected = raw.get("color_index", palette.index(supplied) if supplied is not None else index % len(palette))
    if isinstance(selected, bool) or not isinstance(selected, int) or not 0 <= selected < len(palette):
        raise ValueError("color_index must identify an entry in the live shared palette.")
    if supplied is not None and supplied != palette[selected]:
        raise ValueError("Explicit color conflicts with its semantic shared-palette index.")
    raw["color_index"], raw["color"] = selected, palette[selected]


def prepare_tts_presentation(spec: dict) -> dict:
    """Accept caller-processed coordinates and declare only program-owned styles."""
    result = deepcopy(spec)
    if "presentation_policy" in result and result["presentation_policy"] != POLICY:
        raise ValueError("Unknown or incomplete TTS presentation policy.")
    for figure in result.get("figures", []):
        default_size, wide_size = _size_mm(DEFAULT_FIGURE_SIZE), _size_mm(WIDE_FIGURE_SIZE)
        figure.setdefault("width_mm", default_size[0])
        figure.setdefault("height_mm", default_size[1])
        size = (figure["width_mm"], figure["height_mm"])
        if size not in (default_size, wide_size) or len(figure.get("panels", [])) != 1:
            raise ValueError("Governed figures require one panel and a shared standard or wide size preset.")
        for panel in figure.get("panels", []):
            if "render_options" in panel:
                raise ValueError("Governed panel styles cannot be overridden with raw render options.")
            if set(panel) - _PANEL_FIELDS:
                raise ValueError("Unsupported governed panel fields: " + ", ".join(sorted(set(panel) - _PANEL_FIELDS)))
            panel.setdefault("standard_frame", True)
            panel.setdefault("rect_mm", [0, 0, *size])
            if panel["standard_frame"] is not True or panel["rect_mm"] != [0, 0, *size]:
                raise ValueError("Governed panels require the shared standard frame and full-preset rectangle.")
            for index, raw in enumerate(panel.get("series", [])):
                forbidden = set(raw) & _RAW_STYLE_FIELDS
                if forbidden:
                    raise ValueError("Governed series style overrides require an explicit supported role; raw fields are rejected: " + ", ".join(sorted(forbidden)))
                if set(raw) - _SERIES_FIELDS:
                    raise ValueError("Unsupported governed series fields: " + ", ".join(sorted(set(raw) - _SERIES_FIELDS)))
                expected = _declaration(raw.get("role"), index, raw.get("semantic_id"))
                if any(key in raw and raw[key] != value for key, value in expected.items()):
                    raise ValueError("Series role, template, identity or provenance conflicts with its presentation contract.")
                if (raw.get("kind", "curve") == "bar") != (raw["role"] == "summary_bar"):
                    raise ValueError("Native series kind conflicts with the declared role.")
                raw.update(expected)
                _bind_palette(raw, index)
            roles = {raw["role"] for raw in panel.get("series", [])}
            if "summary_bar" in roles and len(roles) != 1:
                raise ValueError("A native summary bar panel cannot mix curve series.")
            template = "bar" if roles == {"summary_bar"} else "curve" if roles == {"regression_fit"} else "point_line"
            if "template_id" in panel and panel["template_id"] != template:
                raise ValueError("Panel template conflicts with its scientific series roles.")
            if panel.get("rule_id") is not None:
                resolve_rule_template(panel["rule_id"], template)
            panel["template_id"] = template
    result["presentation_policy"] = dict(POLICY)
    return result


def validate_tts_presentation(spec: dict) -> None:
    if spec.get("presentation_policy") != POLICY or prepare_tts_presentation(spec) != spec:
        raise ValueError("Unknown or incomplete TTS presentation declarations.")


def upgrade_tts_presentation(spec: dict) -> dict:
    """Explicitly migrate only presentation fields; preserve all scientific values."""
    result = deepcopy(spec)
    if result.get("figure_layout") != "separate_polymer_modulus":
        raise ValueError("Presentation upgrade supports only the known separated-polymer/modulus plan.")
    if "presentation_policy" in result:
        validate_tts_presentation(result)
        for figure in result.get("figures", []):
            template, declarations = _declarations(figure)
            panel = figure["panels"][0]
            if panel["template_id"] != template or any(
                any(raw.get(k) != value for k, value in expected.items())
                for raw, expected in zip(panel["series"], declarations, strict=True)
            ):
                raise ValueError("Governed historical plan conflicts with its known series identity.")
        return result
    for figure in result.get("figures", []):
        template, declarations = _declarations(figure)
        panel = figure["panels"][0]
        panel["template_id"] = template
        for raw, declaration in zip(panel["series"], declarations, strict=True):
            for key in _RAW_STYLE_FIELDS:
                raw.pop(key, None)
            raw.update(declaration)
    result["presentation_policy"] = dict(POLICY)
    return prepare_tts_presentation(result)


def resolve_tts_series(panel: dict, typed: list[StudioSeries]) -> list[StudioSeries]:
    """Use the ordinary encoding resolver with unique IDs and semantic overrides."""
    raw_series = panel["series"]
    by_id = {}
    groups = dict.fromkeys((raw["template_id"], _ROLES[raw["role"]].get("marker_fill_mode", "template_default"))
                          for raw in raw_series)
    for template, fill_mode in groups:
        selected = [(item, raw) for item, raw in zip(typed, raw_series, strict=True)
                    if raw["template_id"] == template
                    and _ROLES[raw["role"]].get("marker_fill_mode", "template_default") == fill_mode]
        template_options = effective_render_options({"template": template})
        marker_sequence = _string_list(template_options.get("marker_sequence")) or list(POINT_LINE_MARKERS)
        styles = []
        for _item, raw in selected:
            definition = _ROLES[raw["role"]]
            style = {"label": raw["series_id"], "color": raw["color"]}
            marker = definition["marker"]
            if marker != "template_default":
                if marker == "semantic_color_group":
                    style["marker"] = marker_sequence[raw["color_index"] % len(marker_sequence)]
                else:
                    style["marker"] = _METHOD_MARKERS[raw["semantic_id"]] if marker == "semantic_method" else marker
                    style["line_style"] = "solid"
            styles.append(style)
        request = {"template": template, "render_options": {"series_styles": styles},
                   "explicit_render_option_keys": []}
        if fill_mode != "template_default":
            request["render_options"]["marker_fill_mode"] = fill_mode
        options = effective_render_options(request)
        resolved_group = resolve_series_encodings([item for item, _ in selected],
                                                  render_options=options, request=request)
        by_id.update({item.label: item for item in resolved_group})
    resolved = [by_id[item.label] for item in typed]
    if [(s.label, s.x_values, s.y_values, s.error_values) for s in typed] != [
            (s.label, s.x_values, s.y_values, s.error_values) for s in resolved]:
        raise ValueError("Shared presentation resolution may not change the scientific series selection or coordinates.")
    result = []
    for item, raw in zip(resolved, raw_series, strict=True):
        provenance = item.encoding_provenance
        semantic = f"tts_role:{raw['role']}"
        method = raw["semantic_id"]
        updates = {"color_source": "tts_shared_palette_index", "marker_fill_source": "tts_shared_palette_index",
                   "marker_line_source": "tts_shared_palette_index"}
        if _ROLES[raw["role"]]["marker"] == "semantic_color_group":
            updates["marker_source"] = "tts_shared_marker_cycle_by_color_index"
            if _ROLES[raw["role"]].get("marker_fill_mode") == "open":
                updates["marker_fill_source"] = f"{semantic}:shared_open_marker_fill"
        elif raw["role"] != "measured_curve":
            updates.update(marker_source=f"tts_method:{method}" if method else semantic,
                           line_style_source=semantic)
        result.append(replace(item, encoding_provenance=replace(provenance, **updates)))
    return result


def finalize_tts_encoding(entry: dict, raw: dict) -> None:
    """Apply documented role visibility after the shared immutable channels resolve."""
    definition = _ROLES[raw["role"]]
    entry.update({key: deepcopy(raw[key]) for key in
                  ("series_id", "role", "template_id", "semantic_id", "color_index", "presentation_provenance")})
    entry["label"] = str(raw.get("label", ""))
    entry["legend_key"] = entry["label"] if raw.get("legend", True) else ""
    entry["encoding"]["line"]["visible"] = definition["line_visible"]
    entry["plot_line_hide"] = not definition["line_visible"]
    entry["presentation_provenance"]["line_visibility_source"] = f"tts_role:{raw['role']}"
    entry["presentation_provenance"]["shared_resolver"] = "resolve_series_encodings"
    entry["presentation_provenance"]["dimensions_source"] = "sciplot_core.policy"
