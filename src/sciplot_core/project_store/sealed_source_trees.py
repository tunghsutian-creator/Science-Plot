"""An exact decision's complete tree selects live origins or an imported view."""
from collections.abc import Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from typing import Any

from sciplot_core.project_commands.resources import SourceTreeRead
from .errors import ProjectConflict, ProjectStoreError
from .io import directory, read_file, sha
from .repository import FileProjectStore


@dataclass(frozen=True)
class SealedSourceTree:
    command_id: str
    command_digest: str
    decision_id: str
    tree: SourceTreeRead

    def __post_init__(self) -> None:
        if (not isinstance(self.command_id, str) or not 1 <= len(self.command_id) <= 4096
                or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
                       for value in (self.command_digest, self.decision_id))
                or not isinstance(self.tree, SourceTreeRead) or len(self.tree.locator) > 8192):
            raise ProjectStoreError("A sealed source tree requires its exact command, decision and typed complete tree witness.")
        self.tree.__post_init__()

    def to_payload(self) -> dict[str, Any]:
        self.__post_init__()
        return {"command_id": self.command_id, "command_digest": self.command_digest,
                "decision_id": self.decision_id, "tree": self.tree.to_payload()}

    @classmethod
    def from_payload(cls, value: Any) -> "SealedSourceTree":
        if (not isinstance(value, dict) or set(value) != {"command_id", "command_digest", "decision_id", "tree"}
                or not isinstance(value["tree"], dict) or set(value["tree"]) != {"locator", "tree_sha256"}):
            raise ProjectStoreError("Invalid closed complete source-tree witness.")
        tree = SourceTreeRead(value["tree"]["locator"], value["tree"]["tree_sha256"])
        return cls(value["command_id"], value["command_digest"], value["decision_id"], tree)

    def view(self, store: FileProjectStore) -> Path:
        actual = store.prepared_tree_path(self.command_id, self.command_digest, decision_id=self.decision_id,
                                         locator=self.tree.locator, tree_sha256=self.tree.tree_sha256)
        if actual is None:
            raise ProjectConflict("A sealed tree scope requires an explicit complete imported read-only view.")
        return actual

    def live(self, store: FileProjectStore, *, generation: str | None = None) -> Path:
        """Verify the committed author's complete original census, never a cache."""
        from . import source_trees, state
        from .committed_outcomes import require as committed_outcome
        from .root_bindings import require as require_roots

        with store._locked() as (io, current):
            value = state.reachable(io, current, generation) if generation else current
            require_roots(io, current)
            record = state.command(io, self.command_id, self.command_digest)
            if (record is None or record.get("phase") != "complete"
                    or record.get("decision_id") != self.decision_id
                    or record.get("metadata", {}).get("source_trees", []).count(self.tree.to_payload()) != 1
                    or committed_outcome(io, value, record) is None):
                raise ProjectConflict("A live source tree requires its exact committed author and decision.")
            source_trees.require(io, value, record, _live=True)
            return Path(record["source_tree_origins"][self.tree.locator]["actual"])


def _member(path: Path, view: Path, expected_sha256: str | None, *, sealed: bool) -> None:
    relative = path.relative_to(view)
    if ".." in relative.parts:
        raise ProjectConflict("A sealed tree member cannot escape its exact complete view.")
    root = os.open(view, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with directory(root, relative.parts[:-1]) as parent:
            info = os.stat(relative.name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                if expected_sha256 is not None:
                    raise ProjectConflict("A subtree requires its own exact composite witness.")
            elif stat.S_ISREG(info.st_mode):
                data = read_file(parent, relative.name, owned=sealed)[0]
                if expected_sha256 is not None and sha(data) != expected_sha256:
                    raise ProjectConflict("A complete tree member differs from its explicit file hash.")
            else:
                raise ProjectConflict("A sealed tree cannot resolve a symbolic or special member.")
    finally:
        os.close(root)


def resolve_tree_view(store: FileProjectStore, trees: Sequence[SealedSourceTree], original: str | Path, *,
                      expected_sha256: str | None = None, sealed: bool = True,
                      generation: str | None = None) -> tuple[Path, str, bool] | None:
    """Map exact declared roots, or members of their verified local views only."""
    path = Path(original)
    for item in trees:
        if str(original) == item.tree.locator:
            if expected_sha256 is not None and expected_sha256 != item.tree.tree_sha256:
                raise ProjectConflict("The source directory requires its exact composite tree hash.")
            return (item.view(store) if sealed else item.live(store, generation=generation)), item.tree.locator, True
    for item in trees:
        # Revalidate the selected complete membership, bytes, mode and inode.
        view = item.view(store) if sealed else item.live(store, generation=generation)
        if path == view:
            if expected_sha256 is not None and expected_sha256 != item.tree.tree_sha256:
                raise ProjectConflict("The sealed root requires its exact composite tree hash.")
            return view, item.tree.locator, True
        if path.is_relative_to(view):
            _member(path, view, expected_sha256, sealed=sealed)
            return path, str(Path(item.tree.locator) / path.relative_to(view)), False
    return None
