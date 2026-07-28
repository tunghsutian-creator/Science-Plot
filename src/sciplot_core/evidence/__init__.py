"""Acceptance evidence enrichment and reporting API."""

from __future__ import annotations

from sciplot_core.evidence.json_sources import (  # noqa: F401
    DATA_SUFFIXES,
    HASH_PATTERN,
    _load_json,
    _fixture_files,
)
from sciplot_core.evidence.fixture_inventory import (  # noqa: F401
    _fixture_hash_inventory,
)
from sciplot_core.evidence.provenance import (  # noqa: F401
    _provenance_candidates,
    _expected_fixture_hashes,
    _registered_source_hashes,
)
from sciplot_core.evidence.evidence_status import (  # noqa: F401
    _fixture_hash_status,
    _authorization_status,
    _first_mapping,
)
from sciplot_core.evidence.enrichment import (  # noqa: F401
    enrich_rule_evidence,
    load_candidate_rejections,
)
from sciplot_core.evidence.summary import (  # noqa: F401
    _status_summary,
)
from sciplot_core.evidence.csv_report import (  # noqa: F401
    _write_csv,
)
from sciplot_core.evidence.markdown_report import (  # noqa: F401
    _write_markdown,
)
from sciplot_core.evidence.html_report import (  # noqa: F401
    _pill,
    _write_html,
)
from sciplot_core.evidence.dashboard import (  # noqa: F401
    write_evidence_status_dashboard,
)

__all__ = [
    "enrich_rule_evidence",
    "load_candidate_rejections",
    "write_evidence_status_dashboard",
]
