"""Declare launcher filenames, versions, and portable placeholders."""

from __future__ import annotations


DELIVERY_LAUNCHER_CONTRACT_VERSION = 1


PROJECT_LAUNCHER_CONTRACT_VERSION = 4


PROJECT_PRIMARY_LAUNCHER = "Open_in_SciPlot_Studio.command"


PROJECT_VEUSZ_LAUNCHER = "Open_in_Veusz.command"


PROJECT_EXPORT_LAUNCHER = "Export_Edited_Veusz.command"


LEGACY_WEB_WORKBENCH_LAUNCHER = "Open_SciPlot_Project.command"


_PORTABLE_PATH_ASSIGNMENTS = (
    "FALLBACK_REPO",
    "FALLBACK_RUNTIME_REPO",
    "FALLBACK_SOURCE_ROOT",
    "FALLBACK_PYTHON",
    "FALLBACK_WRAPPER",
)


_PORTABLE_PATH_PLACEHOLDER = "<portable-absolute-path>"


_PORTABLE_VSZ_PATH_PLACEHOLDER = "<portable-absolute-vsz-path>"


_PORTABLE_VSZ_NAME_PLACEHOLDER = "<portable-vsz-name>"
