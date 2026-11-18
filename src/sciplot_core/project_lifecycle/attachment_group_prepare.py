"""Recover complete pre-publication figures in their Store-owned workspace."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.foundation.writer_lease import exclusive_directory_lease
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, SourceTreeRead
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.io import install
from sciplot_core.project_store.native_work import MANAGED_GROUP_PREPARE

from .attachment_group import PreparedFigure
from .attachment_index import Attachment, encode
from .attachment_sources import capture_source
from .errors import EngineError
from .repository import digest


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class GroupPreparation:
    def __init__(self, store: FileProjectStore, workspace: Path, command: ProjectCommand,
                 figures: dict[str, str]) -> None:
        self.store, self.workspace, self.command, self.figures = store, workspace, command, figures

    def figure(self, figure_id: str, prepare: Callable[[Path], PreparedFigure]) -> PreparedFigure:
        """Return a sealed exact figure, otherwise execute only this missing figure."""
        expected = self.figures.get(figure_id)
        if expected is None:
            raise EngineError("semantic_group_prepare_unknown_figure", "Choose one figure in the exact saved plan.")
        root = self.workspace / digest(figure_id)
        root.mkdir(exist_ok=True)
        marker = root / "prepared.json"
        if marker.exists():
            value = json.loads(capture_source(marker)[0])
            if (value is None or value.get("figure_id") != figure_id or value.get("figure_request") != expected
                    or value.get("command") != self.command.command_digest):
                raise EngineError("semantic_group_prepare_corrupt", "This completed figure does not belong to the exact prepared command.")
            sealed = value.pop("seal", None)
            if sealed != digest(value):
                raise EngineError("semantic_group_prepare_corrupt", "The completed figure manifest changed.")
            return PreparedFigure(Attachment(self.store, value["entry"]),
                                  self._read(root, value["members"]), self._read(root, value["assets"]),
                                  value["export_evidence"])
        # A process can leave a valid VSZ or partial export before the group
        # manifest exists. Native compilation never overwrites those bytes.
        figure = prepare(root / ("attempt-" + uuid4().hex))
        if figure.attachment.entry["figure_id"] != figure_id:
            raise EngineError("semantic_group_prepare_unknown_figure", "A prepared figure cannot claim another planned identity.")
        value = {"figure_id": figure_id, "figure_request": expected, "command": self.command.command_digest,
                 "entry": figure.attachment.entry, "members": self._write(root, figure.members),
                 "assets": self._write(root, figure.assets), "export_evidence": figure.export_evidence}
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            install(fd, "prepared.json", encode({**value, "seal": digest(value)}), exclusive=True)
        finally:
            os.close(fd)
        return figure

    @staticmethod
    def _write(root: Path, values: dict[str, bytes | None]) -> dict[str, str | None]:
        folder = root / "content"
        folder.mkdir(exist_ok=True)
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            result = {}
            for name, data in values.items():
                blob = _sha(data) if data is not None else None
                if blob is not None and data is not None:
                    path = folder / blob
                    if path.exists():
                        if capture_source(path)[0] != data:
                            raise EngineError("semantic_group_prepare_corrupt", "Prepared content bytes changed.")
                    else:
                        install(fd, blob, data, exclusive=True)
                result[name] = blob
            return result
        finally:
            os.close(fd)

    @staticmethod
    def _read(root: Path, inventory: dict[str, str | None]) -> dict[str, Any]:
        values = {}
        for name, version in inventory.items():
            if version is None:
                values[name] = None
                continue
            if re.fullmatch(r"[a-f0-9]{64}", version) is None:
                raise EngineError("semantic_group_prepare_corrupt", "A prepared file needs its exact byte identity.")
            try:
                data, _ = capture_source(root / "content" / version)
            except OSError as exc:
                raise EngineError("semantic_group_prepare_corrupt", "A completed candidate lost its sealed content.") from exc
            if _sha(data) != version:
                raise EngineError("semantic_group_prepare_corrupt", "A completed candidate's sealed content changed.")
            values[name] = data
        return values


@contextmanager
def prepare_attachment_group(
    store: FileProjectStore, *, key: str, plan: dict[str, Any], figures: dict[str, str],
    source_tree: SourceTreeRead, runtime: str,
) -> Iterator[GroupPreparation]:
    """Reserve a private work owner without publishing a project generation."""
    snapshot = store.snapshot()
    if source_tree_sha256(Path(source_tree.locator)) != source_tree.tree_sha256:
        raise EngineError("semantic_group_prepare_request_changed", "The original source tree no longer matches the prepared plan.")
    request = {"adapter": MANAGED_GROUP_PREPARE, "group_key": key, "plan": plan, "figures": list(figures.items()),
               "original": source_tree.to_payload(), "runtime": runtime}
    app = ProjectCommands(store)
    prior = app.query(key + ":prepare")
    if prior is None:
        command = ProjectCommand.create("semantic_record", key + ":prepare", project_id=snapshot["project_id"],
            expected_generation=snapshot["generation"], read_set={}, write_set=[], request=request,
            source_trees=(source_tree,))
        store.reserve(command.key, command.command_digest, expected_generation=command.expected_generation,
                      read_set={}, write_set=[], metadata=command.to_payload())
    else:
        command = ProjectCommand.from_payload(prior["metadata"])
        if (digest(command.to_payload()["request"]) != digest(request)
                or command.expected_generation != snapshot["generation"] or prior["phase"] != "reserved"):
            raise EngineError("semantic_group_prepare_request_changed", "Resume only the exact saved plan, original data, and project generation.")
    root = store.claim_native_workspace(command.key, command.command_digest, MANAGED_GROUP_PREPARE)
    with exclusive_directory_lease(root) as lease:
        yield GroupPreparation(store, root, command, figures)
        lease.verify()
