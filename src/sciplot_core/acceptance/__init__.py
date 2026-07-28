"""Real-data acceptance API and compatibility facade."""

from __future__ import annotations

from sciplot_core.acceptance.fixtures import (  # noqa: F401
    DEFAULT_3DPA_FTIR_LABELS,
    DEFAULT_3DPA_TORQUE_DIRS,
    DEFAULT_DENSE_SERIES_COUNT,
    DEFAULT_REPRESENTATIVE_COUNT,
    RULE_ACCEPTANCE_VERSION,
    RULE_ACCEPTANCE_CHECK_IDS,
    SpectrumSeries,
    _public_fixture_index,
    _real_world_fixture_index,
    _rule_fixture_evidence,
)
from sciplot_core.acceptance.rule_matrix import (  # noqa: F401
    _rule_matrix_row,
    build_rule_acceptance_matrix,
    _delivery_artifact_passed,
    _manual_edit_probe,
)
from sciplot_core.acceptance.rule_template import (  # noqa: F401
    _run_rule_template_acceptance,
)
from sciplot_core.acceptance.rule_lifecycle import (  # noqa: F401
    _run_rule_lifecycle_acceptance,
)
from sciplot_core.acceptance.rule_reports import (  # noqa: F401
    _write_rule_acceptance_csv,
    _write_rule_acceptance_markdown,
)
from sciplot_core.acceptance.rule_suite import (  # noqa: F401
    run_rule_acceptance_suite,
)
from sciplot_core.acceptance.three_dpa_sources import (  # noqa: F401
    _normalize_label,
    _candidate_ftir_dirs,
    _find_ftir_files,
    _candidate_torque_dirs,
    _find_torque_dir,
    _sample_label,
    _read_raw_spectrum,
    _load_spectra,
    _write_curve_table,
    _build_dense_series,
    _write_request,
)
from sciplot_core.acceptance.three_dpa_runs import (  # noqa: F401
    _manifest_summary,
    _run_acceptance_request,
    _run_torque_acceptance,
    run_3dpa_acceptance,
)

__all__ = [
    "DEFAULT_3DPA_FTIR_LABELS",
    "DEFAULT_3DPA_TORQUE_DIRS",
    "DEFAULT_DENSE_SERIES_COUNT",
    "DEFAULT_REPRESENTATIVE_COUNT",
    "RULE_ACCEPTANCE_CHECK_IDS",
    "RULE_ACCEPTANCE_VERSION",
    "build_rule_acceptance_matrix",
    "run_3dpa_acceptance",
    "run_rule_acceptance_suite",
]
