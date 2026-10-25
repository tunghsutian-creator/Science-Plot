"""The project generation repository used by all native project commands."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import sciplot_core.project_store.commands as commands
import sciplot_core.project_store.projection as projection
import sciplot_core.project_store.publication as publication
import sciplot_core.project_store.state as state
from .errors import ProjectConflict, ProjectRecoveryRequired, ProjectStoreError
from .io import STORE, StoreIO, directory, install, parts, read_file, sha
from .resources import ResourceRoot


class FileProjectStore:
    def __init__(self, project_root: Path, *, locations: Mapping[str, Path | ResourceRoot] | None = None) -> None:
        self.root = Path(project_root).expanduser().resolve(strict=True)
        if locations is None and (self.root / STORE / "local_locations.json").exists():
            # Cold bundles may register only confined, host-created local views.
            with StoreIO(self.root, {}).locked() as io:
                local = io.read("local_locations.json")
            import re
            ids = local.get("ids", []) if local else []
            if any(not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key) for key in ids):
                raise ProjectStoreError("Invalid confined cold-project resource-root IDs.")
            members = local.get("members", {}) if local else {}
            locations = {key: ResourceRoot(self.root / ".sciplot_resources" / key,
                         tuple(members[key]) if members.get(key) is not None else None) for key in ids}
        self.locations = {}
        self.location_members = {}
        for key, supplied in (locations or {}).items():
            capability = supplied if isinstance(supplied, ResourceRoot) else ResourceRoot(supplied)
            self.locations[key] = Path(capability.path).expanduser().resolve(strict=True)
            if capability.members is not None:
                for relative in capability.members:
                    if parts(relative)[0].startswith("@"):
                        raise ProjectStoreError("File capabilities must be relative within one trusted root.")
            self.location_members[key] = capability.members
        roots = [self.root, *self.locations.values()]
        if len(set(roots)) != len(roots):
            raise ProjectStoreError("Trusted resource roots must have distinct identities.")

    @contextmanager
    def _locked(self, *, import_legacy: bool = False, repair: bool = False) -> Iterator[tuple[StoreIO, dict[str, Any]]]:
        with StoreIO(self.root, self.locations, self.location_members).locked() as io:
            current = state.head(io)
            if current is None:
                if not import_legacy:
                    raise ProjectRecoveryRequired("Explicit legacy import is required before project mutation.")
                current = state.import_legacy(io)
            if repair:
                projection.recover(io, current)
            elif projection.pending(io, current):
                raise ProjectRecoveryRequired("A complete generation is committed; explicitly recover its derived files first.")
            yield io, current

    def snapshot(self, *, import_legacy: bool = False) -> dict[str, Any]:
        with self._locked(import_legacy=import_legacy) as (io, current):
            drift = {}
            for name, entry in current["files"].items():
                physical = io.physical(name)
                actual = sha(physical[0]) if physical else None
                if actual != entry["sha256"]:
                    drift[name] = actual
            return {**current, "projection_status": "conflict" if drift else "current", "outside_changes": drift}

    def reserve(self, command_id: str, command_digest: str, *, expected_generation: str | None,
                read_set: Mapping[str, str | None], write_set: Sequence[str],
                metadata: dict[str, Any] | None = None,
                projected_reads: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
        with self._locked(repair=True) as (io, current):
            return commands.public(io, commands.reserve(io, current, command_id, command_digest,
                expected_generation=expected_generation, read_set=read_set, write_set=write_set,
                metadata=metadata, projected_reads=projected_reads))

    def mark_applying(self, command_id: str, command_digest: str) -> dict[str, Any]:
        with self._locked(repair=True) as (io, _current):
            record = state.command(io, command_id, command_digest)
            if record is None:
                raise ProjectStoreError("Reserve this command before native preparation.")
            # Return the admitted applying phase only to this one successful CAS.
            return commands.mark_applying(io, record)

    def stage(self, command_id: str, command_digest: str, *, writes: Mapping[str, bytes | Path | None],
              result: dict[str, Any], review: dict[str, Any],
              artifacts: Mapping[str, bytes | Path] | None = None,
              sources: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
        with self._locked(repair=True) as (io, _current):
            record = state.command(io, command_id, command_digest)
            if record is None:
                raise ProjectStoreError("Reserve this command before freezing a candidate.")
            return commands.public(io, commands.stage(io, record, writes=writes, result=result,
                review=review, artifacts=artifacts, sources=sources), create_views=True)

    def decide(self, command_id: str, command_digest: str, *, decision_id: str, accept: bool) -> dict[str, Any]:
        with self._locked(repair=True) as (io, _current):
            record = state.command(io, command_id, command_digest)
            if record is None:
                raise ProjectStoreError("The frozen candidate does not exist.")
            return commands.public(io, commands.decide(io, record, decision_id, accept))

    def publish(self, command_id: str, command_digest: str, *, writes: Mapping[str, bytes | Path | None],
                result: dict[str, Any], sources: Sequence[dict[str, Any]] | None = None,
                artifacts: Mapping[str, bytes | Path] | None = None) -> dict[str, Any]:
        with self._locked(repair=True) as (io, current):
            record = state.command(io, command_id, command_digest)
            if record is None:
                raise ProjectStoreError("Reserve this command before publication.")
            if record["phase"] == "complete":
                return commands.public(io, record)
            if record["phase"] not in {"reserved", "applying"}:
                raise ProjectStoreError("Resume an accepted command or decide its exact reviewed candidate explicitly.")
            commands.stage(io, record, writes=writes, result=result, review={"execution": "immediate"},
                           artifacts=artifacts, sources=sources)
            commands.decide(io, record, record["decision_id"], True)
            return commands.public(io, publication.publish(io, current, record, frozen=record["draft"]), create_views=True)

    def publish_staged(self, command_id: str, command_digest: str) -> dict[str, Any]:
        with self._locked(repair=True) as (io, current):
            record = state.command(io, command_id, command_digest)
            if record is None or record.get("accepted") is not True:
                raise ProjectStoreError("An exact accepted frozen candidate is required.")
            commands.public(io, record)  # Verify the sealed descriptor before using it.
            return commands.public(io, publication.publish(io, current, record, frozen=record["draft"]), create_views=True)

    def query(self, command_id: str) -> dict[str, Any] | None:
        if not (self.root / STORE / "head.json").exists():
            return None
        with self._locked() as (io, _current):
            record = state.command(io, command_id)
            return commands.public(io, record) if record else None

    def commands(self) -> tuple[dict[str, Any], ...]:
        import os

        with self._locked() as (io, _current):
            try:
                with directory(io.fd, ("commands",)) as parent:
                    names = sorted(name for name in os.listdir(parent) if name.endswith(".json"))
            except FileNotFoundError:
                return ()
            result = []
            for name in names:
                record = io.read("commands/" + name)
                if record is not None:
                    result.append(commands.public(io, record))
            return tuple(result)

    def recover(self) -> dict[str, Any]:
        with self._locked(repair=True) as (io, current):
            unknown = []
            try:
                import os
                with directory(io.fd, ("commands",)) as parent:
                    for name in os.listdir(parent):
                        if name.endswith(".json"):
                            record = io.read("commands/" + name)
                            if record and record["phase"] == "applying":
                                unknown.append(record["command_id"])
                            if record and record.get("draft") is not None:
                                commands.public(io, record, create_views=True)
            except FileNotFoundError:
                pass
            return {"phase": "unknown" if unknown else "complete", "project_id": current["project_id"],
                    "generation": current["generation"], "unknown_commands": sorted(unknown)}

    def read_bytes(self, logical: str, *, generation: str | None = None) -> bytes:
        with self._locked() as (io, current):
            value = state.reachable(io, current, generation) if generation else current
            if value["project_id"] != current["project_id"] or logical not in value["files"]:
                raise ProjectStoreError("The logical resource is not a member of this generation.")
            return io.get(value["files"][logical])

    def logical_path(self, path: Path) -> str:
        candidate = Path(path).expanduser().absolute()
        for key, root in sorted(self.locations.items(), key=lambda item: len(str(item[1])), reverse=True):
            if candidate.is_relative_to(root):
                relative = candidate.relative_to(root).as_posix()
                parts(relative)
                allowed = self.location_members.get(key)
                if allowed is not None and relative not in allowed:
                    raise ProjectStoreError("This file is outside the trusted member capability.")
                return f"@{key}/{relative}"
        if candidate.is_relative_to(self.root):
            relative = candidate.relative_to(self.root).as_posix()
            parts(relative)
            return relative
        raise ProjectStoreError("This path is outside all explicitly trusted resource roots.")

    def projection_path(self, logical: str) -> Path:
        with self._locked() as (io, current):
            expected = current["files"].get(logical)
            physical = io.physical(logical)
            if expected is None or physical is None or sha(physical[0]) != expected["sha256"]:
                raise ProjectConflict("The derived path has unregistered outside bytes or is absent.")
            components = parts(logical)
            if components[0].startswith("@"):
                return self.locations[components[0][1:]] / Path(*components[1:])
            return self.root / Path(*components)

    def resolve_source(self, source_id: str, version: str) -> Path:
        import re

        if not re.fullmatch(r"[0-9a-f]{32}", source_id) or not re.fullmatch(r"[0-9a-f]{64}", version):
            raise ProjectStoreError("Source and version identifiers must match their frozen project identity.")
        with self._locked() as (io, current):
            entry = current["sources"].get(source_id, {}).get(version)
            if entry is None:
                raise ProjectStoreError("The explicit source identity/version is not in this project.")
            name = Path(entry.get("locator") or entry.get("logical") or "source.bin").name
            components = ("sources", source_id, version, name)
            with directory(io.fd, components[:-1], create=True) as parent:
                data = io.get(entry)
                try:
                    install(parent, name, data, mode=0o400, exclusive=True)
                except FileExistsError:
                    if read_file(parent, name)[0] != data:
                        raise ProjectConflict("A source view differs from its immutable source version.") from None
            return self.root / STORE / Path(*components)

    def resolve_locator(self, original: str, *, source_id: str, version: str) -> Path:
        snapshot = self.snapshot()
        entry = snapshot["sources"].get(source_id, {}).get(version)
        if entry is None or entry.get("locator") != original:
            raise ProjectConflict("A locator must match its saved source ID and exact version; names never reconnect.")
        return self.resolve_source(source_id, version)

    def resolve_path(self, original: str | Path, *, expected_sha256: str | None = None,
                     source_id: str | None = None, generation: str | None = None) -> Path:
        import sciplot_core.project_store.locators as locators

        literal = str(original)
        with self._locked() as (io, current):
            value = state.reachable(io, current, generation) if generation else current
            import sciplot_core.project_store.directories as directories
            owned = locators.owned_source_view(io, value, Path(literal), expected_sha256=expected_sha256, source_id=source_id)
            if owned is None:
                owned = directories.owned_view(io, value, Path(literal), expected_sha256=expected_sha256)
            if owned is not None:
                return owned[0]
            logical = locators.logical_for_literal(value, literal)
            if logical is None:
                try:
                    candidate = self.logical_path(Path(literal))
                    logical = candidate if candidate in value["files"] else None
                except ProjectStoreError:
                    pass
            if logical is not None:
                locators.checked_member(io, value, logical, expected_sha256)
                components = parts(logical)
                return (self.locations[components[0][1:]] / Path(*components[1:])
                        if components[0].startswith("@") else self.root / Path(*components))
            closed = directories.resolve(io, value, Path(literal), expected_sha256=expected_sha256)
            if closed is not None:
                return closed
            identity, version, entry = locators.source_entry(io, value, literal,
                expected_sha256=expected_sha256, source_id=source_id)
            local = io.read("local_sources.json") or {"versions": {}}
            if local["versions"].get(identity, {}).get(version) == entry["sha256"]:
                return self.resolve_source(identity, version)
            from .io import read_file
            import os

            source = Path(literal)
            try:
                parent = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    data, _mode = read_file(parent, source.name)
                finally:
                    os.close(parent)
            except OSError as exc:
                raise ProjectConflict("The exact registered original is missing; no same-name reconnection is allowed.") from exc
            if sha(data) != version:
                raise ProjectConflict("The exact original source differs from its registered version.")
            return source

    def literal_path(self, actual: Path, *, generation: str | None = None) -> str:
        import sciplot_core.project_store.locators as locators

        with self._locked() as (io, current):
            value = state.reachable(io, current, generation) if generation else current
            import sciplot_core.project_store.directories as directories
            owned = locators.owned_source_view(io, value, actual)
            if owned is None:
                owned = directories.owned_view(io, value, actual)
            if owned is not None:
                return owned[1]
            try:
                logical = self.logical_path(actual)
            except ProjectStoreError:
                logical = None
            if logical is not None and logical in value["files"]:
                locators.checked_member(io, value, logical, None)
                return locators.original_for_logical(value, logical)
            for identity, versions in value["sources"].items():
                for version, entry in versions.items():
                    name = Path(entry.get("locator") or entry.get("logical") or "source.bin").name
                    if actual == self.root / STORE / "sources" / identity / version / name:
                        from .io import read_file
                        import os

                        parent = os.open(actual.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                        try:
                            observed = read_file(parent, actual.name)[0]
                        finally:
                            os.close(parent)
                        if observed != io.get(entry):
                            raise ProjectConflict("The resolved source view changed.")
                        return str(entry["locator"])
            raise ProjectStoreError("The actual path has no exact preserved locator in this generation.")

    def export_bundle(self, destination: Path) -> Path:
        from .portable import export_bundle

        return export_bundle(self, destination)

    @classmethod
    def import_bundle(cls, bundle: Path, destination: Path) -> FileProjectStore:
        from .portable import import_bundle

        return import_bundle(bundle, destination, factory=lambda root, locations: cls(root, locations=locations))
