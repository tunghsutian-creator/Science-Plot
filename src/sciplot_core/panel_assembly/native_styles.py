"""Refuse native physical styles whose effective size depends on the canvas."""

from importlib import import_module
from typing import Any

from .errors import AssemblyError


def require_physical_styles(loaded: Any) -> None:
    """Check effective inherited point/physical settings, leaving positions alone."""
    native: Any = import_module("veusz.setting")
    physical_types = (native.DistancePt, native.DisplacementPt, native.DistancePhysical)
    units = {"pt", "mm", "cm", "in", "inch", '"'}
    repair = ("In the original plot, set this style to a fixed physical size in pt and Save. "
              "Then choose Use current source version (or explicitly replace/rebind the panel source) and retry export.")

    def settings(group: Any, prefix: str) -> None:
        for name, item in group.setdict.items():
            path = prefix.rstrip("/") + "/" + name
            if hasattr(item, "setdict"):
                settings(item, path)
            elif isinstance(item, physical_types):
                # get() resolves the actual reference chain, including shared
                # stylesheet fonts. Its declaration alone cannot prove points.
                try:
                    value = item.get()
                    match = item.distre.match(value) if isinstance(value, str) else None
                except ValueError:
                    value, match = "unresolved physical reference", None
                if match is None or match.group(2) not in units:
                    issue = {"code": "relative_native_physical_style", "setting_path": path,
                             "value": value, "repair": repair}
                    raise AssemblyError("assembly_relative_physical_style",
                                        f"Native physical style {path}={value!r} has no fixed physical unit. {repair}",
                                        issues=[issue])

    def widget(path: str, node: Any) -> None:
        # The document's stylesheet includes settings for unused widget types;
        # each real child exposes its effective inherited settings separately.
        if node is not loaded.basewidget:
            settings(node.settings, str(path))

    loaded.walkNodes(widget, nodetypes=("widget",))
