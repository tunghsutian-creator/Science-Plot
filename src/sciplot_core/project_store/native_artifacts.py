"""Per-command metadata artifacts are distinct from scientific source identities."""
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any

from sciplot_core.foundation.source_locations import resolve_source_path, selected_source_resolver
from .errors import ProjectConflict, ProjectStoreError
from .io import digest, directory, read_file, sha
from .locators import logical_for_literal
from .runtime import resolve_runtime_output_path
from .source_resolver import ProjectSourceResolver


def _path(value: Any) -> Path:
    if not isinstance(value, (str, Path)):
        raise ProjectStoreError("A native artifact requires one exact absolute file path.")
    path = Path(value)
    if (not path.is_absolute() or str(path) != str(value) or ".." in path.parts or "\x00" in str(path)
            or len(str(path)) > 8192):
        raise ProjectStoreError("A native artifact cannot use an alias or relative path.")
    return path


@dataclass(frozen=True)
class NativeArtifactInput:
    role: str
    path: Path
    sha256: str
    mode: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _path(self.path))
        if (not isinstance(self.role, str) or not isinstance(self.sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None
                or type(self.mode) is not int or not 0 <= self.mode <= 0o777):
            raise ProjectStoreError("A native metadata input requires its exact role, hash and ordinary mode.")


@dataclass(frozen=True)
class NativeArtifactOutput:
    role: str
    path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _path(self.path))
        if not isinstance(self.role, str):
            raise ProjectStoreError("A native artifact output requires its exact argument role.")


@contextmanager
def _parent(path: Path) -> Iterator[int]:
    root = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with directory(root, path.parts[1:-1]) as fd:
            yield fd
    finally:
        os.close(root)


def _argument(argv: list[str], role: str, output: bool) -> Path:
    command = argv[0] if argv else ""
    positional = {("compile-plot-ir", "ir", False): 1, ("compile-plot-ir", "document", True): 2,
        ("inspect-plot-ir", "ir", False): 1, ("inspect-plot-ir", "document", False): 2,
        ("preview-document", "document", False): 1, ("export-document", "document", False): 1,
        ("audit-spec-data", "document", False): 1,
        ("inspect-document-state", "document", False): 1,
        ("validate-document-settings", "document", False): 1}
    options = {("compile-plot-ir", "preview", True): "--preview", ("preview-document", "out", True): "--out",
        ("validate-document-settings", "changes", False): "--changes"}
    key = (command, role, output)
    if key in positional:
        index = positional[key]
    elif key in options and argv.count(options[key]) == 1:
        index = argv.index(options[key]) + 1
    else:
        raise ProjectStoreError("This native command has no admitted metadata file in that argument role.")
    if index >= len(argv):
        raise ProjectStoreError("A native artifact role is absent from its exact command.")
    return _path(argv[index])


def _input(item: dict[str, Any]) -> None:
    path = _path(item["path"])
    with _parent(path) as fd:
        data, mode = read_file(fd, path.name, owned=True)
    if sha(data) != item["sha256"] or mode != item["mode"]:
        raise ProjectConflict("The native metadata input changed its frozen hash or mode.")


def _output(item: dict[str, Any], resolver: ProjectSourceResolver) -> None:
    path = _path(item["path"])
    known = None
    try:
        known = logical_for_literal(resolver.snapshot, str(path))
    except ProjectStoreError:
        pass  # Exact hidden metadata witnesses confer no surrounding namespace.
    try:
        logical = resolver.store.logical_path(path)
    except ProjectStoreError:
        logical = None
    if (known is not None or logical in resolver.snapshot["files"]
            or any(entry.get("locator") == str(path) for versions in resolver.snapshot["sources"].values()
                   for entry in versions.values())):
        raise ProjectConflict("Native artifact outputs cannot replace canonical project or scientific resources.")
    with _parent(path) as fd:
        info = os.fstat(fd)
        if (info.st_uid != os.geteuid() or info.st_mode & 0o022
                or {"device": info.st_dev, "inode": info.st_ino} != item["parent"]):
            raise ProjectConflict("The native output's exact host-owned parent changed identity.")
        try:
            os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return
    raise ProjectConflict("A native metadata output must be a new file, preserving every existing artifact.")


@dataclass(frozen=True)
class _Selection:
    argv_sha256: str
    project_id: str
    generation: str
    inputs: tuple[dict[str, Any], ...]
    outputs: tuple[dict[str, Any], ...]


_SELECTED: ContextVar[_Selection | None] = ContextVar("native_metadata_artifacts", default=None)


def artifact_payload(value: Any) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    if (not isinstance(value, dict) or set(value) != {"inputs", "outputs"}
            or any(not isinstance(value[key], list) for key in value)
            or not 1 <= len(value["inputs"]) + len(value["outputs"]) <= 16):
        raise ProjectStoreError("Invalid finite native metadata file witnesses.")
    for item in value["inputs"]:
        if not isinstance(item, dict) or set(item) != {"role", "path", "sha256", "mode"}:
            raise ProjectStoreError("Invalid closed native metadata input.")
        NativeArtifactInput(item["role"], _path(item["path"]), item["sha256"], item["mode"])
    for item in value["outputs"]:
        if (not isinstance(item, dict) or set(item) != {"role", "path", "parent"}
                or not isinstance(item["parent"], dict) or set(item["parent"]) != {"device", "inode"}
                or any(type(item["parent"][key]) is not int or item["parent"][key] < 0 for key in item["parent"])):
            raise ProjectStoreError("Invalid closed native metadata output.")
        NativeArtifactOutput(item["role"], _path(item["path"]))
    items = [*value["inputs"], *value["outputs"]]
    if len({item["role"] for item in items}) != len(items) or len({item["path"] for item in items}) != len(items):
        raise ProjectStoreError("Native artifact roles and exact file paths must be unambiguous.")
    return tuple(deepcopy(value["inputs"])), tuple(deepcopy(value["outputs"]))


