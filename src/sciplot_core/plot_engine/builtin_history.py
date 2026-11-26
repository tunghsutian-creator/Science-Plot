"""Read installed implementations against sealed historic builtin fingerprints."""
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_transforms import builtin_files
from sciplot_core.plot_transforms.identity import builtin_version_root
from sciplot_core.plot_transforms.versions.catalog import LEGACY_DESCRIPTOR, LEGACY_ORIGINAL_PATHS

from .managed_source_groups import physical_path


def _rebase(files: dict[str, str], archived: dict[str, str], installed: dict[str, str],
            protected: set[str], *, anchor: str) -> None:
    """Replace exactly one complete recorded layout, never substitute arbitrary paths."""
    suffix = Path(anchor)
    roots = {path.parents[len(suffix.parts) - 1] for name, sha in files.items()
             if (path := Path(name)).is_absolute()
             and path.parts[-len(suffix.parts):] == suffix.parts and sha == archived[anchor]}
    matches = [{str(root / relative): sha for relative, sha in archived.items()} for root in roots]
    matches = [pins for pins in matches if not pins.keys() & protected
               and all(files.get(path) == sha for path, sha in pins.items())]
    if (len(matches) != 1 or installed.keys() & protected
            or installed.keys() & (files.keys() - matches[0].keys())):
        return
    for name in matches[0]:
        del files[name]
    files.update(installed)


def fingerprint_for_read(binding: dict[str, Any]) -> dict[str, Any]:
    """Compare exact historic builtin pins to the installed, still-pinned bytes."""
    result: dict[str, Any] = deepcopy(binding["fingerprint"])
    if binding.get("kind") != "sciplot_managed_binding" or "canonical_document" not in binding:
        return result
    from .managed_state import read_canonical

    document = read_canonical(binding)
    nodes = [node for node in document["scientific"]["transforms"] if node["executor"]["kind"] == "builtin"]
    if not nodes:
        return result
    files = result["files"]
    protected = {source["path"] for source in document["scientific"]["data_sources"]}
    registry = document["scientific"]["provenance"]["managed"].get("executors", {})
    protected.update(executor[field] for executor in registry.values() for field in ("script", "executable"))
    protected |= {physical_path(path) for path in protected}
    if any(node["executor"] == LEGACY_DESCRIPTOR for node in nodes):
        _rebase(files, LEGACY_ORIGINAL_PATHS, {physical_path(path): sha for path, sha in builtin_files().items()},
                protected, anchor="plot_transforms/builtins.py")

    try:
        installed = {path: sha for node in nodes for path, sha in builtin_files(node["kind"], node["executor"]).items()}
    except DocumentError:
        return result  # The existing input admission reports any unavailable installed descriptor.
    if all(files.get(path) == sha for path, sha in installed.items()):
        return result
    root = builtin_version_root()
    prefix = root.parents[2]
    if any(not Path(path).is_relative_to(root) for path in installed):
        return result
    archived = {Path(path).relative_to(prefix).as_posix(): sha for path, sha in installed.items()}
    anchor = (root / "__init__.py").relative_to(prefix).as_posix()
    if anchor in archived:
        _rebase(files, archived, {physical_path(path): sha for path, sha in installed.items()},
                protected, anchor=anchor)
    return result
