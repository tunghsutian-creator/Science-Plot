"""The registered implementation owner seals the actual builtin executor bytes."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_document.errors import DocumentError

from .schema import BUILTIN_VERSION


def builtin_files() -> dict[str, str]:
    root = Path(__file__).parent
    return {str(root / name): file_sha256(root / name)
            for name in ("builtins.py", "datasets.py", "execution.py", "schema.py", "identity.py")}


def builtin_executor() -> dict[str, Any]:
    files = {Path(path).name: sha for path, sha in builtin_files().items()}
    return {"kind": "builtin", "version": BUILTIN_VERSION,
            "content_hash": canonical_json_sha256(files, allow_nan=False)}


_LOADED_FILES = builtin_files()


def require_builtin_runtime_current() -> None:
    if builtin_files() != _LOADED_FILES:
        error = DocumentError("transform_runtime_changed", "Builtin Python code changed after this service loaded; restart before scientific execution.")
        error.repair = {"action": "restart_local_plot_service", "automatic_retry": False}
        raise error
