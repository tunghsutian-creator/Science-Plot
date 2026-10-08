"""Versioned render recipes, separately from the generated artifact byte seals."""

from importlib import metadata
import os
from pathlib import Path
import sys
from typing import Any

from sciplot_core._paths import PACKAGE_ROOT, VEUSZ_ROOT, VEUSZ_UPSTREAM_COMMIT
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_document.dependency import artifact_build_key
from sciplot_core.native_process import verified_runtime_identity


def _digest(value: Any) -> str:
    return canonical_json_sha256(value, allow_nan=False)


def _version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "not-installed"


def _source_digest(directory: Path) -> str:
    return _digest({str(path.relative_to(directory)): existing_file_sha256(path)
                    for path in sorted(directory.rglob("*.py"))})


def runtime_identity() -> dict[str, str]:
    """Read versions/recipe bytes without importing Qt or starting a native worker."""
    environment = {key: os.environ.get(key, "") for key in (
        "QT_QPA_PLATFORM", "QT_QPA_FONTDIR", "FONTCONFIG_FILE", "FONTCONFIG_PATH",
        "SCIPLOT_BUNDLED_QT_LIB", "DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH",
    )}
    return {
        "recipe_version": "sciplot-render-recipe-1", "python_runtime": sys.version,
        "native_process_runtime_sha256": verified_runtime_identity(),
        "python_executable_sha256": existing_file_sha256(Path(sys.executable)) or "unavailable",
        "platform": sys.platform,
        "adapter_source_sha256": _source_digest(PACKAGE_ROOT / "plot_backends"),
        "worker_source_sha256": _source_digest(PACKAGE_ROOT / "veusz_worker"),
        "renderer_source_sha256": _source_digest(PACKAGE_ROOT / "studio_render"),
        "veusz_upstream_commit": VEUSZ_UPSTREAM_COMMIT,
        "veusz_python_source_sha256": _source_digest(VEUSZ_ROOT / "veusz"),
        "veusz_version_file_sha256": existing_file_sha256(VEUSZ_ROOT / "VERSION") or "unavailable",
        "veusz_installation": str(VEUSZ_ROOT),
        "PyQt6": _version("PyQt6"), "PyQt6-Qt6": _version("PyQt6-Qt6"),
        "numpy": _version("numpy"), "runtime_environment_sha256": _digest(environment),
    }


def build_metadata(document: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    """Requested fonts are known; resolved system font file bytes are not observed."""
    versions = runtime_identity()
    configuration = binding.get("font_configuration", {"kind": "unobserved"})
    fonts = {"requested_configuration_sha256": _digest(configuration),
             "coverage": "requested_configuration_only_resolved_font_files_unobserved"}
    recipe = artifact_build_key(scientific_hash=document["scientific_hash"],
        presentation_hash=document["presentation_hash"], backend_versions=versions,
        export_configuration=document["presentation"]["export_configuration"], fonts=fonts)
    return {"build_key": _digest({"recipe": recipe, "native_binding": binding["fingerprint"]}),
            "recipe_key": recipe, "backend_versions": versions, "fonts": fonts}


def build_key(document: dict[str, Any], binding: dict[str, Any]) -> str:
    return str(build_metadata(document, binding)["build_key"])
