"""Exact sealed input views created only by explicit complete bundle import."""

import os
from pathlib import Path
import stat
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands.resources import SourceTreeRead

from .errors import ProjectConflict
from .io import STORE, StoreIO, digest, directory, install, parts, read_file
from .source_tree_io import observe
import sciplot_core.project_store.state as state


class _IncompleteCapture(ProjectConflict):
    """An old completed command may never have frozen its optional raw reads."""


def _draft(io: StoreIO, current: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    if record["project_id"] != current["project_id"]:
        raise ProjectConflict("Prepared inputs belong to another stable project.")
    draft = state.sealed_draft(io, record)
    if (record.get("metadata", {}).get("source_trees")
            and draft.get("source_tree_origins") != record.get("source_tree_origins")):
        raise ProjectConflict("Prepared inputs lost their sealed original tree observation.")
    return draft


def _entries(io: StoreIO, draft: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for source_id, versions in draft.get("sources", {}).items():
        for version, entry in versions.items():
            if (entry.get("source_id") != source_id or entry.get("version") != version
                    or entry.get("sha256") != version or type(entry.get("mode")) is not int
                    or not 0 <= entry["mode"] <= 0o777):
                raise ProjectConflict("A sealed input has inconsistent identity, version, or permissions.")
            try:
                io.get(entry)
            except OSError as exc:
                raise ProjectConflict("The exact sealed prepared source blob is missing.") from exc
            result.append(entry)
    return result


def _file_version(entry: dict[str, Any]) -> str:
    return canonical_json_sha256({"kind": "file", "content_sha256": entry["sha256"]}, allow_nan=False)


def _write_file(io: StoreIO, relative: str, entry: dict[str, Any]) -> None:
    components = parts(relative)
    with directory(io.fd, components[:-1], create=True) as parent:
        data = io.get(entry)
        try:
            install(parent, components[-1], data, mode=0o400, exclusive=True)
        except FileExistsError:
            pass
        if read_file(parent, components[-1], owned=True) != (data, 0o400):
            raise ProjectConflict("An imported prepared input cache differs from its exact frozen bytes or mode.")


def _seal_dirs(io: StoreIO, components: tuple[str, ...]) -> None:
    with directory(io.fd, components) as fd:
        for name in os.listdir(fd):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                _seal_dirs(io, (*components, name))
            elif not stat.S_ISREG(info.st_mode):
                raise ProjectConflict("Prepared input views refuse symbolic or special entries.")
        os.fchmod(fd, 0o500)
        os.fsync(fd)


def _proof(io: StoreIO, relative: str, expected: str) -> dict[str, Any]:
    version, proof = observe(str(io.root / STORE / Path(*parts(relative))))
    if version != expected:
        raise ProjectConflict("The complete prepared input view differs from its frozen composite hash.")
    return {"path": relative, "observed": proof}


def _verify(io: StoreIO, view: dict[str, Any], expected: str) -> Path:
    relative = view.get("path")
    if not isinstance(relative, str) or parts(relative)[0] != "prepared_inputs":
        raise ProjectConflict("A prepared input view must remain inside its exact private cache.")
    actual = _proof(io, relative, expected)
    if actual != view:
        raise ProjectConflict("The prepared input view changed its host-bound inode or permissions.")
    return io.root / STORE / Path(*parts(relative))


def _matching(entries: list[dict[str, Any]], locators: set[str], mode: int) -> dict[str, Any]:
    found = [entry for entry in entries if entry["locator"] in locators]
    if not found:
        raise _IncompleteCapture("The selected tree has an original member without exact frozen source bytes.")
    if len(found) != 1 or found[0]["mode"] != stat.S_IMODE(mode):
        raise ProjectConflict("A complete original tree needs one exact captured source for every ordinary member and mode.")
    return found[0]


def _tree(io: StoreIO, record: dict[str, Any], draft: dict[str, Any], guard: SourceTreeRead,
          entries: list[dict[str, Any]], base: str) -> dict[str, Any]:
    origin = draft.get("source_tree_origins", {}).get(guard.locator)
    if not isinstance(origin, dict) or set(origin) != {"root", "members", "actual"}:
        raise ProjectConflict("A complete prepared tree needs its exact sealed original member observation.")
    root = origin["root"]
    mode = root.get("mode")
    if (set(root) != {"device", "inode", "mode"} or any(type(value) is not int for value in root.values())
            or not isinstance(origin["members"], dict) or not isinstance(origin["actual"], str)):
        raise ProjectConflict("The original tree observation has invalid permissions or members.")
    relative = base + "/trees/" + digest(guard.locator) + "/" + Path(guard.locator).name
    locators = {guard.locator, origin["actual"]}
    captured: dict[str, dict[str, Any]] = {}
    if stat.S_ISREG(mode):
        if origin["members"]:
            raise ProjectConflict("A frozen single-file source cannot contain invented child members.")
        entry = _matching(entries, locators, mode)
        if _file_version(entry) != guard.tree_sha256:
            raise ProjectConflict("The frozen file version differs from the selected source-tree witness.")
        _write_file(io, relative, entry)
    elif stat.S_ISDIR(mode):
        for name, observed in origin["members"].items():
            if not isinstance(observed, dict) or set(observed) != {"device", "inode", "mode"} or any(
                    type(value) is not int for value in observed.values()):
                raise ProjectConflict("A prepared tree member lost its exact original inode and mode proof.")
            components = parts(name)
            for index in range(1, len(components)):
                parent = origin["members"].get("/".join(components[:index]), {})
                if not stat.S_ISDIR(parent.get("mode", 0)):
                    raise ProjectConflict("The frozen source tree lacks an exact ordinary parent directory.")
            member_mode = observed.get("mode")
            if type(member_mode) is not int or not (stat.S_ISREG(member_mode) or stat.S_ISDIR(member_mode)):
                raise ProjectConflict("A prepared source tree cannot restore an alias or special member.")
            if stat.S_ISREG(member_mode):
                captured[name] = _matching(entries, {str(Path(path) / name) for path in locators}, member_mode)
        payload = {"kind": "directory", "files": [{"path": name, "content_sha256": captured[name]["sha256"]}
            for name in sorted(captured, key=Path)]}
        if canonical_json_sha256(payload, allow_nan=False) != guard.tree_sha256:
            raise ProjectConflict("Captured sources do not cover the complete selected source-tree hash.")
        with directory(io.fd, parts(relative), create=True):
            pass
        for name, observed in sorted(origin["members"].items(), key=lambda item: len(Path(item[0]).parts)):
            if stat.S_ISDIR(observed["mode"]):
                with directory(io.fd, (*parts(relative), *parts(name)), create=True):
                    pass
        for name, entry in captured.items():
            _write_file(io, relative + "/" + name, entry)
        _seal_dirs(io, parts(relative))
    else:
        raise ProjectConflict("A prepared input tree requires an original ordinary file or directory.")
    view = _proof(io, relative, guard.tree_sha256)
    local_members = view["observed"]["members"]
    if set(local_members) != set(origin["members"]):
        raise ProjectConflict("The imported prepared tree has unrecognized or missing original member names.")
    for name, original in origin["members"].items():
        expected_mode = stat.S_IFDIR | 0o500 if stat.S_ISDIR(original["mode"]) else stat.S_IFREG | 0o400
        if local_members[name]["mode"] != expected_mode:
            raise ProjectConflict("A prepared tree cache member lost its fixed read-only permission mode.")
    return {"tree_sha256": guard.tree_sha256, **view}


def bind_import(io: StoreIO, current: dict[str, Any], record: dict[str, Any], local: dict[str, Any]) -> None:
    if record["phase"] not in {"needs_review", "accepted", "complete"}:
        return
    draft = _draft(io, current, record)
    entries = _entries(io, draft)
    base = "prepared_inputs/" + digest(record["command_id"]) + "/" + record["decision_id"]
    sources: dict[str, Any] = {}
    for entry in entries:
        if local["versions"].get(entry["source_id"], {}).get(entry["version"]) != entry["sha256"]:
            raise ProjectConflict("A prepared input was not explicitly inventoried by this cold import.")
        relative = base + "/sources/" + entry["source_id"] + "/" + entry["version"] + "/" + Path(entry["locator"]).name
        _write_file(io, relative, entry)
        sources.setdefault(entry["source_id"], {})[entry["version"]] = _proof(io, relative, _file_version(entry))
    trees = {}
    for item in record.get("metadata", {}).get("source_trees", []):
        try:
            trees[item["locator"]] = _tree(io, record, draft, SourceTreeRead(**item), entries, base)
        except _IncompleteCapture:
            if record["phase"] != "complete":
                raise
            # Complete reply replay needs no raw IO. It does not create an
            # unproved directory capability for an uncaptured historical read.
    local.setdefault("prepared", {})[digest(record["command_id"])] = {
        "project_id": record["project_id"], "command_id": record["command_id"],
        "command_digest": record["command_digest"], "decision_id": record["decision_id"],
        "sources": sources, "trees": trees}


def _binding(io: StoreIO, current: dict[str, Any], record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    draft = _draft(io, current, record)
    imported = io.read("local_resource_roots.json")
    if imported is not None and not isinstance(imported.get("commands"), list):
        raise ProjectConflict("The cold input binding lost its exact imported command census.")
    if imported is None or record["command_id"] not in imported.get("commands", []):
        return None
    if imported.get("project_id") != current["project_id"]:
        raise ProjectConflict("The imported input index belongs to another stable project.")
    local = io.read("local_sources.json")
    binding = local.get("prepared", {}).get(digest(record["command_id"])) if local else None
    if binding is None:
        raise ProjectConflict("This imported command has no complete frozen input binding; recover it explicitly.")
    if any(binding.get(key) != record.get(key) for key in ("project_id", "command_id", "command_digest", "decision_id")):
        raise ProjectConflict("The imported input view does not belong to this exact command and decision.")
    if not isinstance(binding.get("sources"), dict) or not isinstance(binding.get("trees"), dict):
        raise ProjectConflict("The imported input view lost its exact source and tree member maps.")
    assert local is not None
    return draft, binding, local


def input_path(io: StoreIO, current: dict[str, Any], record: dict[str, Any], *, locator: str,
               expected_sha256: str, source_id: str | None) -> Path | None:
    selected = _binding(io, current, record)
    if selected is None:
        return None
    draft, binding, local = selected
    entries = [entry for entry in _entries(io, draft) if entry["locator"] == locator and entry["version"] == expected_sha256
               and (source_id is None or source_id == entry["source_id"] or source_id in entry.get("aliases", []))]
    if len(entries) != 1:
        raise ProjectConflict("The prepared source locator, ID and exact content version are missing or ambiguous.")
    entry = entries[0]
    if local["versions"].get(entry["source_id"], {}).get(entry["version"]) != entry["sha256"]:
        raise ProjectConflict("The exact prepared source version is absent from its explicit cold inventory.")
    view = binding["sources"].get(entry["source_id"], {}).get(entry["version"])
    if view is None:
        raise ProjectConflict("The exact prepared source has no sealed local read view.")
    expected_path = ("prepared_inputs/" + digest(record["command_id"]) + "/" + record["decision_id"]
        + "/sources/" + entry["source_id"] + "/" + entry["version"] + "/" + Path(entry["locator"]).name)
    if view.get("path") != expected_path:
        raise ProjectConflict("The prepared input cache path does not belong to this exact sealed source and command.")
    return _verify(io, view, _file_version(entry))


def tree_path(io: StoreIO, current: dict[str, Any], record: dict[str, Any], *, locator: str,
              tree_sha256: str) -> Path | None:
    selected = _binding(io, current, record)
    if selected is None:
        return None
    draft, binding, local = selected
    guards = [item for item in record.get("metadata", {}).get("source_trees", [])
              if item == {"locator": locator, "tree_sha256": tree_sha256}]
    if len(guards) != 1:
        raise ProjectConflict("The prepared tree must match one exact sealed source-tree witness.")
    view = binding["trees"].get(locator)
    if view is None or view["tree_sha256"] != tree_sha256:
        raise ProjectConflict("The complete selected tree has no exact cold read binding.")
    expected_path = ("prepared_inputs/" + digest(record["command_id"]) + "/" + record["decision_id"]
        + "/trees/" + digest(locator) + "/" + Path(locator).name)
    if view.get("path") != expected_path:
        raise ProjectConflict("The prepared tree cache path does not belong to this exact sealed source and command.")
    for entry in _entries(io, draft):
        if local["versions"].get(entry["source_id"], {}).get(entry["version"]) != entry["sha256"]:
            raise ProjectConflict("A frozen tree input lost its exact explicit cold source-version inventory.")
    return _verify(io, {key: value for key, value in view.items() if key != "tree_sha256"}, tree_sha256)
