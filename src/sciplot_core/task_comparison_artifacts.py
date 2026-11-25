"""One sealed private review record and compiled evidence per Managed alternative."""

from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.writer_lease import exclusive_directory_lease
from sciplot_core.task_contract import TaskControlError


def _file(folder: Path, name: str, fd: int, *, collect: bool = False) -> tuple[str, bytes]:
    # Read only direct regular owned children with an anchored descriptor.
    if Path(name).name != name or name in {"", ".", ".."}:
        raise _changed("The comparison artifact name is invalid.")
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(descriptor, "rb") as stream:
        identity = os.fstat(stream.fileno())
        if not stat.S_ISREG(identity.st_mode) or (collect and identity.st_size > 8 * 1024 * 1024):
            raise _changed("The comparison artifact is not an admitted regular file.")
        if collect:
            content = stream.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024:
                raise _changed("The comparison review exceeds its finite read limit.")
            digest = sha256(content).hexdigest()
        else:
            value = sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(block)
            digest, content = value.hexdigest(), b""
        after = os.fstat(stream.fileno())
        path = (folder / name).lstat()
        before = (identity.st_dev, identity.st_ino, identity.st_size, identity.st_mtime_ns, identity.st_ctime_ns)
        if any((member.st_dev, member.st_ino, member.st_size, member.st_mtime_ns, member.st_ctime_ns) != before
               for member in (after, path)):
            raise _changed("A comparison artifact changed during its byte check.")
    return digest, content


def _changed(message: str) -> TaskControlError:
    return TaskControlError("comparison_candidate_changed", message)


def seal_review(folder: Path, identifier: str, baseline: dict[str, Any], evidence: dict[str, Any]) -> dict[str, str]:
    image = evidence["preview"]
    files = {}
    for name, digest in evidence["evidence_files"].items():
        path = Path(name)
        if path.parent != folder or path.is_symlink():
            raise _changed("Native comparison evidence escaped its private attempt directory.")
        files[path.name] = digest
    review = {"candidate_id": identifier, "baseline": baseline, "files": files, "preview": image,
              **{key: evidence[key] for key in ("changes", "scientific_audit", "presentation_hash",
                                               "ir_hash", "native_state_hash", "compiler_identity")}}
    review["operation_id"] = canonical_json_sha256(review)
    with exclusive_directory_lease(folder) as lease:
        _verify_files(folder, review, lease.fd)
        atomic_write_json(folder / "review.json", review)
        digest, _ = _file(folder, "review.json", lease.fd, collect=True)
        lease.verify()
    return {"directory": folder.name, "sha256": digest}


def _verify_files(folder: Path, review: dict[str, Any], fd: int) -> None:
    image = review["preview"]
    path = Path(image["path"])
    files = review["files"]
    if (path.parent != folder or path.suffix != ".png" or files.get(path.name) != image["sha256"]
            or set(files) != {path.name, "document.vsz", f'plot-ir-{review["ir_hash"]}.json'}):
        raise _changed("The review does not name one complete set of its private IR, native document and PNG.")
    for name, expected in review["files"].items():
        digest, _ = _file(folder, name, fd)
        if expected != digest:
            raise _changed("A sealed comparison artifact changed.")


def read_review(root: Path, baseline: dict[str, Any], identifier: str, record: dict[str, str]) -> dict[str, Any]:
    directory = record["directory"]
    folder = root / directory
    if (Path(directory).name != directory or not directory.startswith("candidate-")
            or folder.resolve() != folder or folder.parent != root):
        raise _changed("The candidate directory is not in the original comparison namespace.")
    with exclusive_directory_lease(folder) as lease:
        digest, content = _file(folder, "review.json", lease.fd, collect=True)
        if digest != record["sha256"]:
            raise _changed("The sealed candidate review changed.")
        review = json.loads(content)
        if (not isinstance(review, dict) or review["candidate_id"] != identifier or review["baseline"] != baseline
                or canonical_json_sha256({key: val for key, val in review.items() if key != "operation_id"}) != review["operation_id"]
                or review["scientific_audit"]["status"] != "passed"):
            raise _changed("The preview is not audited for this exact baseline and candidate.")
        _verify_files(folder, review, lease.fd)
        lease.verify()
    return {**review, "review_path": str(folder / "review.json")}
