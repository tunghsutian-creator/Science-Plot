"""The project generation repository used by all native project commands."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import commands, projection, publication, state
from .errors import ProjectConflict, ProjectRecoveryRequired, ProjectStoreError
from .io import STORE, StoreIO, directory, install, parts, read_file, sha


class FileProjectStore:
    def __init__(self, project_root: Path, *, locations: Mapping[str, Path] | None = None) -> None:
        self.root = Path(project_root).expanduser().resolve(strict=True)
        if locations is None and (self.root / STORE / "local_locations.json").exists():
            # Cold bundles may register only confined, host-created local views.
            with StoreIO(self.root, {}).locked() as io:
                local = io.read("local_locations.json")
            import re
            ids = local.get("ids", []) if local else []
            if any(not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key) for key in ids):
                raise ProjectStoreError("Invalid confined cold-project resource-root IDs.")
            locations = {key: self.root / ".sciplot_resources" / key for key in ids}
        self.locations = {key: Path(path).expanduser().resolve(strict=True) for key, path in (locations or {}).items()}
        roots = [self.root, *self.locations.values()]
        if len(set(roots)) != len(roots):
            raise ProjectStoreError("Trusted resource roots must have distinct identities.")

    @contextmanager
    def _locked(self, *, import_legacy: bool = False) -> Iterator[tuple[StoreIO, dict[str, Any]]]:
        with StoreIO(self.root, self.locations).locked() as io:
            current = state.head(io)
            if current is None:
                if not import_legacy:
                    raise ProjectRecoveryRequired("Explicit legacy import is required before project mutation.")
                current = state.import_legacy(io)
            projection.recover(io, current)
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
        with self._locked() as (io, current):
            return commands.public(io, commands.reserve(io, current, command_id, command_digest,
                expected_generation=expected_generation, read_set=read_set, write_set=write_set,
                metadata=metadata, projected_reads=projected_reads))

    def mark_applying(self, command_id: str, command_digest: str) -> dict[str, Any]:
        with self._locked() as (io, _current):
            record = state.command(io, command_id, command_digest)
            if record is None:
                raise ProjectStoreError("Reserve this command before native preparation.")
            # Return the admitted applying phase only to this one successful CAS.
            return commands.mark_applying(io, record)

    def stage(self, command_id: str, command_digest: str, *, writes: Mapping[str, bytes | Path | None],
              result: dict[str, Any], review: dict[str, Any],
              artifacts: Mapping[str, bytes | Path] | None = None,
              sources: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
        with self._locked() as (io, _current):
            record = state.command(io, command_id, command_digest)
            if record is None:
                raise ProjectStoreError("Reserve this command before freezing a candidate.")
            return commands.public(io, commands.stage(io, record, writes=writes, result=result,
                review=review, artifacts=artifacts, sources=sources))

    def decide(self, command_id: str, command_digest: str, *, decision_id: str, accept: bool) -> dict[str, Any]:
        with self._locked() as (io, _current):
            record = state.command(io, command_id, command_digest)
            if record is None:
                raise ProjectStoreError("The frozen candidate does not exist.")
            return commands.public(io, commands.decide(io, record, decision_id, accept))

    def publish(self, command_id: str, command_digest: str, *, writes: Mapping[str, bytes | Path | None],
                result: dict[str, Any], sources: Sequence[dict[str, Any]] | None = None,
                artifacts: Mapping[str, bytes | Path] | None = None) -> dict[str, Any]:
        with self._locked() as (io, current):
            record = state.command(io, command_id, command_digest)
            if record is None:
                raise ProjectStoreError("Reserve this command before publication.")
            if record["phase"] == "complete":
                return commands.public(io, record)
            frozen = {"writes": state.import_writes(io, writes), "result": result,
                      "sources": commands.capture_sources(io, sources), "review": {},
                      "artifacts": state.import_writes(io, artifacts or {})}
            commands.seal(io, record, frozen)
            return commands.public(io, publication.publish(io, current, record, frozen=frozen))

    def publish_staged(self, command_id: str, command_digest: str) -> dict[str, Any]:
        with self._locked() as (io, current):
            record = state.command(io, command_id, command_digest)
            if record is None or record.get("accepted") is not True:
                raise ProjectStoreError("An exact accepted frozen candidate is required.")
            commands.public(io, record)  # Verify the sealed descriptor before using it.
            return commands.public(io, publication.publish(io, current, record, frozen=record["draft"]))

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
        with self._locked() as (io, current):
            unknown = []
            try:
                import os
                with directory(io.fd, ("commands",)) as parent:
                    for name in os.listdir(parent):
                        if name.endswith(".json"):
                            record = io.read("commands/" + name)
                            if record and record["phase"] == "applying":
                                unknown.append(record["command_id"])
            except FileNotFoundError:
                pass
            return {"phase": "unknown" if unknown else "complete", "project_id": current["project_id"],
                    "generation": current["generation"], "unknown_commands": sorted(unknown)}

    def read_bytes(self, logical: str, *, generation: str | None = None) -> bytes:
        with self._locked() as (io, current):
            value = state.generation(io, generation) if generation else current
            if value["project_id"] != current["project_id"] or logical not in value["files"]:
                raise ProjectStoreError("The logical resource is not a member of this generation.")
            return io.get(value["files"][logical])

    def logical_path(self, path: Path) -> str:
        candidate = Path(path).expanduser().absolute()
        for key, root in sorted(self.locations.items(), key=lambda item: len(str(item[1])), reverse=True):
            if candidate.is_relative_to(root):
                relative = candidate.relative_to(root).as_posix()
                parts(relative)
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

    def export_bundle(self, destination: Path) -> Path:
        from .portable import export_bundle

        return export_bundle(self, destination)

    @classmethod
    def import_bundle(cls, bundle: Path, destination: Path) -> FileProjectStore:
        from .portable import import_bundle

        return import_bundle(bundle, destination)
