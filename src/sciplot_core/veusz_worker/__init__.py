"""Internal Veusz worker API and compatibility facade."""

from __future__ import annotations

from sciplot_core.veusz_worker.operations import (  # noqa: F401
    export_request,
    export_document,
    audit_documents,
    inspect_document_state,
    migrate_unit_labels,
)
from sciplot_core.veusz_worker.numeric_evidence import (  # noqa: F401
    _exact_numeric_token,
    _persisted_expected_numeric_token,
    _numeric_payload,
    _numeric_digest,
    _dataset_evidence,
    _text_dataset_values,
)
from sciplot_core.veusz_worker.widget_bindings import (  # noqa: F401
    _node_is_visible,
    _setting_value,
    _distance_is_positive,
    _distance_matches_mm,
    _distance_matches_pt,
    _style_channel_visible,
    _visible_mark_channels,
    _normalized_setting_value,
    _settings_snapshot,
    _dataset_setting_bindings,
    _visible_data_bindings,
    _numeric_setting_equal,
    _numeric_sequence_equal,
)
from sciplot_core.veusz_worker.axis_matchers import (  # noqa: F401
    _axis_record_matches_spec,
    _scalar_image_matches_contract,
)
from sciplot_core.veusz_worker.visual_matchers import (  # noqa: F401
    _colorbar_record_matches_contract,
    _rect_record_matches_contract,
    _line_record_matches_contract,
    _polygon_record_matches_contract,
    _direct_label_record_matches_contract,
)
from sciplot_core.veusz_worker.contours import (  # noqa: F401
    _expected_contour_records,
    _actual_contour_record,
)
from sciplot_core.veusz_worker.save import (  # noqa: F401
    save_spec,
)
from sciplot_core.veusz_worker.cli import (  # noqa: F401
    _split_formats,
    _build_parser,
    main,
)
from sciplot_core.veusz_worker.spec_audit import audit_spec_data

__all__ = [
    "audit_documents",
    "audit_spec_data",
    "export_document",
    "export_request",
    "inspect_document_state",
    "main",
    "migrate_unit_labels",
    "save_spec",
]
