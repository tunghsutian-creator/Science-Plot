"""Final-size visual-review API and compatibility facade."""

from __future__ import annotations

import os as os

from sciplot_core.visual_review.transaction import (  # noqa: F401
    PHYSICAL_SIZE_TOLERANCE_MM,
    TIFF_DPI_TOLERANCE,
    CONTACT_SHEET_COLUMNS,
    CONTACT_SHEET_ROWS,
    CONTACT_SHEET_TILE_SIZE,
    FINAL_SIZE_VISUAL_REVIEW_VERSION,
    FINAL_SIZE_VISUAL_DECISION_VERSION,
    REVIEW_SURFACE,
    PENDING_REVIEW_STATUS,
    REQUIRED_PREVIEW_CHECKS,
    _json_bytes,
    _bytes_sha256,
    _stage_bytes,
    _replace_files_transactionally,
)
from sciplot_core.visual_review.artifact_records import (  # noqa: F401
    _parse_size_mm,
    _round_pair,
    _size_pair,
    _expected_size_from_manifest,
    _within_tolerance,
    _delivery_figure,
    _pdf_size_mm,
    _tiff_metadata,
    _record_for_row,
)
from sciplot_core.visual_review.contact_sheets import (  # noqa: F401
    _contact_sheet_label,
    _write_contact_sheets,
    _contact_sheet_metadata,
    _write_csv,
)
from sciplot_core.visual_review.report_text import (  # noqa: F401
    _markdown_text,
    _write_markdown,
    _html_text,
    _write_html,
)
from sciplot_core.visual_review.write_review import (  # noqa: F401
    write_final_size_visual_review,
)
from sciplot_core.visual_review.decision_validation import (  # noqa: F401
    _read_json_object_strict,
    _strict_nonnegative_int,
    _strict_positive_pair,
    _validate_passed_record,
    _validate_records,
    _validate_summary,
    _validate_manual_source,
    _validate_contact_sheets,
)
from sciplot_core.visual_review.evidence_binding import (  # noqa: F401
    _resolved_artifact_path,
    _validate_acceptance_binding,
    _validate_evidence_binding,
    _validate_existing_decision,
)
from sciplot_core.visual_review.record_decision import (  # noqa: F401
    record_final_size_visual_decision,
)

__all__ = [
    "CONTACT_SHEET_COLUMNS",
    "CONTACT_SHEET_ROWS",
    "PHYSICAL_SIZE_TOLERANCE_MM",
    "TIFF_DPI_TOLERANCE",
    "record_final_size_visual_decision",
    "write_final_size_visual_review",
]
