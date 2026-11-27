"""Internal Card 20 adapter for one regular .sciplot file.

The ZIP64 envelope is exactly the existing portable Store bundle. A local
session owns its private, disposable Store; the document changes only on
explicit save. Kernel leases coordinate cooperating local writers, not cloud
replicas or an outside process racing the final check and rename.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from tempfile import TemporaryDirectory, mkstemp
from typing import IO, BinaryIO
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from sciplot_core.delivery.install import install_new_delivery
from sciplot_core.foundation.research_destination import require_data_destination
from sciplot_core.foundation.writer_lease import DirectoryWriterLease, WriterLeaseBusy, WriterLeaseChanged
from sciplot_core.project_store.errors import ProjectConflict, ProjectRecoveryRequired, ProjectStoreError
from sciplot_core.project_store.io import parts
from sciplot_core.project_store.repository import FileProjectStore

_HEADER = "bundle.json"


@dataclass(frozen=True)
class ProjectFileSave:
    project_id: str
    generation: str
    sha256: str


class ProjectFileSaveUnconfirmed(ProjectRecoveryRequired):
    """Publication may be visible, but the saved document was not acknowledged."""

    def __init__(self, receipt: ProjectFileSave) -> None:
        self.receipt = receipt
        super().__init__("Project file publication is unconfirmed; check this exact candidate before retrying.")


@dataclass(frozen=True)
class _FileVersion:
    identity: tuple[int, ...]
    sha256: str

    def matches_published(self, candidate: _FileVersion) -> bool:
        # A rename can change ctime; it does not change the inode or file bytes.
        return self.identity[:2] == candidate.identity[:2] and self.sha256 == candidate.sha256


@dataclass(frozen=True)
class _Manifest:
    project_id: str
    generation: str
    members: dict[str, tuple[str, int]]


def _manifest(raw: bytes) -> _Manifest:
    value = json.loads(raw)
    if (not isinstance(value, dict) or value.get("kind") != "sciplot_project_bundle"
            or type(value.get("version")) is not int or value["version"] != 1
            or not isinstance(value.get("project_id"), str) or not isinstance(value.get("generation"), str)
            or not isinstance(value.get("location_ids"), list)
            or not isinstance(value.get("location_members", {}), dict)
            or not isinstance(value.get("members"), dict) or "head.json" not in value["members"]):
        raise ProjectStoreError("Invalid .sciplot bundle manifest.")
    for paths in value.get("location_members", {}).values():
        if paths is not None and (not isinstance(paths, list) or not all(isinstance(p, str) for p in paths)):
            raise ProjectStoreError("Invalid .sciplot resource inventory.")
    members: dict[str, tuple[str, int]] = {}
    for name, entry in value["members"].items():
        parts(name)
        if ("\x00" in name or not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                or type(entry.get("size")) is not int or entry["size"] < 0
                or type(entry.get("mode")) is not int or not 0 <= entry["mode"] <= 0o777):
            raise ProjectStoreError("Invalid .sciplot member inventory.")
        members[f"store/{name}"] = (entry["sha256"], entry["size"])
    return _Manifest(value["project_id"], value["generation"], members)


def _copy_hash(incoming: IO[bytes], output: BinaryIO | None = None) -> str:
    digest = hashlib.sha256()
    while chunk := incoming.read(1024 * 1024):
        digest.update(chunk)
        if output is not None:
            output.write(chunk)
    return digest.hexdigest()


def _read_archive(
    stream: BinaryIO, *, extract: Path | None = None, expected_header: bytes | None = None
) -> _Manifest:
    try:
        with ZipFile(stream) as archive:
            infos = {info.filename: info for info in archive.infolist()}
            if (len(infos) != len(archive.infolist()) or _HEADER not in infos
                    or any(info.orig_filename != info.filename
                           or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)
                           for info in infos.values())):
                raise ProjectStoreError("Invalid or duplicate .sciplot archive members.")
            raw = archive.read(_HEADER)
            if expected_header is not None and raw != expected_header:
                raise ProjectConflict("The .sciplot candidate manifest differs from the exported Store bundle.")
            manifest = _manifest(raw)
            if infos.keys() != manifest.members.keys() | {_HEADER}:
                raise ProjectStoreError("The .sciplot archive does not match its manifest inventory.")
            for name, (sha, size) in manifest.members.items():
                if infos[name].file_size != size:
                    raise ProjectStoreError("A .sciplot member has an incorrect size.")
                with archive.open(infos[name]) as member:
                    if extract is None:
                        actual = _copy_hash(member)
                    else:
                        target = extract / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("xb") as output:
                            actual = _copy_hash(member, output)
                if actual != sha:
                    raise ProjectStoreError("A .sciplot member differs from its manifest hash.")
            if extract is not None:
                (extract / _HEADER).write_bytes(raw)
            return manifest
    except (BadZipFile, UnicodeError, json.JSONDecodeError, NotImplementedError, EOFError, FileExistsError) as exc:
        raise ProjectStoreError("Invalid or incomplete .sciplot archive.") from exc


def _path(path: Path) -> Path:
    value = path.expanduser()
    if value.suffix != ".sciplot":
        raise ProjectStoreError("Expected an ordinary .sciplot project file.")
    return value.parent.resolve(strict=True) / value.name


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def _regular_file(path: str | Path, *, dir_fd: int | None = None) -> Iterator[BinaryIO]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ProjectStoreError("A .sciplot document must be an ordinary file.")
        yield stream


def _fingerprint(stream: BinaryIO) -> _FileVersion:
    info = _identity(os.fstat(stream.fileno()))
    stream.seek(0)
    sha = _copy_hash(stream)
    if info != _identity(os.fstat(stream.fileno())):
        raise ProjectConflict("The .sciplot file changed while it was being read.")
    stream.seek(0)
    return _FileVersion(info, sha)


@contextmanager
def _locked_archive_file(fd: int, name: str) -> Iterator[BinaryIO]:
    with _regular_file(name, dir_fd=fd) as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WriterLeaseBusy("Another writer owns this .sciplot file's save lease.") from exc
        yield stream


def _current(stream: BinaryIO, fd: int, name: str) -> _FileVersion:
    version = _fingerprint(stream)
    if version.identity != _identity(os.stat(name, dir_fd=fd, follow_symlinks=False)):
        raise ProjectConflict("The .sciplot path changed while it was being checked.")
    return version


@dataclass(frozen=True)
class _Candidate:
    receipt: ProjectFileSave
    version: _FileVersion


@contextmanager
def _candidate(
    store: FileProjectStore, path: Path, generation: str, *, project_id: str | None = None
) -> Iterator[tuple[Path, _Candidate]]:
    with TemporaryDirectory(prefix="sciplot-capture-") as temporary:
        bundle = store.export_bundle(Path(temporary) / "bundle")
        raw = (bundle / _HEADER).read_bytes()
        manifest = _manifest(raw)
        if manifest.generation != generation or project_id not in (None, manifest.project_id):
            raise ProjectConflict("The captured Store does not match the accepted project and generation.")
        fd, name = mkstemp(prefix=".sciplot-save-", dir=path.parent)
        stage = Path(name)
        try:
            with os.fdopen(fd, "w+b") as output:
                with ZipFile(output, "w", compression=ZIP_DEFLATED, allowZip64=True) as archive:
                    archive.writestr(_HEADER, raw)
                    for name in sorted(manifest.members):
                        archive.write(bundle / name, name)
                output.flush()
                _read_archive(output, expected_header=raw)
                os.fsync(output.fileno())
                version = _fingerprint(output)
                yield stage, _Candidate(ProjectFileSave(manifest.project_id, generation, version.sha256), version)
        finally:
            stage.unlink(missing_ok=True)


def _publish(path: Path, stage: Path, candidate: _Candidate, baseline: _FileVersion | None) -> _FileVersion:
    # Share the parent only with new archive writers. An older version using
    # the exclusive parent flock still cannot enter this publication window.
    with closing(DirectoryWriterLease(path.parent, shared=True)) as lease, ExitStack() as held:
        fd = lease.fd
        if baseline is None:
            try:
                os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(path)
        else:
            try:
                opened = held.enter_context(_locked_archive_file(fd, path.name))
                existing = _current(opened, fd, path.name)
            except (OSError, ProjectStoreError) as exc:
                raise ProjectConflict("The .sciplot save target changed since open.") from exc
            if existing != baseline:
                raise ProjectConflict("The .sciplot save target changed since open.")
        # Keep the old file locked and transfer another locked inode to the
        # target at rename. Neither side of atomic replace admits a second save.
        incoming = held.enter_context(_locked_archive_file(fd, stage.name))
        lease.verify()
        if (_identity(os.fstat(incoming.fileno())) != candidate.version.identity
                or _identity(os.stat(stage.name, dir_fd=fd, follow_symlinks=False)) != candidate.version.identity):
            raise ProjectConflict("The staged .sciplot candidate changed before save.")
        if baseline is None:
            # Existing portable path-based no-replace primitive. The verified
            # lease coordinates SciPlot, not an outside rename of its parent.
            install_new_delivery(stage, path)
        else:
            os.replace(stage.name, path.name, src_dir_fd=fd, dst_dir_fd=fd)
        try:
            lease.verify()
            info = _identity(os.stat(path.name, dir_fd=fd, follow_symlinks=False))
            if info[:-1] != candidate.version.identity[:-1]:
                raise ProjectConflict("The published .sciplot file differs from its candidate.")
            os.fsync(fd)
        except (OSError, ProjectStoreError, WriterLeaseChanged) as exc:
            raise ProjectFileSaveUnconfirmed(candidate.receipt) from exc
        return _FileVersion(info, candidate.version.sha256)


def create_project_file(path: Path, store: FileProjectStore, *, expected_generation: str) -> ProjectFileSave:
    """Publish a new archive without replacing a file already at the target."""
    target = _path(path)
    require_data_destination(target)
    with _candidate(store, target, expected_generation) as (stage, candidate):
        _publish(target, stage, candidate, None)
        return candidate.receipt


class ProjectFileSession:
    """A private Store and its opening document baseline, valid until close."""

    def __init__(self, path: Path, store: FileProjectStore, manifest: _Manifest, version: _FileVersion) -> None:
        self.path = path
        self.store = store
        self.project_id = manifest.project_id
        self.opened_generation = manifest.generation
        self._version = version
        self._pending: _Candidate | None = None
        self._closed = False

    def matches_path(self, path: Path) -> bool:
        """Cheap view-cache check only. Saves still verify the exact bytes."""
        try:
            return not self._closed and self._version.identity == _identity(
                path.expanduser().stat(follow_symlinks=False))
        except FileNotFoundError:
            return False

    def save(self, *, expected_generation: str) -> ProjectFileSave:
        """Persist this exact accepted Store generation; never replay its edits."""
        if self._closed:
            raise ProjectStoreError("This .sciplot session is closed.")
        require_data_destination(self.path)
        pending = self._pending
        if pending is not None:
            if expected_generation != pending.receipt.generation:
                raise ProjectFileSaveUnconfirmed(pending.receipt)
            try:
                with closing(DirectoryWriterLease(self.path.parent, shared=True)) as lease:
                    with _locked_archive_file(lease.fd, self.path.name) as opened:
                        current = _current(opened, lease.fd, self.path.name)
                        if not current.matches_published(pending.version):
                            raise ProjectConflict("The unconfirmed .sciplot candidate is no longer at the save target.")
                        lease.verify()
                        os.fsync(lease.fd)
            except FileNotFoundError as exc:
                raise ProjectConflict("The unconfirmed .sciplot candidate is no longer at the save target.") from exc
            except (OSError, WriterLeaseChanged) as exc:
                raise ProjectFileSaveUnconfirmed(pending.receipt) from exc
            self._version = current
            self._pending = None
            return pending.receipt
        baseline = self._version
        with _candidate(self.store, self.path, expected_generation, project_id=self.project_id) as (stage, candidate):
            try:
                self._version = _publish(self.path, stage, candidate, baseline)
            except ProjectFileSaveUnconfirmed:
                self._pending = candidate
                raise
            return candidate.receipt


@contextmanager
def open_project_file(path: Path, *, workspace_parent: Path | None = None) -> Iterator[ProjectFileSession]:
    """Open a verified independent working Store from only the document bytes."""
    target = _path(path)
    with TemporaryDirectory(prefix="sciplot-open-", dir=workspace_parent) as temporary:
        root = Path(temporary)
        with TemporaryDirectory(prefix="extract-", dir=root) as stage:
            with _regular_file(target) as stream:
                version = _fingerprint(stream)
                manifest = _read_archive(stream, extract=Path(stage))
                if version.identity != _identity(os.fstat(stream.fileno())):
                    raise ProjectConflict("The .sciplot file changed during extraction.")
            store = FileProjectStore.import_bundle(Path(stage), root / "project")
        session = ProjectFileSession(target, store, manifest, version)
        try:
            yield session
        finally:
            session._closed = True
