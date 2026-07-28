"""Public declarative data-mapping contract API."""

from __future__ import annotations

from sciplot_core.mapping_contract.constants import (  # noqa: F401
    DATA_MAPPING_PROPOSAL_KIND,
    DATA_MAPPING_PROPOSAL_VERSION,
    DATA_MAPPING_CONFIRMATION_KIND,
    DATA_MAPPING_CONFIRMATION_LEGACY_VERSION,
    DATA_MAPPING_CONFIRMATION_VERSION,
    DECLARATIVE_TRANSFORMATIONS,
    DATA_COLUMN_ROLES,
    DATA_MAPPING_REQUEST_PATCH_KEYS,
    _REPLICATE_MODES,
    _SAFE_ID,
    _SHA256,
    _FORBIDDEN_EXECUTABLE_KEYS,
)
from sciplot_core.mapping_contract.values import (  # noqa: F401
    _now,
    _absolute_path,
    _timestamp,
    _required_text,
    _free_text,
    _text_parameter,
    _safe_id,
    _sha256,
    _optional_text,
    _relative_source_path,
    _text_list,
    _int_list,
    _reject_executable_keys,
    _string_mapping,
)
from sciplot_core.mapping_contract.transform_validation import (  # noqa: F401
    _validate_condition,
    _validate_transform_parameters,
    _validate_request_patch,
)
from sciplot_core.mapping_contract.source_reference import (  # noqa: F401
    DataSourceReference,
)
from sciplot_core.mapping_contract.column_mapping import (  # noqa: F401
    DataColumnMapping,
)
from sciplot_core.mapping_contract.transformation import (  # noqa: F401
    DeclarativeTransformation,
)
from sciplot_core.mapping_contract.proposal import (  # noqa: F401
    DataMappingProposal,
)
from sciplot_core.mapping_contract.confirmation import (  # noqa: F401
    LegacyDataMappingConfirmation,
    DataMappingConfirmation,
)

__all__ = [
    "DATA_COLUMN_ROLES",
    "DATA_MAPPING_CONFIRMATION_KIND",
    "DATA_MAPPING_CONFIRMATION_LEGACY_VERSION",
    "DATA_MAPPING_CONFIRMATION_VERSION",
    "DATA_MAPPING_PROPOSAL_KIND",
    "DATA_MAPPING_PROPOSAL_VERSION",
    "DATA_MAPPING_REQUEST_PATCH_KEYS",
    "DECLARATIVE_TRANSFORMATIONS",
    "DataColumnMapping",
    "DataMappingConfirmation",
    "DataMappingProposal",
    "DataSourceReference",
    "DeclarativeTransformation",
    "LegacyDataMappingConfirmation",
]
