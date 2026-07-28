"""Portable launcher API and compatibility facade."""

from __future__ import annotations

from sciplot_core.launchers.contracts import (  # noqa: F401
    DELIVERY_LAUNCHER_CONTRACT_VERSION,
    PROJECT_LAUNCHER_CONTRACT_VERSION,
    PROJECT_PRIMARY_LAUNCHER,
    PROJECT_VEUSZ_LAUNCHER,
    PROJECT_EXPORT_LAUNCHER,
    LEGACY_WEB_WORKBENCH_LAUNCHER,
    _PORTABLE_PATH_ASSIGNMENTS,
    _PORTABLE_PATH_PLACEHOLDER,
    _PORTABLE_VSZ_PATH_PLACEHOLDER,
    _PORTABLE_VSZ_NAME_PLACEHOLDER,
)
from sciplot_core.launchers.portable_shell import (  # noqa: F401
    _shell_name,
    portable_sciplot_prelude,
    portable_vsz_finder,
)
from sciplot_core.launchers.content_hashing import (  # noqa: F401
    _sha256_text,
    _mask_portable_assignments,
)
from sciplot_core.launchers.delivery_launcher import (  # noqa: F401
    _delivery_launcher_lines,
    write_delivery_launcher,
    _canonical_delivery_launcher_lines,
)
from sciplot_core.launchers.project_launcher import (  # noqa: F401
    _canonical_project_launcher_lines,
)
from sciplot_core.launchers.portable_values import (  # noqa: F401
    _normalize_shell_assignment,
    _normalize_indented_vsz_path,
    _normalize_vsz_name_assignment,
)
from sciplot_core.launchers.structure import (  # noqa: F401
    _launcher_structure,
    _project_launcher_structure,
    _delivery_launcher_structure,
)
from sciplot_core.launchers.delivery_inspection import (  # noqa: F401
    inspect_delivery_launcher_contract,
)
from sciplot_core.launchers.project_inspection import (  # noqa: F401
    _project_launcher_record,
    inspect_project_launcher_contract,
)

__all__ = [
    "DELIVERY_LAUNCHER_CONTRACT_VERSION",
    "LEGACY_WEB_WORKBENCH_LAUNCHER",
    "PROJECT_EXPORT_LAUNCHER",
    "PROJECT_LAUNCHER_CONTRACT_VERSION",
    "PROJECT_PRIMARY_LAUNCHER",
    "PROJECT_VEUSZ_LAUNCHER",
    "inspect_delivery_launcher_contract",
    "inspect_project_launcher_contract",
    "portable_sciplot_prelude",
    "portable_vsz_finder",
    "write_delivery_launcher",
]
