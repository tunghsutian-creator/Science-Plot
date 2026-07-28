"""Publication contract API and first-party compatibility facade."""

from __future__ import annotations

from sciplot_core.publication_layouts import (
    COMPOSITE_CANVAS_WIDTH_MM,
    COMPOSITE_LAYOUT_KIND,
    COMPOSITE_LAYOUT_VERSION,
    COMPOSITE_NOMINAL_CONTENT_WIDTH_MM,
    build_composite_layout,
    list_composite_layouts,
)
from sciplot_core.publication.profiles import (  # noqa: F401
    PUBLICATION_PROFILE_KIND,
    PUBLICATION_PROFILE_VERSION,
    PUBLICATION_INTENT_KIND,
    PUBLICATION_INTENT_VERSION,
    TRANSFORM_LEDGER_KIND,
    TRANSFORM_LEDGER_VERSION,
    DEFAULT_STANDALONE_PROFILE_ID,
    DEFAULT_COMPOSITE_PROFILE_ID,
    _NATURE_FIGURE_GUIDE,
    _NATURE_INITIAL_SUBMISSION,
    _NATURE_FINAL_SUBMISSION,
    _PUBLICATION_PROFILES,
    _standalone_profile,
    list_publication_profiles,
    get_publication_profile,
    resolve_publication_profile,
)
from sciplot_core.publication.intent_helpers import (  # noqa: F401
    _figure_height_mm,
    _statistics_contract_for_figure,
    _explicit_request_text,
    _merge_existing,
    _merge_keyed_contracts,
    _reference_list,
    _figure_contracts,
    _panel_defaults_for_layout,
)
from sciplot_core.publication.intent import (  # noqa: F401
    build_publication_intent,
)
from sciplot_core.publication.artifacts import (  # noqa: F401
    _table_shape,
    artifact_record,
)
from sciplot_core.publication.transform_ledger import (  # noqa: F401
    build_transform_step,
    build_transform_ledger,
    link_intent_to_transform_ledger,
)
from sciplot_core.publication.write import (  # noqa: F401
    write_publication_artifacts,
)

__all__ = [
    "COMPOSITE_CANVAS_WIDTH_MM",
    "COMPOSITE_LAYOUT_KIND",
    "COMPOSITE_LAYOUT_VERSION",
    "COMPOSITE_NOMINAL_CONTENT_WIDTH_MM",
    "PUBLICATION_INTENT_KIND",
    "PUBLICATION_INTENT_VERSION",
    "PUBLICATION_PROFILE_KIND",
    "PUBLICATION_PROFILE_VERSION",
    "TRANSFORM_LEDGER_KIND",
    "TRANSFORM_LEDGER_VERSION",
    "artifact_record",
    "build_composite_layout",
    "build_publication_intent",
    "build_transform_ledger",
    "build_transform_step",
    "get_publication_profile",
    "list_composite_layouts",
    "list_publication_profiles",
    "link_intent_to_transform_ledger",
    "resolve_publication_profile",
    "write_publication_artifacts",
]
