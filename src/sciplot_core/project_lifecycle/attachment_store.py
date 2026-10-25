"""Host-created backup read capability for one already validated directory transfer."""
from pathlib import Path

from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.resources import ResourceRoot


def with_backup(store: FileProjectStore, identity: str, backup: Path) -> FileProjectStore:
    capabilities = {key: ResourceRoot(path, store.location_members[key]) for key, path in store.locations.items()}
    return FileProjectStore(store.root, locations=capabilities,
        namespace_backups={**store.namespace_backups, identity: backup})
