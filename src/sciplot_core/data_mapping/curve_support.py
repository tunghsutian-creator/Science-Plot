"""Rules whose native source adapters consume verified explicit XY tables."""

from typing import Literal

from sciplot_core.materials_rules.models import SemanticRule


def supports_table_mapping(rule: SemanticRule) -> bool:
    # Specialized analysis adapters are not interchangeable with XY tables.
    return rule.fixture_status == "ready" and rule.scientific_source_adapter in {
        "registered_paired_curve", "ftir", "stress_relaxation",
    }


def supports_replicate_mapping(rule: SemanticRule) -> bool:
    """The existing wide replicate adapter consumes independent value columns."""
    return (rule.fixture_status == "ready" and rule.figure_plan_adapter == "impact"
            and rule.presentation_data_shape == "categorical_replicates")


def table_mapping_shape(rule: SemanticRule, *, summary_statistic: object) -> Literal["xy", "replicates"]:
    """Choose shape from verified scientific fields, independently of source prose."""
    return "replicates" if summary_statistic == "raw_only" and supports_replicate_mapping(rule) else "xy"
