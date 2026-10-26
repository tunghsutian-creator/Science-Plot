"""The project generation repository used by all native project commands."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sciplot_core.project_commands.resources import PreparedFile

import sciplot_core.project_store.commands as commands
import sciplot_core.project_store.projection as projection
import sciplot_core.project_store.publication as publication
import sciplot_core.project_store.state as state
import sciplot_core.project_store.native_work as native_work
from .errors import ProjectConflict, ProjectRecoveryRequired, ProjectStoreError
from .io import STORE, StoreIO, directory, install, owned_io, parts, read_file, sha
from .resources import ResourceRoot


class FileProjectStore:
    def __init__(self, project_root: Path, *, locations: Mapping[str, Path | ResourceRoot] | None = None,
                 namespace_backups: Mapping[str, Path] | None = None) -> None:
        self.root = Path(project_root).expanduser().resolve(strict=True)
        self.namespace_backups = {key: Path(path).expanduser().absolute() for key, path in (namespace_backups or {}).items()}
        if any(path.resolve(strict=True) != path for path in self.namespace_backups.values()):
            raise ProjectStoreError("A namespace backup capability cannot follow symbolic aliases.")
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
        for key, path in self.locations.items():
            if path.is_relative_to(self.root) and not path.is_relative_to(self.root / ".sciplot_resources"):
                raise ProjectStoreError("An internal resource uses project-relative members instead of a second physical root alias.")
            if self.root.is_relative_to(path) and self.location_members[key] is None:
                raise ProjectStoreError("An ancestor resource requires a finite explicit file capability.")
            for other_key, other in self.locations.items():
                if key != other_key and path.is_relative_to(other) and self.location_members[other_key] is None:
                    raise ProjectStoreError("Overlapping whole-directory resource roots cannot have two authorities.")

    @contextmanager
    def _locked(self, *, import_legacy: bool = False, repair: bool = False,
                allow_pending: bool = False) -> Iterator[tuple[StoreIO, dict[str, Any]]]:
        with self._checked_locked(import_legacy=import_legacy, repair=repair, allow_pending=allow_pending) as (io, current, _checked):
            yield io, current

    @contextmanager
    def _checked_locked(self, *, import_legacy: bool = False, repair: bool = False,
                        allow_pending: bool = False) -> Iterator[tuple[StoreIO, dict[str, Any], state.CheckedHead]]:
        from .namespace_transfers import augment_controls

        active = owned_io(self.root)
        if active is not None and active.locations == self.locations:
            active_head = state.head(active)
            if active_head is not None:
                augment_controls(active, active_head, self.location_members)
        with StoreIO(self.root, self.locations, self.location_members, self.namespace_backups).locked() as io:
            checked = state.checked_head(io)
            if checked is None:
                if not import_legacy:
                    raise ProjectRecoveryRequired("Explicit legacy import is required before project mutation.")
                state.import_legacy(io)
                checked = state.checked_head(io)
            assert checked is not None
            try:
                current = checked.current
                augment_controls(io, current, self.location_members)
                if repair:
                    epoch = io.validation_epoch
                    projection.recover(io, current, checked=checked)
                    if io.validation_epoch != epoch:
                        checked.close()
                        refreshed = state.checked_head(io)
                        if refreshed is None:
                            raise ProjectRecoveryRequired("Recovery lost its committed head; inspect the project before continuing.")
                        checked = refreshed
                        current = checked.current
                elif not allow_pending and projection.pending(io, current):
                    raise ProjectRecoveryRequired("A complete generation is committed; explicitly recover its derived files first.")
                yield io, current, checked
            finally:
                checked.close()

    def snapshot(self, *, import_legacy: bool = False) -> dict[str, Any]:
        with self._locked(import_legacy=import_legacy) as (io, current):
            from .root_bindings import require

            require(io, current)
            drift: dict[str, str | None] = {}
            metadata_drift: dict[str, str] = {}
            for name, entry in current["files"].items():
                try:
                    physical = io.physical(name, owned=name not in current.get("input_resources", [])
                        and name not in current.get("history_resources", []))
                except ProjectConflict as exc:
                    drift[name] = None
                    metadata_drift[name] = str(exc)
                    continue
                actual = sha(physical[0]) if physical else None
                if actual != entry["sha256"] or physical is not None and physical[1] != entry["mode"]:
                    drift[name] = actual
            return {**current, "projection_status": "conflict" if drift else "current",
                    "outside_changes": drift, "outside_metadata": metadata_drift}

    def capture_source_observation(self, resource: str, *, source_id: str, before_sha256: str) -> dict[str, Any]:
        from .source_observations import capture

        with self._locked(allow_pending=True) as (io, current):
            return capture(io, current, resource, source_id=source_id, before_sha256=before_sha256)

    def capture_namespace(self, prefix: str) -> dict[str, Any]:
        from .namespace_io import capture

        with self._locked(allow_pending=True) as (io, current):
            return capture(io, current, prefix)

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

    def stage(self, command_id: str, command_digest: str, *, writes: Mapping[str, bytes | Path | PreparedFile | None],
              result: dict[str, Any], review: dict[str, Any],
              artifacts: Mapping[str, bytes | Path | PreparedFile] | None = None,
              sources: Sequence[dict[str, Any]] | None = None,
              input_reads: Sequence[dict[str, str]] = (),
              expected_metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with self._locked(repair=True) as (io, _current):
            record = state.command(io, command_id, command_digest)
            if record is None:
                raise ProjectStoreError("Reserve this command before freezing a candidate.")
            return commands.public(io, commands.stage(io, record, writes=writes, result=result,
                review=review, artifacts=artifacts, sources=sources, input_reads=input_reads,
                expected_metadata=expected_metadata), create_views=True)

    def decide(self, command_id: str, command_digest: str, *, decision_id: str, accept: bool) -> dict[str, Any]:
        with self._locked(allow_pending=True) as (io, _current):
            record = state.command(io, command_id, command_digest)
            if record is None:
                raise ProjectStoreError("The frozen candidate does not exist.")
            return commands.public(io, commands.decide(io, record, decision_id, accept))

    def publish(self, command_id: str, command_digest: str, *, writes: Mapping[str, bytes | Path | PreparedFile | None],
                result: dict[str, Any], sources: Sequence[dict[str, Any]] | None = None,
                artifacts: Mapping[str, bytes | Path | PreparedFile] | None = None,
                input_reads: Sequence[dict[str, str]] = (),
                expected_metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with self._locked(repair=True) as (io, current):
            record = state.command(io, command_id, command_digest)
            if record is None:
                raise ProjectStoreError("Reserve this command before publication.")
            from .input_reads import require_metadata

            require_metadata(record, expected_metadata)
            if record["phase"] == "complete":
                return commands.public(io, record)
            if record["phase"] not in {"reserved", "applying"}:
                raise ProjectStoreError("Resume an accepted command or decide its exact reviewed candidate explicitly.")
            commands.stage(io, record, writes=writes, result=result, review={"execution": "immediate"},
                           artifacts=artifacts, sources=sources, input_reads=input_reads,
                           expected_metadata=expected_metadata)
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
        with self._locked(allow_pending=True) as (io, current):
            record = state.command(io, command_id)
            return commands.public(io, record, projection_pending=projection.pending(io, current)) if record else None

    def claim_native_workspace(self, command_id: str, command_digest: str, adapter: str) -> Path:
        with self._locked(allow_pending=True) as (io, _current):
            record = state.command(io, command_id, command_digest)
            if record is None:
                raise ProjectStoreError("An admitted exact command must own native execution evidence.")
            return native_work.claim(io, record, adapter)

    def append_native_failure(self, command_id: str, command_digest: str, *, original_error: str,
                              renderer_dispatch_entered: bool, owned_invocation_closed: bool) -> dict[str, Any]:
        with self._locked(allow_pending=True) as (io, _current):
            record = state.command(io, command_id, command_digest)
            if record is None:
                raise ProjectStoreError("No admitted command owns this native failure evidence.")
            return commands.public(io, native_work.append_failure(io, record, original_error=original_error,
                renderer_dispatch_entered=renderer_dispatch_entered, owned_invocation_closed=owned_invocation_closed))

    def commands(self) -> tuple[dict[str, Any], ...]:
        with self._checked_locked(allow_pending=True) as (io, current, checked):
            records = state.read_commands(io, expected=current["commands"])
            pending = projection.pending(io, current)
            return tuple(commands.public(io, record, projection_pending=pending, checked=checked) for record in records)

    def recover(self) -> dict[str, Any]:
        with self._checked_locked(repair=True) as (io, current, checked):
            unknown = []
            for record in state.read_commands(io, expected=current["commands"]):
                if record["phase"] == "applying":
                    unknown.append(record["command_id"])
                if record.get("draft") is not None:
                    commands.public(io, record, create_views=True, checked=checked)
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
        roots = {"": self.root, **self.locations}
        for key, root in sorted(roots.items(), key=lambda item: len(str(item[1])), reverse=True):
            if candidate.is_relative_to(root):
                relative = candidate.relative_to(root).as_posix()
                parts(relative)
                allowed = self.location_members.get(key)
                if allowed is not None and relative not in allowed:
                    continue
                if not key and relative.split("/", 1)[0] == ".sciplot_resources":
                    continue
                return f"@{key}/{relative}" if key else relative
        raise ProjectStoreError("This path is outside all explicitly trusted resource roots.")

    def projection_path(self, logical: str) -> Path:
        with self._locked() as (io, current):
            expected = current["files"].get(logical)
            physical = io.physical(logical)
            if (expected is None or physical is None or sha(physical[0]) != expected["sha256"]
                    or physical[1] != expected["mode"]):
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

    def _prepared_path(self, command_id: str, command_digest: str, *, decision_id: str,
                       locator: str, expected: str, source_id: str | None, tree: bool) -> Path | None:
        from .prepared_inputs import input_path, tree_path

        with self._locked(allow_pending=True) as (io, current):
            record = state.command(io, command_id, command_digest)
            if record is None or record.get("decision_id") != decision_id:
                raise ProjectConflict("Prepared inputs require their exact command and sealed decision.")
            if tree:
                return tree_path(io, current, record, locator=locator, tree_sha256=expected)
            return input_path(io, current, record, locator=locator, expected_sha256=expected, source_id=source_id)

    def prepared_input_path(self, command_id: str, command_digest: str, *, decision_id: str,
                            locator: str, expected_sha256: str, source_id: str | None = None) -> Path | None:
        return self._prepared_path(command_id, command_digest, decision_id=decision_id, locator=locator,
                                   expected=expected_sha256, source_id=source_id, tree=False)

    def prepared_tree_path(self, command_id: str, command_digest: str, *, decision_id: str,
                           locator: str, tree_sha256: str) -> Path | None:
        return self._prepared_path(command_id, command_digest, decision_id=decision_id, locator=locator,
                                   expected=tree_sha256, source_id=None, tree=True)

    def resolve_path(self, original: str | Path, *, expected_sha256: str | None = None,
                     source_id: str | None = None, generation: str | None = None) -> Path:
        from .paths import resolve_path

        return resolve_path(self, original, expected_sha256=expected_sha256, source_id=source_id, generation=generation)

    def literal_path(self, actual: Path, *, generation: str | None = None) -> str:
        from .paths import literal_path

        return literal_path(self, actual, generation=generation)

    def export_bundle(self, destination: Path) -> Path:
        from .portable import export_bundle

        return export_bundle(self, destination)

    @classmethod
    def import_bundle(cls, bundle: Path, destination: Path) -> FileProjectStore:
        from .portable import import_bundle

        return import_bundle(bundle, destination, factory=lambda root, locations: cls(root, locations=locations))
