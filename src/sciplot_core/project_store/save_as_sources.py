"""Bind only the exact staged Save As source copies for independent local reads."""

from sciplot_core.project_commands import ProjectCommand
from . import state
from .errors import ProjectConflict
from .repository import FileProjectStore

SAVE_AS_ADAPTER = "managed_save_as_v1"
FILE_SAVE_AS_ADAPTER = "project_file_save_as_v1"


def bind_staged_source_copies(store: FileProjectStore, command: ProjectCommand) -> None:
    """Install local source provenance before accepting the matching new head.

    The copied bytes are already sealed by the normal prepared Store command.
    This is only the host locator binding; source IDs, versions and bytes still
    enter the new Store's canonical generation through the existing publisher.
    """
    adapter = command.to_payload()["request"].get("adapter")
    with store._locked(allow_pending=True, writer=True) as (io, current):
        record = state.command(io, command.key, command.command_digest)
        if (record is None or record["phase"] not in {"needs_review", "accepted"}
                or record.get("metadata") != command.to_payload()
                or adapter not in {SAVE_AS_ADAPTER, FILE_SAVE_AS_ADAPTER}
                or record["metadata"]["request"].get("save_as", {}).get("destination") != str(store.root)
                or record["project_id"] != current["project_id"]
                or record["generation"] != current["generation"]):
            raise ProjectConflict("Only the exact prepared Save As can bind its local source copies.")
        frozen = state.sealed_draft(io, record)
        record_sources = frozen.get("sources")
        if (not isinstance(record_sources, dict) or not record_sources
                or current["sources"] or current["commands"]
                or adapter == FILE_SAVE_AS_ADAPTER and current["files"]):
            raise ProjectConflict("Save As source copies belong only to this new empty project.")
        versions = {}
        for identity, entries in record_sources.items():
            if adapter == SAVE_AS_ADAPTER and len(entries) != 1:
                raise ProjectConflict("Save As includes one selected version per source.")
            if not entries:
                raise ProjectConflict("Each copied original needs at least one sealed version.")
            versions[identity] = {}
            for version, entry in entries.items():
                if entry["source_id"] != identity or entry["sha256"] != version:
                    raise ProjectConflict("A Save As source lost its exact version identity.")
                io.get(entry)
                versions[identity][version] = entry["sha256"]
        binding = {"versions": versions}
        prior = io.read("local_sources.json")
        if prior is not None and prior != binding:
            raise ProjectConflict("The new project already has another local source binding.")
        if prior is None:
            io.write("local_sources.json", binding)
