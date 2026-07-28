"""Rendered source-coverage API and compatibility facade."""

from __future__ import annotations

import subprocess as subprocess  # noqa: F401

from sciplot_core.source_coverage.artifacts import (  # noqa: F401
    _SHA256,
    _required_sha256,
    _current_source_artifact,
    _source_artifact_from_inventory,
    _series_source_artifacts,
    _expected_mapping_outputs,
    _result_path_list,
    _terminal_file_snapshots,
)
from sciplot_core.source_coverage.file_snapshots import (  # noqa: F401
    _canonical_sha256,
    _stat_identity,
    _stable_file_snapshot,
    _assert_snapshot_current,
    _write_private_snapshot,
)
from sciplot_core.source_coverage.document_audit import (  # noqa: F401
    _audit_exact_document_data,
)
from sciplot_core.source_coverage.spec_units import (  # noqa: F401
    _spec_render_data_units,
)
from sciplot_core.source_coverage.terminal_requests import (  # noqa: F401
    _declared_terminal_render_requests,
    _authoritative_terminal_render_requests,
)
from sciplot_core.source_coverage.derivation import (  # noqa: F401
    _remap_derived_source_artifacts,
    _terminal_render_derivation,
)
from sciplot_core.source_coverage.evaluate import (  # noqa: F401
    evaluate_mapping_source_coverage,
)
from sciplot_core.source_coverage.verify import (  # noqa: F401
    verify_rendered_mapping_source_coverage,
)

__all__ = [
    "evaluate_mapping_source_coverage",
    "verify_rendered_mapping_source_coverage",
]
