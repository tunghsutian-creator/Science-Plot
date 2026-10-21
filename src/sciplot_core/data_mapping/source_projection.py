"""Project verified source correspondence without interpreting display labels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.mapping_contract import DataMappingProposal
from sciplot_core.mapping_contract.source_identity import proposal_source_identities


def mapping_source_groups(execution: dict[str, Any], *, replicates: bool | None = None) -> list[dict[str, Any]]:
    """Read the proposal only after the execution owner has verified its bytes."""
    proposal = DataMappingProposal.from_dict(json.loads(Path(execution["proposal"]).read_text()))
    if replicates is not None and ("replicates" in proposal.table_confirmation) != replicates:
        return []
    identities = proposal_source_identities(proposal)
    if not identities:
        return []
    outputs = {item["source_id"]: item for item in execution["outputs"]}
    return [{"source_id": source.source_id, **source.identity,
             "sample": proposal.sample_labels[source.source_id],
             "display_label": proposal.display_labels.get(source.source_id, proposal.sample_labels[source.source_id]),
             "path": outputs[source.source_id]["path"], "sha256": outputs[source.source_id]["sha256"],
             "rows": outputs[source.source_id]["rows"]} for source in proposal.sources]


def verified_mapping_source_groups(request: dict[str, Any], *, replicates: bool | None = None) -> list[dict[str, Any]]:
    application = request.get("data_mapping_application") or {}
    if not application.get("source_groups"):
        return []
    from sciplot_core.data_mapping.execution_loading import load_data_mapping_execution

    # This owner reproduces original sheet/column/row domains, null positions,
    # source SHA and mapped array bytes. A CSV or an application claim alone
    # cannot establish the correspondence consumed by rendering.
    execution = load_data_mapping_execution(application["execution"])
    groups = mapping_source_groups(execution)
    if application["source_groups"] != groups:
        raise ValueError("The source-group projection differs from its verified mapping receipt.")
    return groups if replicates is None else mapping_source_groups(execution, replicates=replicates)
