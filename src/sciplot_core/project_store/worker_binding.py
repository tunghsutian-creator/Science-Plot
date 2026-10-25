"""Host-created private per-command project locator binding for native workers."""
from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from sciplot_core.foundation.source_locations import selected_source_resolver, source_location_scope
from .errors import ProjectConflict, ProjectStoreError
from .io import digest
from .incoming_sources import expectation_payload, source_expectation_scope, without_source_expectations
from .candidate_resources import validate_resources_binding
from .native_artifacts import artifact_payload, bound_native_artifacts, native_artifact_binding
from .repository import FileProjectStore
from .resources import ResourceRoot
from .runtime import ProjectSourceResolver


@contextmanager
def native_runtime_binding(argv: list[str]) -> Iterator[dict[str, str] | None]:
    """Only selected trusted host state creates a locator; no wire/root discovery."""
    selected = selected_source_resolver()
    if selected is None:
        native_artifact_binding(argv, None)
        yield None
        return
    if not isinstance(selected, ProjectSourceResolver):
        raise ProjectStoreError("This scientific locator has no trusted native-worker binding.")
    project = selected.binding()
    artifacts = native_artifact_binding(argv, selected)
    if artifacts is not None:
        project["native_artifacts"] = artifacts
    value = {"project": project, "argv_sha256": digest(argv), "parent_pid": os.getpid()}
    data = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    with tempfile.TemporaryDirectory(prefix="sciplot-project-runtime-") as temporary:
        root = Path(temporary).resolve(strict=True)
        root.chmod(0o700)
        path = root / "binding.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        yield {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def validate_binding_reference(value: Any) -> None:
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"}
            or not isinstance(value["path"], str) or not Path(value["path"]).is_absolute()
            or len(value["path"]) > 8192 or not isinstance(value["sha256"], str)
            or len(value["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in value["sha256"])):
        raise ProjectStoreError("Invalid closed native project locator reference.")


def _read_binding(reference: dict[str, str], argv: list[str]) -> dict[str, Any]:
    validate_binding_reference(reference)
    path = Path(reference["path"])
    parent = path.parent.stat()
    if (path.parent.resolve() != path.parent or parent.st_uid != os.geteuid()
            or not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o077):
        raise ProjectStoreError("A native locator requires a private host-owned directory.")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
                or info.st_size > 65536):
            raise ProjectStoreError("A native locator requires a bounded private host-owned file.")
        data = stream.read(65537)
    if hashlib.sha256(data).hexdigest() != reference["sha256"]:
        raise ProjectConflict("Native project locator bytes changed after host binding.")
    value = json.loads(data)
    if (not isinstance(value, dict) or set(value) != {"project", "argv_sha256", "parent_pid"}
            or value["argv_sha256"] != digest(argv) or value["parent_pid"] != os.getppid()):
        raise ProjectConflict("The native project locator belongs to a different command or host process.")
    project = value["project"]
    if not isinstance(project, dict):
        raise ProjectStoreError("Unsupported closed native project locator.")
    fields = {"kind", "version", "root", "project_id", "generation", "generation_sha256", "locations"}
    if "source_expectations" in project:
        fields.add("source_expectations")
        expectation_payload(project["source_expectations"])
    if "native_artifacts" in project:
        fields.add("native_artifacts")
        artifact_payload(project["native_artifacts"])
    if project.get("kind") == "sciplot_project_candidate_runtime":
        fields.add("candidate")
        candidate = project.get("candidate")
        candidate_fields = {"root", "device", "inode"}
        if isinstance(candidate, dict) and "resources" in candidate:
            candidate_fields.add("resources")
            validate_resources_binding(candidate["resources"])
        if (not isinstance(candidate, dict) or set(candidate) != candidate_fields
                or not isinstance(candidate["root"], str) or not Path(candidate["root"]).is_absolute()
                or any(type(candidate[key]) is not int or candidate[key] < 0 for key in ("device", "inode"))):
            raise ProjectStoreError("Invalid closed private candidate locator.")
    elif project.get("kind") != "sciplot_project_runtime":
        raise ProjectStoreError("Unsupported closed native project locator.")
    if set(project) != fields or project["version"] != 1 or not isinstance(project["locations"], dict):
        raise ProjectStoreError("Unsupported closed native project locator.")
    return project


@contextmanager
def worker_project_runtime(reference: dict[str, str] | None, argv: list[str]) -> Iterator[None]:
    with without_source_expectations(), bound_native_artifacts(None, argv, None):
        with _worker_project_runtime(reference, argv):
            yield


@contextmanager
def _worker_project_runtime(reference: dict[str, str] | None, argv: list[str]) -> Iterator[None]:
    if reference is None:
        # Even pooled requests without a project cannot inherit the previous one.
        with source_location_scope(None):
            yield
        return
    value = _read_binding(reference, argv)
    locations = {}
    for key, item in value["locations"].items():
        if (not isinstance(item, dict) or set(item) != {"path", "members"}
                or not isinstance(item["path"], str) or not Path(item["path"]).is_absolute()
                or item["members"] is not None and (not isinstance(item["members"], list)
                    or not all(isinstance(name, str) for name in item["members"]))):
            raise ProjectStoreError("Invalid trusted native resource-root capability.")
        locations[key] = ResourceRoot(Path(item["path"]), tuple(item["members"]) if item["members"] is not None else None)
    if not isinstance(value["root"], str) or not Path(value["root"]).is_absolute():
        raise ProjectStoreError("A native project locator needs its explicit physical root.")
    store = FileProjectStore(Path(value["root"]), locations=locations)
    resolver: ProjectSourceResolver
    if value["kind"] == "sciplot_project_candidate_runtime":
        from .candidate_runtime import ProjectCandidateResolver

        candidate = value["candidate"]
        resources = candidate.get("resources")
        resolver = ProjectCandidateResolver(store, Path(candidate["root"]), value["generation"],
            bound_identity={key: candidate[key] for key in ("device", "inode")},
            resources_root=Path(resources["root"]) if resources is not None else None,
            bound_resources=resources)
    else:
        resolver = ProjectSourceResolver(store, value["generation"])
    if (resolver.snapshot["project_id"] != value["project_id"]
            or digest(resolver.snapshot) != value["generation_sha256"]):
        raise ProjectConflict("The native locator differs from the selected project generation.")
    with bound_native_artifacts(value.get("native_artifacts"), argv, resolver):
        if "source_expectations" in value:
            mode, sources = expectation_payload(value["source_expectations"])
            with source_expectation_scope(resolver.snapshot, mode, sources), source_location_scope(resolver):
                yield
        else:
            with source_location_scope(resolver):
                yield
