"""Build the immutable transform-step parameter payload for mapping execution."""

from __future__ import annotations

from typing import Any
from sciplot_core.mapping_contract import (
    DataMappingConfirmation,
    DataMappingProposal,
    LegacyDataMappingConfirmation,
)

from sciplot_core.data_mapping.contracts import (
    data_mapping_proposal_sha256,
)


def _mapping_step_parameters(
    proposal: DataMappingProposal,
    confirmation: DataMappingConfirmation | LegacyDataMappingConfirmation,
) -> dict[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "proposal_sha256": data_mapping_proposal_sha256(proposal),
        "provider": proposal.provider,
        "confirmation_id": confirmation.confirmation_id,
        "confirmed_by": confirmation.confirmed_by,
        "source_hashes": proposal.source_hashes,
        "column_mappings": [mapping.to_dict() for mapping in proposal.columns],
        "transformations": [
            transformation.to_dict() for transformation in proposal.transformations
        ],
        "request_patch": proposal.request_patch,
        "raw_sources_preserved": True,
        "silent_omission_allowed": False,
    }
