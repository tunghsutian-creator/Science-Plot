"""One exact tracked namespace becomes a refusal shell and registered history."""
import hashlib
from pathlib import Path
from typing import Any

from sciplot_core.project_commands import MembershipRead, NamespaceMember, NamespaceTransfer, PreparedFile
from sciplot_core.project_store.errors import ProjectStoreError
from .attachment_fence import refusal
from .attachment_index import OWNER, encode
from .errors import EngineError
from .legacy_namespace import LegacyNamespace


def retire_namespace(store: Any, observed: LegacyNamespace, marker: dict[str, Any], entry: dict[str, Any],
                     snapshot: dict[str, Any], writes: dict[str, Any]) -> tuple[tuple[NamespaceTransfer, ...], tuple[MembershipRead, ...]]:
    prefix = observed.prefix
    if prefix is None:
        return (), ()
    physical_prefix = None
    try:
        physical_prefix = store.logical_path(Path(marker["history_root"]) / "head.json").removesuffix("/head.json")
    except ProjectStoreError:
        pass
    history_prefix = physical_prefix or entry["namespace"] + "/original-history"
    entry.update(history_prefix=history_prefix, physical_backup_prefix=physical_prefix)
    original_head = hashlib.sha256(observed.members["head.json"]).hexdigest()
    shell, owner, history_owner = encode(refusal(marker, original_head)), encode({**marker, "role": "redirect"}), encode({**marker, "role": "history"})
    for name in snapshot["files"]:
        if name.startswith(prefix + "/"):
            writes[name] = None
    for relative, data in observed.members.items():
        writes[prefix + "/" + relative] = None
        writes[history_prefix + "/" + relative] = PreparedFile(data, observed.modes[relative])
    writes[prefix + "/head.json"] = PreparedFile(shell, 0o600)
    writes[prefix + "/" + OWNER] = PreparedFile(owner, 0o600)
    writes[history_prefix + "/" + OWNER] = PreparedFile(history_owner, 0o600)
    members = tuple(NamespaceMember(name, hashlib.sha256(data).hexdigest(), len(data), observed.modes[name])
                    for name, data in sorted(observed.members.items()))
    transfer = NamespaceTransfer(prefix, history_prefix, entry["id"], original_head,
        hashlib.sha256(shell).hexdigest(), hashlib.sha256(owner).hexdigest(), hashlib.sha256(history_owner).hexdigest(),
        members, physical_prefix)
    memberships = tuple(MembershipRead.capture(snapshot["files"], name) for name in dict.fromkeys(
        (prefix, history_prefix, physical_prefix) if physical_prefix else (prefix, history_prefix)))
    return (transfer,), memberships


def retire_artifacts(store: Any, artifacts: Any, snapshot: dict[str, Any], writes: dict[str, Any]) -> None:
    if artifacts.root is None:
        return
    for relative, data in artifacts.members.items():
        # Only managed compiler product directories are disposable. Other
        # published files/notes retain their independent complete-project owner.
        parts = Path(relative).parts
        if len(parts) < 3 or parts[0] != "artifacts" or len(parts[1]) != 64 or any(c not in "0123456789abcdef" for c in parts[1]):
            continue
        try:
            logical = store.logical_path(artifacts.root / relative)
        except ProjectStoreError:
            continue
        before = snapshot["files"].get(logical)
        if before is None:
            continue
        if before["sha256"] != hashlib.sha256(data).hexdigest() or before["mode"] != artifacts.modes[relative]:
            raise EngineError("managed_external_mutation", "The old registered compiler product differs from the current validated artifact.")
        writes[logical] = None
