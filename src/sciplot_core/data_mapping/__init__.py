"""Public confirmed data-mapping lifecycle API."""

from __future__ import annotations

from sciplot_core.data_mapping.contracts import (  # noqa: F401
    DATA_MAPPING_PREVIEW_KIND,
    DATA_MAPPING_PREVIEW_VERSION,
    DATA_MAPPING_EXECUTION_KIND,
    DATA_MAPPING_EXECUTION_VERSION,
    DATA_MAPPING_APPLICATION_KIND,
    DATA_MAPPING_APPLICATION_VERSION,
    DATA_MAPPING_PROPOSAL_FILENAME,
    DATA_MAPPING_CONFIRMATION_FILENAME,
    DATA_MAPPING_PREVIEW_FILENAME,
    DATA_MAPPING_EXECUTION_FILENAME,
    DATA_MAPPING_REQUEST_FILENAME,
    DATA_MAPPING_REQUEST_SEED_FILENAME,
    DATA_MAPPING_BASE_REQUEST_FILENAME,
    DATA_MAPPING_BASE_LEDGER_FILENAME,
    _SUPPORTED_TABLE_SUFFIXES,
    _MISSING_STRINGS,
    _NUMERIC_COLUMN_ROLES,
    _PRIMARY_NUMERIC_COLUMN_ROLES,
    _DECIMAL_COMMA_NUMBER,
    _now,
    _canonical_sha256,
    data_mapping_proposal_sha256,
    _write_json,
    _read_json,
    load_data_mapping_proposal,
    load_data_mapping_confirmation,
    _resolve_source_root,
    _resolve_request_path,
    _resolve_source_path,
    verify_data_mapping_sources,
    _verify_request_binding,
    create_data_mapping_confirmation,
    write_data_mapping_confirmation,
    _validate_confirmation,
    _validate_confirmation_paths,
)
from sciplot_core.data_mapping.raw_tables import (  # noqa: F401
    _RawTable,
    _detect_delimiter,
    _cell_text,
    _normalize_missing,
    _normalize_decimal_comma,
    _read_raw_table,
    _column_mappings_for_source,
    _map_columns,
    _require_columns,
    _numeric_series,
    _deterministic_sort_key,
    _condition_mask,
)
from sciplot_core.data_mapping.transformations import (  # noqa: F401
    _apply_transformation,
)
from sciplot_core.data_mapping.source_mapping import (  # noqa: F401
    _apply_source_mapping,
    _prepare_mapping_frames,
    preview_data_mapping_proposal,
)
from sciplot_core.data_mapping.output_files import (  # noqa: F401
    _safe_output_name,
    _filename_collision_key,
    _write_mapped_csv,
    _mapped_csv_sha256,
    _rebase_paths,
    _stable_id,
)
from sciplot_core.data_mapping.request_rebinding import (  # noqa: F401
    _rebind_study_model,
    _candidate_request,
)
from sciplot_core.data_mapping.execution import (  # noqa: F401
    _validate_existing_execution,
    execute_data_mapping_proposal,
)
from sciplot_core.data_mapping.execution_shared import (  # noqa: F401
    _mapping_step_parameters,
)
from sciplot_core.data_mapping.execution_loading import (  # noqa: F401
    load_data_mapping_execution,
)
from sciplot_core.data_mapping.request_resolution import (  # noqa: F401
    resolve_data_mapping_request,
)

__all__ = [
    "DATA_MAPPING_APPLICATION_KIND",
    "DATA_MAPPING_APPLICATION_VERSION",
    "DATA_MAPPING_BASE_REQUEST_FILENAME",
    "DATA_MAPPING_BASE_LEDGER_FILENAME",
    "DATA_MAPPING_CONFIRMATION_FILENAME",
    "DATA_MAPPING_EXECUTION_FILENAME",
    "DATA_MAPPING_EXECUTION_KIND",
    "DATA_MAPPING_EXECUTION_VERSION",
    "DATA_MAPPING_PREVIEW_FILENAME",
    "DATA_MAPPING_PREVIEW_KIND",
    "DATA_MAPPING_PREVIEW_VERSION",
    "DATA_MAPPING_PROPOSAL_FILENAME",
    "DATA_MAPPING_REQUEST_FILENAME",
    "DATA_MAPPING_REQUEST_SEED_FILENAME",
    "create_data_mapping_confirmation",
    "data_mapping_proposal_sha256",
    "execute_data_mapping_proposal",
    "load_data_mapping_confirmation",
    "load_data_mapping_execution",
    "load_data_mapping_proposal",
    "preview_data_mapping_proposal",
    "resolve_data_mapping_request",
    "verify_data_mapping_sources",
    "write_data_mapping_confirmation",
]
