"""SciPlot CLI command dispatch."""

from sciplot_core.cli.dispatch.diagnostics import dispatch_diagnostics
from sciplot_core.cli.dispatch.governance import dispatch_governance
from sciplot_core.cli.dispatch.interfaces import dispatch_interfaces
from sciplot_core.cli.dispatch.rendering import dispatch_rendering

__all__ = [
    "dispatch_diagnostics",
    "dispatch_governance",
    "dispatch_interfaces",
    "dispatch_rendering",
]
