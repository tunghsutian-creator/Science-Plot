"""Pure root binding checks for one owned public-stage observation."""
from pathlib import Path
from collections.abc import Mapping

STAGE_ROOTS = (("SCIPLOT_REPO", "."), ("SCIPLOT_SOURCE_ROOT", "src"),
               ("SCIPLOT_RUNTIME_REPO", "."), ("SCIPLOT_VEUSZ_ROOT", "third_party/veusz"))


def require_stage_environment(root: Path, environment: Mapping[str, str]) -> None:
    if "SCIPLOT_REFERENCE_DATA" in environment:
        raise ValueError("Controlled public stages reject inherited reference-data configuration.")
    if any(environment.get(key) != str(root / relative) for key, relative in STAGE_ROOTS):
        raise ValueError("Controlled public source/runtime environment does not bind the actual stage.")
