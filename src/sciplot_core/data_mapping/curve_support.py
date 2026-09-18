"""Rules whose native source adapters consume verified explicit XY tables."""

from sciplot_core.materials_rules.models import SemanticRule


def supports_table_mapping(rule: SemanticRule) -> bool:
    # Specialized analysis adapters are not interchangeable with XY tables.
    return rule.fixture_status == "ready" and rule.scientific_source_adapter in {
        "registered_paired_curve", "ftir",
    }
