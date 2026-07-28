"""Pure Studio project status API and compatibility facade."""

from __future__ import annotations

from sciplot_gui.studio_project_status.project_runs import (  # noqa: F401
    _read_json,
    _request_path_value,
    _validate_project_request_pair,
    _canonical_json_sha256,
    _project_manifest_payload,
    _registered_manifest_candidates,
    _latest_project_run,
)
from sciplot_gui.studio_project_status.source_status import (  # noqa: F401
    _source_reference,
    _source_content_record,
    _source_status,
)
from sciplot_gui.studio_project_status.mapping_status import (  # noqa: F401
    _mapping_application_from_run,
    _mapping_coverage_from_run,
    _bind_mapping_to_artifact_qa,
    _mapping_status,
)
from sciplot_gui.studio_project_status.export_status import (  # noqa: F401
    _normalized_export_format,
    _export_records,
    _verify_export_artifacts,
    _standalone_qa_report_current,
)
from sciplot_gui.studio_project_status.qa_status import (  # noqa: F401
    _qa_display_status,
    _qa_status,
)
from sciplot_gui.studio_project_status.workflow_status import (  # noqa: F401
    _project_audit_state,
    _workflow_status,
    _result_targets,
    _finalize_status,
)
from sciplot_gui.studio_project_status.live_document import (  # noqa: F401
    _live_document_payload,
    _evidence_path,
)
from sciplot_gui.studio_project_status.provenance_status import (  # noqa: F401
    _nonempty_evidence_path,
    _provenance_status,
)
from sciplot_gui.studio_project_status.figure_set_scope import (  # noqa: F401
    _resolve_figure_set_export_scope,
)
from sciplot_gui.studio_project_status.builder import (  # noqa: F401
    build_studio_project_status,
)
from sciplot_gui.studio_project_status.messages import (  # noqa: F401
    export_result_message,
    _short_hash,
    _status_text,
)

__all__ = [
    "build_studio_project_status",
    "export_result_message",
]
