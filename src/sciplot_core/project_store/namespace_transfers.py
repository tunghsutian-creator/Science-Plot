"""The one fixed semantic ownership fence, with exact before/after observations."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from sciplot_core.project_commands.resources import MembershipRead, NamespaceMember, NamespaceTransfer

from .errors import ProjectConflict, ProjectRecoveryRequired, ProjectStoreError
from .io import StoreIO, digest, directory
from .namespace_io import OWNER, census, descriptors, identity, scope
from .locators import original_for_logical
import sciplot_core.project_store.state as state


@dataclass
class Admission:
    physical: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    memberships: dict[str, set[str]] = field(default_factory=dict)
    root_exemptions: set[str] = field(default_factory=set)
    installed: set[str] = field(default_factory=set)
    history: set[str] = field(default_factory=set)


def values(record: dict[str, Any]) -> tuple[NamespaceTransfer, ...]:
    supplied = record.get("metadata", {}).get("namespace_transfers", [])
    if not isinstance(supplied, list) or len(supplied) > 1:
        raise ProjectStoreError("Only one fixed semantic ownership transfer may be admitted.")
    if supplied and record["metadata"].get("kind") != "attachment_import":
        raise ProjectStoreError("Only an exact attachment import may transfer semantic ownership.")
    result = []
    for item in supplied:
        payload = dict(item)
        members = tuple(NamespaceMember(**member) for member in payload.pop("members"))
        result.append(NamespaceTransfer(**payload, members=members))
    return tuple(result)


def _observed(transfer: NamespaceTransfer) -> dict[str, Any]:
    return {member.relative: {key: getattr(member, key) for key in ("sha256", "size", "mode")}
            for member in transfer.members}


def _backup(io: StoreIO, record: dict[str, Any], transfer: NamespaceTransfer,
            actual_origin: Path, origin_identity: dict[str, int]) -> tuple[Path, dict[str, int], dict[str, Any]]:
    path = io.namespace_backups.get(transfer.attachment_id)
    request = record.get("metadata", {}).get("request", {})
    if (path is None or path.resolve(strict=True) != path or path == actual_origin
            or path.parent != actual_origin.parent or request.get("history_root") != str(path)):
        raise ProjectRecoveryRequired("This ownership transfer needs its exact host-supplied sibling backup read capability.")
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        origin = os.stat(actual_origin.name, dir_fd=parent, follow_symlinks=False)
        if (origin.st_dev, origin.st_ino) != (origin_identity["device"], origin_identity["inode"]):
            raise ProjectConflict("The supplied backup does not share the observed namespace's physical parent.")
        with directory(parent, (path.name,)) as descriptor:
            before = identity(descriptor)
            if os.fstat(descriptor).st_uid != os.geteuid():
                raise ProjectRecoveryRequired("The namespace backup is not owned by this host account.")
            captured = census(descriptor)
            after = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if identity(descriptor) != before or (after.st_dev, after.st_ino) != (before["device"], before["inode"]):
                raise ProjectConflict("The explicit namespace backup changed directory identity.")
    finally:
        os.close(parent)
    return path, before, captured


def _control(record: dict[str, Any], transfer: NamespaceTransfer, members: dict[str, Any], role: str) -> None:
    expected = {"head.json": transfer.refusal_sha256, OWNER: transfer.owner_sha256} if role == "redirect" else {OWNER: transfer.history_owner_sha256}
    for name, version in expected.items():
        entry = members.get(name)
        if entry is None or entry["sha256"] != version or entry["mode"] != 0o600:
            raise ProjectConflict("The semantic ownership control record differs from its frozen bytes or mode.")
    owner = json.loads(members[OWNER]["data"])
    request = record["metadata"].get("request", {})
    expected_owner = {"kind": "sciplot_semantic_owner", "version": 1,
        "origin_root": request.get("origin_root"), "project": request.get("project_path"),
        "project_id": record["project_id"], "attachment_id": transfer.attachment_id,
        "history_root": request.get("history_root"), "figure_id": request.get("figure_id"), "role": role}
    if not isinstance(owner, dict) or owner != expected_owner or type(owner.get("version")) is not int:
        raise ProjectConflict("The semantic ownership marker does not bind this exact project and attachment.")
    if role == "redirect":
        head = json.loads(members["head.json"]["data"])
        if not isinstance(head, dict) or head != {"kind": "sciplot_attached_semantic_redirect", "version": 1,
                    "project_id": record["project_id"], "attachment_id": transfer.attachment_id,
                    "original_head_sha256": transfer.original_head_sha256} or type(head.get("version")) is not int:
            raise ProjectConflict("The old semantic writer is not fenced by the exact fixed refusal head.")


def _full(prefix: str, members: dict[str, Any]) -> dict[str, Any]:
    return {prefix + "/" + name: entry for name, entry in members.items()}


def require(io: StoreIO, current: dict[str, Any], record: dict[str, Any], *, admit: bool = False,
            committed: bool = False) -> Admission:
    result = Admission()
    for transfer in values(record):
        baseline = state.reachable(io, current, record["expected_generation"])
        prefix, history = transfer.prefix, transfer.history_prefix
        observed = _observed(transfer)
        tracked = {name: entry for name, entry in baseline["files"].items() if name.startswith(prefix + "/")}
        guards = [MembershipRead(**item) for item in record.get("metadata", {}).get("read_memberships", [])]
        for guarded in (prefix, history):
            expected_guard = MembershipRead.capture(baseline["files"], guarded)
            if expected_guard not in guards or MembershipRead.capture(current["files"], guarded) != expected_guard:
                raise ProjectConflict("The complete old namespace and empty history memberships must remain bound.")
        old_names = set(tracked) | set(_full(prefix, observed)) | {prefix + "/" + OWNER}
        history_entries = {**observed, OWNER: {"sha256": transfer.history_owner_sha256, "mode": 0o600}}
        history_names = set(_full(history, history_entries))
        physical_prefix = transfer.physical_backup_prefix
        physical_names = set(_full(physical_prefix, history_entries)) if physical_prefix else set()
        if physical_prefix and any(name.startswith(physical_prefix + "/") for name in current["files"]):
            raise ProjectConflict("Physical history observations cannot replace an existing managed namespace.")
        for name in old_names | history_names | physical_names:
            expected = baseline["files"].get(name)
            if name not in record["read_set"] or record["read_set"][name] != (expected["sha256"] if expected else None):
                raise ProjectConflict("The transfer must bind every old record and every new history destination.")
        if not old_names | history_names | physical_names <= set(record["write_set"]):
            raise ProjectConflict("The transfer does not retire its entire old namespace or preserve its complete history.")
        if (set(name for name in record["write_set"] if name.startswith(prefix + "/")) != old_names
                or set(name for name in record["write_set"] if name.startswith(history + "/")) != history_names):
            raise ProjectConflict("A semantic ownership transfer cannot add undeclared namespace records.")
        if physical_prefix and set(name for name in record["write_set"] if name.startswith(physical_prefix + "/")) != physical_names:
            raise ProjectConflict("The observed physical history must declare exactly its complete known closure.")
        if any(name.startswith(history + "/") for name in baseline["files"]):
            raise ProjectConflict("A transfer cannot replace another existing history namespace.")
        request = record["metadata"].get("request", {})
        origin = str(Path(original_for_logical(baseline, prefix + "/head.json")).parent)
        if (request.get("scientific_origin", request.get("origin_root")) != origin
                or request.get("project_path") != str(io.root) or request.get("attachment_id") != transfer.attachment_id):
            raise ProjectConflict("The transfer origin and stable ownership context do not match this project.")
        with scope(io, prefix) as (fd, actual, allowed):
            here, physical = identity(fd), census(fd, allowed=allowed)
        if request.get("origin_root") != str(actual):
            raise ProjectConflict("The transfer does not bind its exact host-selected physical namespace.")
        backup, backup_identity, backup_members = _backup(io, record, transfer, actual, here)
        if physical_prefix:
            with scope(io, physical_prefix) as (_fd, declared, _allowed):
                if declared != backup:
                    raise ProjectConflict("The declared physical history prefix is not the exact supplied backup.")
        elif backup.is_relative_to(io.root) and not backup.is_relative_to(io.root / ".sciplot_resources"):
            raise ProjectConflict("An in-project physical backup must be registered as exact read-only history observations.")
        posted = record.get("phase") in {"accepted", "complete"} or committed
        if not posted:
            if descriptors(physical) != observed or set(backup_members) != {"head.json", OWNER}:
                raise ProjectConflict("The latest old namespace or its prepared refusal shell changed before ownership transfer.")
            _control(record, transfer, backup_members, "redirect")
            if backup_identity["mode"] != 0o700:
                raise ProjectConflict("The prepared ownership shell is not a private directory.")
            if admit:
                record.setdefault("namespace_origins", {})[transfer.attachment_id] = {"original": here, "shell": backup_identity}
            origins = record.get("namespace_origins", {}).get(transfer.attachment_id)
            if origins != {"original": here, "shell": backup_identity}:
                raise ProjectConflict("The ownership transfer no longer observes its admitted directory pair.")
        else:
            if set(physical) != {"head.json", OWNER}:
                raise ProjectConflict("The fenced old namespace has unrecognized records.")
            _control(record, transfer, physical, "redirect")
            _control(record, transfer, backup_members, "history")
            if descriptors({name: entry for name, entry in backup_members.items() if name != OWNER}) != observed:
                raise ProjectConflict("The exact old namespace history differs from the frozen latest observation.")
            origins = record.get("namespace_origins", {}).get(transfer.attachment_id)
            if origins != {"original": backup_identity, "shell": here}:
                raise ProjectConflict("The ownership fence did not preserve its admitted atomic directory exchange.")
            if prefix.startswith("@") and "/" not in prefix:
                result.root_exemptions.add(prefix[1:])
        draft = record.get("draft")
        if draft is not None or posted:
            if draft is None or record.get("decision_id") != digest({"command_digest": record["command_digest"], "candidate": draft}):
                raise ProjectConflict("Ownership publication requires the exact accepted sealed transfer.")
            frozen = draft["writes"]
            for name in old_names:
                expected = ({"sha256": transfer.refusal_sha256, "mode": 0o600} if name == prefix + "/head.json"
                    else {"sha256": transfer.owner_sha256, "mode": 0o600} if name == prefix + "/" + OWNER else None)
                if (frozen.get(name) is not None if expected is None else frozen.get(name) is None
                        or any(frozen[name][key] != value for key, value in expected.items())):
                    raise ProjectConflict("The accepted transfer does not contain the exact refusal and retirement set.")
            for name, expected in {**_full(history, history_entries), **(_full(physical_prefix, history_entries) if physical_prefix else {})}.items():
                if frozen.get(name) is None or any(frozen[name][key] != value for key, value in expected.items()):
                    raise ProjectConflict("The accepted transfer does not preserve its exact original history closure.")
        result.physical.update({name: None for name in old_names})
        result.physical.update(_full(prefix, descriptors(physical)))
        result.memberships[prefix] = set(_full(prefix, physical))
        if physical_prefix:
            result.physical.update({name: None for name in physical_names})
            result.physical.update(_full(physical_prefix, descriptors(backup_members)))
            result.memberships[physical_prefix] = set(_full(physical_prefix, backup_members))
            result.history.update(physical_names)
            result.installed.update(physical_names)
        result.installed.update(old_names)
        result.history.update(history_names)
    return result


def root_exemptions(io: StoreIO, current: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    try:
        with directory(io.fd, ("commands",)) as parent:
            names = [name for name in os.listdir(parent) if name.endswith(".json")]
    except FileNotFoundError:
        return result
    for name in names:
        record = io.read("commands/" + name)
        if record and record["phase"] == "accepted" and record["command_id"] not in current["commands"]:
            if any(item.prefix.startswith("@") and "/" not in item.prefix for item in values(record)):
                result.update(require(io, current, record).root_exemptions)
    return result


def verify_committed(io: StoreIO, current: dict[str, Any], record: dict[str, Any]) -> None:
    for transfer in values(record):
        with scope(io, transfer.prefix) as (fd, _actual, allowed):
            members = census(fd, allowed=allowed)
        if set(members) != {"head.json", OWNER}:
            raise ProjectRecoveryRequired("The committed semantic refusal shell changed outside its generation.")
        _control(record, transfer, members, "redirect")
        if transfer.physical_backup_prefix:
            with scope(io, transfer.physical_backup_prefix) as (fd, _actual, allowed):
                history = census(fd, allowed=allowed)
            expected = {**_observed(transfer), OWNER: {"sha256": transfer.history_owner_sha256, "mode": 0o600}}
            if set(history) != set(expected) or any(any(history[name][key] != value for key, value in entry.items())
                for name, entry in expected.items()):
                raise ProjectRecoveryRequired("The committed read-only semantic history changed outside its generation.")
            _control(record, transfer, history, "history")


def reject_pending_bundle(io: StoreIO, current: dict[str, Any]) -> None:
    try:
        with directory(io.fd, ("commands",)) as parent:
            names = [name for name in os.listdir(parent) if name.endswith(".json")]
    except FileNotFoundError:
        return
    for name in names:
        record = io.read("commands/" + name)
        if (not record or record["command_id"] in current["commands"] or record.get("draft") is None
                or record.get("metadata", {}).get("kind") != "attachment_import"):
            continue
        # A rejected tracked transfer is inert only when its admitted original
        # inode and exact prepared shell are still in their pre-fence positions.
        if record.get("phase") == "rejected" and values(record):
            try:
                require(io, current, record)
            except (ProjectConflict, ProjectRecoveryRequired, OSError) as exc:
                raise ProjectRecoveryRequired("Resolve the rejected ownership transfer's physical fence before bundling.") from exc
            continue
        raise ProjectRecoveryRequired("Finish the pending semantic ownership transfer at its original location before bundling.")


def augment_controls(io: StoreIO, current: dict[str, Any], client_members: dict[str, tuple[str, ...] | None] | None = None) -> None:
    """Evolve only the fixed OWNER marker for an already granted old namespace."""
    for outcome in current["commands"].values():
        for transfer in values(outcome):
            prefix = transfer.prefix
            if not prefix.startswith("@"):
                continue
            root, _, relative = prefix.partition("/")
            key = root[1:]
            if key not in io.location_members:
                continue
            head_relative = relative + "/head.json" if relative else "head.json"
            owner_relative = relative + "/" + OWNER if relative else OWNER
            published = state.reachable(io, current, outcome["generation"])
            if published.get("parent") is None:
                raise ProjectConflict("A namespace transfer has no committed prior generation.")
            baseline = state.generation(io, published["parent"])
            required = {name[len(root) + 1:] for name in baseline["files"] if name.startswith(prefix + "/")}
            controls = {}
            for name, expected in (("head.json", transfer.refusal_sha256), (OWNER, transfer.owner_sha256)):
                entry = current["files"].get(prefix + "/" + name)
                if entry is None or entry["sha256"] != expected or entry["mode"] != 0o600:
                    raise ProjectConflict("The committed semantic control marker is not the fixed admitted protocol.")
                controls[name] = {**entry, "data": io.get(entry)}
            _control(outcome, transfer, controls, "redirect")
            for target in (io.location_members, client_members):
                if target is None or target.get(key) is None:
                    continue
                allowed = set(target[key] or ())
                if head_relative in allowed and required.issubset(allowed):
                    target[key] = tuple(sorted(allowed | {owner_relative}))
