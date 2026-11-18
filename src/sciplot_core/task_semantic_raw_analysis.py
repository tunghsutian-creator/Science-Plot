"""Analyze a verified raw curve using the existing scientific metrics owner."""
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.task_errors import TaskControlError


def raw_curve_analysis(source: Path, rule_id: str, plan: dict[str, Any], source_sha256: str) -> list[dict[str, Any]]:
    """Run the same registered scientific analysis on the verified canonical curve."""
    from tempfile import TemporaryDirectory

    from sciplot_core.materials_rules.analysis import compute_analysis_metrics
    from sciplot_core.materials_rules.catalog import get_rule, semantic_payload_from_rule
    from sciplot_core.semantic_sources.curve_output import _write_curve_table
    from sciplot_core.semantic_sources.scientific_source_single_curve import resolve_single_curve_transform

    rule = get_rule(rule_id)
    resolved = resolve_single_curve_transform(source, rule=rule)
    if file_sha256(source) != source_sha256 or resolved.contract.to_payload() != plan["scientific_transform"]:
        raise TaskControlError("source_changed", "The original scientific curve changed before its analysis.")
    # The old owner analyzes this normalized table. Using its exact writer
    # preserves header aliases and per-sample parsing even for TSV originals.
    with TemporaryDirectory(prefix="sciplot-raw-analysis-") as directory:
        workspace = Path(directory)
        canonical = workspace / "curve.csv"
        _write_curve_table(list(resolved.series), canonical)
        semantic = semantic_payload_from_rule(rule, confidence=100.0)
        return compute_analysis_metrics(source_path=canonical, processed_source=canonical,
                                        semantic=semantic, output_dir=workspace)
