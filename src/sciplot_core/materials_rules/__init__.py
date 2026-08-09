"""Public semantic rules, scientific units, and analysis metrics API."""

from __future__ import annotations

from sciplot_core.materials_rules.tokens import (  # noqa: F401
    normalize_token,
    _metric_header_matches,
)
from sciplot_core.materials_rules.unit_data import (  # noqa: F401
    NORMALIZED_STRESS_RATIO_DISPLAY_LABEL,
    UnitRule,
    _UNIT_RULES,
    _DIMENSIONLESS_EXPRESSION_LABELS,
    _UNIT_WHOLE_ALIASES,
    _SUPERSCRIPT_DIGITS,
    _PLAIN_SUPERSCRIPTS,
    _SUPERSCRIPT_CHARACTERS,
    _UNIT_BASE_SYMBOLS,
    _UNIT_PREFIXES,
    _UNIT_EXPONENT_RE,
    _UNIT_TEXT_EDGE_PUNCTUATION,
    _PLOT_TEXT_TOKEN_RE,
    _BRACKET_PAIRS,
    _BRACKET_OPEN_BY_CLOSE,
)
from sciplot_core.materials_rules.unit_formatting import (  # noqa: F401
    _unicode_exponent,
    _split_unit_factor_exponent,
    _normalize_unit_symbol,
    _format_unit_factor,
    _format_existing_unit_product,
    _denominator_unit_factors,
    _is_known_unit_symbol,
    _is_known_unit_factor,
    _looks_like_unit_solidus_expression,
    format_unit_label,
)
from sciplot_core.materials_rules.unit_scanning import (  # noqa: F401
    _balanced_bracket_spans,
    _trim_unit_text_candidate,
    _unit_solidus_text_spans,
    format_plot_text_units,
    unit_solidus_violations,
    scientific_unit_expression_contract,
)
from sciplot_core.materials_rules.unit_conversion import (  # noqa: F401
    convert_value,
)
from sciplot_core.materials_rules.models import (  # noqa: F401
    ELONGATION_AT_BREAK_METRIC,
    LEGACY_STRAIN_AT_BREAK_METRIC,
    ELONGATION_AT_BREAK_IQR_METRIC,
    ELONGATION_AT_BREAK_LABEL,
    AxisSpec,
    AnalysisSpec,
    SemanticRule,
    _rule,
)
from sciplot_core.materials_rules.catalog_axes import (  # noqa: F401
    RHEOLOGY_X_FREQUENCY,
    RHEOLOGY_X_TEMPERATURE,
    TIME_AXIS,
    TENSILE_STRAIN_AXIS,
    TENSILE_STRESS_AXIS,
    COMPRESSION_STRAIN_AXIS,
    COMPRESSION_STRESS_AXIS,
    FLEXURAL_STRAIN_AXIS,
    FLEXURAL_STRESS_AXIS,
    TORQUE_AXIS,
)
from sciplot_core.materials_rules.catalog_data import (  # noqa: F401
    RULES,
    _RULE_BY_ID,
)
from sciplot_core.materials_rules.catalog import (  # noqa: F401
    iter_rules,
    get_rule,
    resolve_rule_template,
    _is_ready_rule,
    iter_public_rules,
    list_rules_payload,
    show_rule_payload,
    match_rule,
    _matches_rule_token,
    semantic_payload_from_rule,
)
from sciplot_core.materials_rules.metric_tables import (  # noqa: F401
    _write_metrics_csv,
    _metric,
    _read_labeled_paired_curve_series,
    _read_labeled_paired_curve_table,
    _read_paired_curve_table,
    tensile_curve_metric_values,
)
from sciplot_core.materials_rules.mechanical_metrics import (  # noqa: F401
    _interpolated_threshold_time,
    _stress_relaxation_metrics,
    _creep_metrics,
    _tensile_summary_metrics,
    _tensile_metrics,
    _torque_metrics,
)
from sciplot_core.materials_rules.curve_extrema_metrics import (  # noqa: F401
    _raw_table,
    _tga_metrics,
    _paired_extreme_position_metrics,
    _paired_steepest_drop_position_metrics,
)
from sciplot_core.materials_rules.curve_peak_metrics import (  # noqa: F401
    _ftir_peak_position_metrics,
    _interior_local_peak_position_metrics,
    _terminal_y_metrics,
    _peak_y_metrics,
)
from sciplot_core.materials_rules.thermal_metrics import (  # noqa: F401
    _dsc_metrics,
    _swelling_metrics,
)
from sciplot_core.materials_rules.impact_metrics import (  # noqa: F401
    _impact_metric_tables,
    _impact_metrics,
)
from sciplot_core.materials_rules.analysis import (  # noqa: F401
    _analysis_metric_name,
    compute_analysis_metrics,
)

__all__ = [
    "AnalysisSpec",
    "AxisSpec",
    "NORMALIZED_STRESS_RATIO_DISPLAY_LABEL",
    "ELONGATION_AT_BREAK_IQR_METRIC",
    "ELONGATION_AT_BREAK_LABEL",
    "ELONGATION_AT_BREAK_METRIC",
    "LEGACY_STRAIN_AT_BREAK_METRIC",
    "SemanticRule",
    "UnitRule",
    "compute_analysis_metrics",
    "convert_value",
    "format_plot_text_units",
    "format_unit_label",
    "get_rule",
    "iter_public_rules",
    "iter_rules",
    "list_rules_payload",
    "match_rule",
    "normalize_token",
    "semantic_payload_from_rule",
    "scientific_unit_expression_contract",
    "show_rule_payload",
    "tensile_curve_metric_values",
    "unit_solidus_violations",
]
