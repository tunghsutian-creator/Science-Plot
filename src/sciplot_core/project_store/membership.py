"""Exact logical membership over host-confined resource namespaces."""

import os
import stat
from typing import Any

from sciplot_core.project_commands.resources import MembershipRead, membership_digest

from .errors import ProjectConflict, ProjectRecoveryRequired
from .io import StoreIO, directory, member_names, parts


def physical_names(io: StoreIO, prefix: str) -> set[str]:
    if prefix.startswith("@"):
        root, _, relative = prefix.partition("/")
        key = root[1:]
    else:
        key, relative = "", prefix
    if key not in io.root_fds:
        raise ProjectRecoveryRequired("The membership guard needs its explicit trusted resource root.")
    fd = io.root_fds[key]
    allowed = io.location_members.get(key)
    if key and allowed is not None:
        result = set()
        for name in allowed:
            if relative and name != relative and not name.startswith(relative + "/"):
                continue
            components = parts(name)
            try:
                with directory(fd, components[:-1]) as parent:
                    info = os.stat(components[-1], dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise ProjectConflict("An exact trusted file member became a symbolic or special entry.")
                result.add(f"@{key}/{name}")
            except FileNotFoundError:
                pass
        return result
    components = parts(relative) if relative else ()
    try:
        with directory(fd, components) as selected:
            names = member_names(selected, exclude=(".sciplot_resources",) if not key and not components else ())
    except FileNotFoundError:
        return set()
    except NotADirectoryError:
        with directory(fd, components[:-1]) as parent:
            info = os.stat(components[-1], dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ProjectConflict("A membership namespace is not an ordinary file or directory.") from None
        return {prefix}
    return {prefix + "/" + name if prefix else name for name in names}


def require_memberships(io: StoreIO, baseline: dict[str, Any], current: dict[str, Any], record: dict[str, Any]) -> None:
    values = record.get("metadata", {}).get("read_memberships", [])
    seen = set()
    for supplied in values:
        guard = MembershipRead(**supplied)
        if guard.prefix in seen:
            raise ProjectConflict("A command cannot bind one membership namespace twice.")
        seen.add(guard.prefix)
        if (MembershipRead.capture(baseline["files"], guard.prefix) != guard
                or MembershipRead.capture(current["files"], guard.prefix) != guard
                or membership_digest(physical_names(io, guard.prefix)) != guard.members_sha256):
            raise ProjectConflict("A declared whole-set membership changed inside or outside the generation.")
