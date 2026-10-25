"""Find a sealed revision's source generation through the verified ancestor chain."""
from sciplot_core.project_store import state
from sciplot_core.project_store.io import digest
from sciplot_core.project_store.repository import FileProjectStore
from .errors import EngineError


def introduced_generation(store: FileProjectStore, logical: str) -> str:
    with store._locked() as (io, current):
        expected = current["files"].get(logical)
        if expected is None:
            raise EngineError("document_state_missing", "The historical semantic revision is not in this project generation.")
        chosen, value = current["generation"], current
        seen = set()
        while value["generation"] not in seen:
            seen.add(value["generation"])
            if value["files"].get(logical) != expected:
                return str(chosen)
            chosen = value["generation"]
            if value["parent"] is None:
                return str(chosen)
            parent = state.generation(io, value["parent"])
            if digest(parent) != value["parent_sha256"] or parent["project_id"] != current["project_id"]:
                raise EngineError("semantic_attachment_history_invalid", "The historical source generation ancestor proof changed.")
            value = parent
    raise EngineError("semantic_attachment_history_invalid", "The historical source generation contains a cycle.")