def native_artifact_binding(argv: list[str], resolver: ProjectSourceResolver | None) -> dict[str, Any] | None:
    selected = _SELECTED.get()
    if selected is None:
        return None
    if (resolver is None or selected.argv_sha256 != digest(argv)
            or (selected.project_id, selected.generation) != (resolver.snapshot["project_id"], resolver.generation)):
        raise ProjectConflict("Native metadata witnesses belong to a different command or project generation.")
    return deepcopy({"inputs": list(selected.inputs), "outputs": list(selected.outputs)})


def require_native_artifact_command(argv: list[str]) -> None:
    selected = _SELECTED.get()
    if selected is not None and selected.argv_sha256 != digest(argv):
        raise ProjectConflict("Native metadata witnesses cannot authorize a different command argument list.")


@contextmanager
def bound_native_artifacts(value: Any, argv: list[str], resolver: ProjectSourceResolver | None) -> Iterator[None]:
    token = _SELECTED.set(None)
    try:
        if value is not None:
            if resolver is None:
                raise ProjectStoreError("Native metadata witnesses require their explicit project generation.")
            inputs, outputs = artifact_payload(value)
            required = {"compile-plot-ir": ({"ir"}, {"document", "preview"}),
                "inspect-plot-ir": ({"ir", "document"}, set()), "preview-document": ({"document"}, {"out"}),
                "export-document": ({"document"}, set()), "inspect-document-state": ({"document"}, set())}
            required["audit-spec-data"] = ({"document"}, set())
            required["validate-document-settings"] = ({"document", "changes"}, set())
            roles = ({item["role"] for item in inputs}, {item["role"] for item in outputs})
            if not argv or required.get(argv[0]) != roles:
                raise ProjectStoreError("A native command requires its complete closed metadata input/output witnesses.")
            for output, items in ((False, inputs), (True, outputs)):
                for item in items:
                    if _argument(argv, item["role"], output) != Path(item["path"]):
                        raise ProjectConflict("The metadata witness differs from its exact argument role.")
                    _output(item, resolver) if output else _input(item)
            _SELECTED.set(_Selection(digest(argv), resolver.snapshot["project_id"], resolver.generation, inputs, outputs))
        yield
    finally:
        _SELECTED.reset(token)


@contextmanager
def native_artifact_runtime(argv: list[str], *, inputs: Sequence[NativeArtifactInput] = (),
                            outputs: Sequence[NativeArtifactOutput] = ()) -> Iterator[None]:
    resolver = selected_source_resolver()
    if not isinstance(resolver, ProjectSourceResolver) or _SELECTED.get() is not None:
        raise ProjectStoreError("Native artifact IO requires one host-selected project invocation.")
    if (any(not isinstance(item, NativeArtifactInput) for item in inputs)
            or any(not isinstance(item, NativeArtifactOutput) for item in outputs)):
        raise ProjectStoreError("A host native artifact scope requires typed finite file witnesses.")
    captured_inputs = [{"role": item.role, "path": str(item.path), "sha256": item.sha256, "mode": item.mode} for item in inputs]
    captured_outputs = []
    for item in outputs:
        with _parent(item.path) as fd:
            info = os.fstat(fd)
        captured_outputs.append({"role": item.role, "path": str(item.path), "parent": {"device": info.st_dev, "inode": info.st_ino}})
    with bound_native_artifacts({"inputs": captured_inputs, "outputs": captured_outputs}, argv, resolver):
        yield


def resolve_native_artifact(original: str | Path, *, role: str, output: bool = False,
                            expected_sha256: str | None = None, source_id: str | None = None) -> Path:
    if source_id is not None:
        return resolve_source_path(original, expected_sha256=expected_sha256, source_id=source_id)
    resolver = selected_source_resolver()
    selected = _SELECTED.get()
    if selected is not None:
        if (not isinstance(resolver, ProjectSourceResolver)
                or (selected.project_id, selected.generation) != (resolver.snapshot["project_id"], resolver.generation)):
            raise ProjectConflict("The native metadata scope differs from the selected generation.")
        items = selected.outputs if output else selected.inputs
        item = next((entry for entry in items if entry["role"] == role), None)
        if item is not None:
            if str(original) != item["path"] or expected_sha256 is not None and expected_sha256 != item.get("sha256"):
                raise ProjectConflict("The requested native metadata file differs from its frozen role or version.")
            _output(item, resolver) if output else _input(item)
            return Path(item["path"])
        if any(entry["path"] == str(original) for entry in (*selected.inputs, *selected.outputs)):
            raise ProjectConflict("A native metadata witness cannot be reused in a different argument role.")
    return resolve_runtime_output_path(original) if output else resolve_source_path(original, expected_sha256=expected_sha256)
