"""Read the native font catalog without initializing Qt in a caller process."""

import json
import sys

from sciplot_core.native_process import run_worker
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.veusz_runtime import veusz_worker_environment


def installed_font_families() -> list[str]:
    """The existing native worker owns Qt on its process main thread."""
    result = run_worker([sys.executable, "-m", "sciplot_core.veusz_worker", "font-families"],
                        env=veusz_worker_environment(), capture_output=True, text=True, timeout=30)
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError):
        payload = None
    if (result.returncode != 0 or not isinstance(payload, dict)
            or set(payload) != {"kind", "version", "families"}
            or payload["kind"] != "sciplot_native_font_catalog" or type(payload["version"]) is not int
            or payload["version"] != 1 or not isinstance(payload["families"], list)
            or not payload["families"] or len(payload["families"]) > 10000
            or not all(isinstance(item, str) and item and len(item) <= 256 for item in payload["families"])):
        raise EngineError("common_edit_font_catalog_unavailable", "The native font catalog could not be verified; repair the native runtime before editing.",
                          action="repair_runtime", request_executed=False)
    families: list[str] = payload["families"]
    if families != sorted(set(families)):
        raise EngineError("common_edit_font_catalog_unavailable", "The native font catalog has invalid family identities.",
                          action="repair_runtime", request_executed=False)
    return families
