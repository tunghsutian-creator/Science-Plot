"""Reserve a new Managed project's root without giving it an external write grant."""

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.delivery.install import install_new_delivery
from sciplot_core.foundation.json_io import atomic_write_json, read_json_object
from sciplot_core.foundation.research_destination import require_data_destination
from sciplot_core.foundation.project_session_lease import external_project_session
from sciplot_core.project_store.errors import ProjectRecoveryRequired
from sciplot_core.project_store.io import STORE
from sciplot_core.project_store.repository import FileProjectStore

from .errors import EngineError
from .paths import canonical_path
from .repository import digest

MANAGED_STORE_CLAIM = "managed-store-claim.json"


def managed_publication_target(root: Path, output: Path, sources: list[dict[str, Any]]) -> Path:
    """Admit the resolved expert destination separately from the canonical Store claim."""
    output = canonical_path(output)
    require_data_destination(output)
    originals = [canonical_path(Path(source["path"])) for source in sources]
    if any(output.is_relative_to(path) or path.is_relative_to(output) for path in [root, *originals]):
        raise EngineError("managed_output_conflict", "The visible output cannot overlap the Managed store or an original source.")
    if output.exists() and (not output.is_dir() or
            not (root / MANAGED_STORE_CLAIM).is_file() and any(output.iterdir())):
        raise EngineError("managed_output_conflict", "The selected output directory already contains files.")
    return output


def open_managed_store(root: Path, request: dict[str, Any], *,
                       authorize_new: Callable[[], None] | None = None) -> FileProjectStore:
    """Recover one exact root claim through the existing Store writer.

    Authorization precedes a fresh claim; the existing journal retains
    completed or uncertain execution facts without re-admitting the command.
    """
    require_data_destination(root)
    for source in request["data_binding"]["data_sources"]:
        path = canonical_path(Path(source["path"]))
        if path == root or path.is_relative_to(root) or root.is_relative_to(path):
            raise EngineError("managed_output_conflict", "The Managed store cannot overlap an original source.")
    claim = {"kind": "sciplot_managed_store_claim", "version": 1, "request_sha256": digest(request)}
    return open_claimed_store(root, claim, authorize_new=authorize_new)


def open_claimed_store(root: Path, claim: dict[str, Any], *,
                       authorize_new: Callable[[], None] | None = None) -> FileProjectStore:
    """Create or resume this exact first-Store claim, never adopt an unrelated root."""
    require_data_destination(root)
    admitted = authorize_new is None
    if authorize_new is not None and not root.exists():
        authorize_new()
        admitted = True
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with external_project_session(root):
        canonical_path(root)
        if not root.exists():
            if not admitted and authorize_new is not None:
                authorize_new()
            with TemporaryDirectory(prefix=".managed-store-", dir=root.parent) as directory:
                candidate = Path(directory) / "project"
                candidate.mkdir(mode=0o700)
                atomic_write_json(candidate / MANAGED_STORE_CLAIM, claim)
                install_new_delivery(candidate, root)
        if not root.is_dir() or read_json_object(canonical_path(root / MANAGED_STORE_CLAIM)) != claim:
            raise EngineError("document_idempotency_conflict", "This Store creation key belongs to a different or unowned request.")
        store_path = canonical_path(root / STORE)
        initialize = not canonical_path(store_path / "head.json").is_file()
        if initialize and any(item.name not in {MANAGED_STORE_CLAIM, STORE} for item in root.iterdir()):
            raise EngineError("document_state_changed", "The uninitialized Managed store contains unowned files.")
    # Store operations acquire this same non-reentrant external lease. The
    # physical root claim is sealed before handing off to that writer.
    store = FileProjectStore(root)
    try:
        store.snapshot(import_legacy=initialize)
    except ProjectRecoveryRequired:
        if store.recover()["phase"] != "complete":
            raise EngineError("document_state_changed", "The Managed Store has a command with an unknown outcome.") from None
    observed = store.observe_members((MANAGED_STORE_CLAIM,), projection=False, physical=(MANAGED_STORE_CLAIM,))
    stored_claim = observed.members[MANAGED_STORE_CLAIM].data
    physical_claim = observed.physical[MANAGED_STORE_CLAIM]
    if stored_claim is None or physical_claim is None or stored_claim != physical_claim[0]:
        raise EngineError("document_state_changed", "The Managed Store root claim differs from its recorded bytes.")
    return store
