"""Private host-owned registration file; requests cannot create or widen grants."""
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.writer_lease import exclusive_directory_lease
from sciplot_core.plot_document.errors import DocumentError
from .models import EXECUTE_TRANSFORM, SourceScope, denied


class HostRegistry:
    def __init__(self, path: Path):
        self.path = path.absolute()

    @classmethod
    def default(cls) -> "HostRegistry":
        # No project/request/environment-supplied registry locator or allow flag.
        return cls(Path.home() / ".sciplot" / "host-executors.json")

    def _parent(self, *, create: bool = False) -> None:
        if create:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.parent.resolve() != self.path.parent:
            denied("host_registry_untrusted", "Host grant directories cannot use a path alias.")
        info = self.path.parent.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            denied("host_registry_untrusted", "The host registry directory must be private and owned by the host user.")

    def _read(self) -> list[dict[str, Any]]:
        try:
            return self._read_checked()
        except DocumentError:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            denied("host_registry_invalid", "The host registry cannot be read as an explicit supported grant configuration.")

    def _read_checked(self) -> list[dict[str, Any]]:
        if not self.path.exists() and not self.path.is_symlink():
            return []
        self._parent()
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_size > 1024 * 1024):
                denied("host_registry_untrusted", "Host grants require one bounded private user-owned file.")
            value = json.load(stream)
        if (not isinstance(value, dict) or set(value) != {"kind", "version", "grants"}
                or value["kind"] != "sciplot_host_executor_grants" or value["version"] != 1
                or not isinstance(value["grants"], list)):
            denied("host_registry_invalid", "The host grant registry is not a supported configuration.")
        seen = set()
        for grant in value["grants"]:
            if (not isinstance(grant, dict) or set(grant) != {"id", "registration", "actions", "sources"}
                    or not isinstance(grant["actions"], list)
                    or len(grant["actions"]) != len(set(grant["actions"]))
                    or any(action != EXECUTE_TRANSFORM for action in grant["actions"]) or not grant["sources"]):
                denied("host_registry_invalid", "Host grants need explicit supported actions and source scopes.")
            key = (grant["id"], grant["registration"]["identity"]["content_hash"])
            if key in seen:
                denied("host_registry_invalid", "Host grants have duplicate identities.")
            seen.add(key)
            for item in grant["sources"]:
                if set(item) != {"source_id", "path", "sha256"}:
                    denied("host_registry_invalid", "Source grants cannot contain unknown permissions.")
                SourceScope.of(item)
        return deepcopy(value["grants"])

    def registrations(self) -> list[dict[str, Any]]:
        return self._read()

    def grant(self, identifier: str, registration: dict[str, Any], sources: list[SourceScope], *, action: str) -> None:
        """Explicit trusted host administration; never called by a plot request."""
        from sciplot_core.plot_transforms.external_descriptor import ExternalExecutor

        executor = ExternalExecutor.from_dict(registration)
        if executor.descriptor(identifier) != registration["identity"] or action != EXECUTE_TRANSFORM or not sources:
            denied("host_grant_invalid", "Grant one exact executor, supported action and nonempty source scope.")
        for source in sources:
            if file_sha256(resolve_source_path(source.path, expected_sha256=source.sha256, source_id=source.source_id)) != source.sha256:
                denied("host_executor_source_denied", "The explicitly selected host source changed before granting.")
        self._parent(create=True)
        with exclusive_directory_lease(self.path.parent):
            grants = self._read()
            grants = [g for g in grants if (g["id"], g["registration"]["identity"]) != (identifier, registration["identity"])]
            grants.append({"id": identifier, "registration": deepcopy(registration), "actions": [action],
                           "sources": [source.to_dict() for source in sources]})
            atomic_write_json(self.path, {"kind": "sciplot_host_executor_grants", "version": 1, "grants": grants})

    def revoke(self, identifier: str) -> None:
        self._parent(create=True)
        with exclusive_directory_lease(self.path.parent):
            grants = [g for g in self._read() if g["id"] != identifier]
            atomic_write_json(self.path, {"kind": "sciplot_host_executor_grants", "version": 1, "grants": grants})

    def require(self, identifier: str, identity: dict[str, Any], sources: tuple[SourceScope, ...]) -> dict[str, Any]:
        matches = [g for g in self._read() if g["id"] == identifier and g["registration"]["identity"] == identity]
        if len(matches) != 1:
            denied("host_executor_ungranted", "This scientific identity has no explicit host grant. Use the trusted local host-grants command.")
        grant = matches[0]
        if EXECUTE_TRANSFORM not in grant["actions"]:
            denied("host_executor_action_denied", "The host has not granted transform.execute.")
        allowed = {SourceScope.of(item) for item in grant["sources"]}
        if not sources or any(source not in allowed for source in sources):
            denied("host_executor_source_denied", "This executor is not host-granted for every actual input source.")
        for source in sources:
            if file_sha256(resolve_source_path(source.path, expected_sha256=source.sha256, source_id=source.source_id)) != source.sha256:
                denied("host_executor_source_denied", "A granted source's current bytes do not match its explicit scope.")
        return deepcopy(grant["registration"])
