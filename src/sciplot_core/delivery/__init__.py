"""Visible delivery package API and compatibility facade."""

from __future__ import annotations

from sciplot_core.delivery.contracts import (  # noqa: F401
    PUBLICATION_ARTIFACT_FILENAMES,
    PUBLICATION_ARTIFACT_KINDS,
    DELIVERY_BINDING_POLICY_LEGACY,
    DELIVERY_BINDING_POLICY_RESOLVED_PLAN,
    DELIVERY_PACKAGE_CONTRACT_VERSION,
    _project_slug,
)
from sciplot_core.delivery.figure_pairing import (  # noqa: F401
    _delivery_figure_pairing,
)
from sciplot_core.delivery.project_documents import (  # noqa: F401
    _manifest_veusz_documents,
    _editable_project_name,
    _copy_project_documents,
)
from sciplot_core.delivery.publication_evidence import (  # noqa: F401
    _qa_hash_evidence,
    _publication_status,
)
from sciplot_core.delivery.file_set_validation import (  # noqa: F401
    _recorded_file_set,
)
from sciplot_core.delivery.package_validation import (  # noqa: F401
    verify_delivery_package,
)
from sciplot_core.delivery.package_builder import (  # noqa: F401
    build_delivery_package,
)

__all__ = [
    "DELIVERY_PACKAGE_CONTRACT_VERSION",
    "DELIVERY_BINDING_POLICY_LEGACY",
    "DELIVERY_BINDING_POLICY_RESOLVED_PLAN",
    "build_delivery_package",
    "verify_delivery_package",
]
