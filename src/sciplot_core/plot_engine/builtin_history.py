"""Read old implementation fingerprints without rewriting their sealed history."""
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.plot_transforms import builtin_files
from sciplot_core.plot_transforms.versions.catalog import LEGACY_DESCRIPTOR, LEGACY_ORIGINAL_PATHS


def fingerprint_for_read(binding: dict[str, Any]) -> dict[str, Any]:
    """Compare recognized historic code pins against the retained real version.

    Old filesystem paths remain evidence in the original record. This transient
    comparison view names the installed retained bytes; it never reports that
    the obsolete original path still contains its historic bytes.
    """
    result: dict[str, Any] = deepcopy(binding["fingerprint"])
    if binding.get("kind") != "sciplot_managed_binding" or "canonical_document" not in binding:
        return result
    from .managed_state import read_canonical

    document = read_canonical(binding)
    if not any(node["executor"] == LEGACY_DESCRIPTOR for node in document["scientific"]["transforms"]):
        return result
    files = result["files"]
    anchor = "plot_transforms/builtins.py"
    prefixes = [Path(path).parents[1] for path, sha in files.items()
                if Path(path).as_posix().endswith("/" + anchor) and sha == LEGACY_ORIGINAL_PATHS[anchor]]
    protected = {source["path"] for source in document["scientific"]["data_sources"]}
    registry = document["scientific"]["provenance"]["managed"].get("executors", {})
    protected.update(executor[field] for executor in registry.values() for field in ("script", "executable"))
    matches = [{str(prefix / relative): sha for relative, sha in LEGACY_ORIGINAL_PATHS.items()} for prefix in prefixes]
    matches = [pins for pins in matches if not pins.keys() & protected and all(files.get(path) == sha for path, sha in pins.items())]
    if len(matches) != 1:
        return result
    for path in matches[0]:
        del files[path]
    files.update(builtin_files())
    return result
