"""Resolve closed builtin versions to their retained immutable implementations."""
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import MappingProxyType
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document.errors import DocumentError

from .versions.catalog import LEGACY_DESCRIPTOR, LEGACY_RETAINED_FILES, V1_OPERATORS
from .versions.v1.hashing import canonical_json_sha256


@dataclass(frozen=True)
class BuiltinVersion:
    operator: str
    version: str
    content_hash: str
    entry: str
    runtime: str
    multiple_inputs: bool
    files: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        payload = {"operator": self.operator, "version": self.version, "entry": self.entry,
                   "runtime": self.runtime, "multiple_inputs": self.multiple_inputs, "files": dict(self.files)}
        actual = canonical_json_sha256(payload, allow_nan=False)
        entries = [entry.split(":", 1)[0].replace(".", "/") + ".py" for entry in (self.entry, self.runtime)]
        if actual != self.content_hash or any(name not in dict(self.files) for name in entries):
            raise ValueError("A registered builtin version must seal its actual entry, runtime and dependency pins.")

    def descriptor(self) -> dict[str, Any]:
        return {"kind": "builtin", "operator": self.operator, "version": self.version,
                "content_hash": self.content_hash}

    def execute(self, node: dict[str, Any], sources: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
        operation = _function(self.entry)
        runtime = _function(self.runtime)
        # Check again after imports: a dependency must not drift while loading.
        require_builtin(node)
        result: tuple[dict[str, Any], str] = runtime(node, sources, operation, multiple_inputs=self.multiple_inputs)
        require_builtin(node)
        return result


def _function(entry: str) -> Callable[..., Any]:
    module, function = entry.split(":", 1)
    operation: Callable[..., Any] = getattr(import_module(__package__ + ".versions." + module), function)
    return operation


_VERSIONS = {(kind, "1"): BuiltinVersion(kind, "1", value["content_hash"], value["entry"], value["runtime"],
                                          value["multiple_inputs"], tuple(value["files"].items()))
             for kind, value in V1_OPERATORS.items()}
_CURRENT = {kind: "1" for kind in V1_OPERATORS}
_LEGACY_VERSIONS = MappingProxyType(dict(_VERSIONS))
_LEGACY_FILES = tuple(LEGACY_RETAINED_FILES.items())
_LEGACY_DESCRIPTOR = MappingProxyType(dict(LEGACY_DESCRIPTOR))


def _unavailable(message: str, *, code: str = "transform_executor_unavailable") -> DocumentError:
    error = DocumentError(code, message)
    error.repair = {"action": "restore_builtin_executor", "automatic_retry": False,
                    "automatic_refresh": False}
    return error


def _resolve(kind: str, executor: dict[str, Any]) -> BuiltinVersion:
    if not isinstance(executor, dict) or type(executor.get("version")) is not str:
        raise _unavailable("An exact saved builtin operator version is required.")
    if executor == _LEGACY_DESCRIPTOR:
        version = _VERSIONS.get((kind, "1"))
        if version != _LEGACY_VERSIONS.get((kind, "1")):
            raise _unavailable("The historical builtin alias cannot be redirected to another implementation.")
    else:
        saved_version: str = executor["version"]
        version = _VERSIONS.get((kind, saved_version))
        if executor.get("version") == _LEGACY_DESCRIPTOR["version"] or version is not None and executor != version.descriptor():
            raise _unavailable("The saved builtin descriptor differs from its registered immutable identity.", code="transform_executor_changed")
        if version is None:
            raise _unavailable("The saved builtin operator version and content identity are not installed; restore that exact implementation.")
    if version is None:
        raise _unavailable("No retained implementation exists for this builtin operator.")
    return version


def builtin_executor(kind: str | None = None, *, version: str | None = None) -> dict[str, Any]:
    """New callers name their operator; no-argument calls retain the old wire API."""
    if kind is None:
        if version is not None:
            raise _unavailable("An operator is required to select an implementation version.")
        return dict(_LEGACY_DESCRIPTOR)
    selected_version = version if version is not None else _CURRENT.get(kind)
    if selected_version is None:
        raise _unavailable("The requested builtin operator has no installed version.")
    selected = _VERSIONS.get((kind, selected_version))
    if selected is None:
        raise _unavailable("The requested builtin operator version is not installed.")
    return selected.descriptor()


def builtin_files(kind: str | None = None, executor: dict[str, Any] | None = None) -> dict[str, str]:
    """Return expected pins, never bless current bytes by hashing them as a new version."""
    if kind is None:
        if executor is not None and executor != _LEGACY_DESCRIPTOR:
            raise _unavailable("An operator is required for a versioned implementation.")
        files = dict(_LEGACY_FILES)
    else:
        descriptor = builtin_executor(kind) if executor is None else executor
        selected = _resolve(kind, descriptor)
        files = dict(_LEGACY_FILES) if descriptor == _LEGACY_DESCRIPTOR else dict(selected.files)
    root = Path(__file__).with_name("versions")
    return {str(root / name): sha for name, sha in files.items()}


def require_builtin(node: dict[str, Any]) -> BuiltinVersion:
    """Admission and cache reuse both require the saved implementation's real bytes."""
    selected = _resolve(node["kind"], node["executor"])
    try:
        changed = [path for path, sha in builtin_files(node["kind"], node["executor"]).items()
                   if file_sha256(Path(path)) != sha]
    except OSError as exc:
        raise _unavailable("A retained builtin implementation file is unavailable.") from exc
    if changed:
        error = DocumentError("transform_runtime_changed", "An immutable builtin version or dependency changed in place; restore its exact bytes.")
        error.repair = {"action": "restore_builtin_executor", "automatic_retry": False,
                        "automatic_refresh": False, "changed": changed}
        raise error
    return selected
