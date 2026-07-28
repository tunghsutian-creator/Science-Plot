"""Runtime smoke gate API and compatibility facade."""

from __future__ import annotations

from sciplot_core.smoke.contracts import (  # noqa: F401
    RUNTIME_SMOKE_VERSION,
    EXPECTED_RULE_ID,
    MANUAL_EDIT_MARKER,
    EXPECTED_SCALAR_VISUAL_ATTACK_IDS,
    _check,
    _inspect_veusz_document_state,
    _delivery_artifact,
)
from sciplot_core.smoke.delivery import (  # noqa: F401
    _delivery_layout_probe,
)
from sciplot_core.smoke.runtime_environment import (  # noqa: F401
    _package_import_probe,
    _source_checkout_wrapper_probe,
    _qt_mainwindow_probe,
    _portable_launcher_probe,
    _relocated_delivery_launcher_probe,
    _standalone_export_probe,
)
from sciplot_core.smoke.data_mapping import (  # noqa: F401
    _write_synthetic_ftir,
    _data_mapping_studio_lifecycle_probe,
    _transform_parameters,
)
from sciplot_core.smoke.semantic_parser import (  # noqa: F401
    _semantic_parser_probe,
)
from sciplot_core.smoke.direct_labels import (  # noqa: F401
    _direct_label_contract_probe,
)
from sciplot_core.smoke.scalar_field import (  # noqa: F401
    _scalar_field_render_probe,
)
from sciplot_core.smoke.runtime import (  # noqa: F401
    _run_hash_failure_probe,
    run_runtime_smoke,
)

__all__ = ["run_runtime_smoke"]
