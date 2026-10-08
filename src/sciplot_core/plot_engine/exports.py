"""Current-revision rendering and publication cache without reapplying semantics."""

from pathlib import Path
from typing import Any
from uuid import uuid4

from .backend import PlotBackend
from .cache_identity import build_key
from .current import artifact_files, evidence_current, require_current
from .execution import advance
from .storage import active, digest, persist, read, reserve, write
from .errors import EngineError


def render_head(root: Path, head: dict[str, Any], backend: PlotBackend) -> dict[str, Any]:
    document, binding = head["document"], head["binding"]
    key = build_key(document, binding)
    cache_path = root / "render-cache.json"
    if cache_path.exists():
        cache = read(cache_path)
        if cache["build_key"] == key and evidence_current(cache["artifact_files"]):
            return {**cache["result"], "cache_hit": True}
    output = backend.render(binding, root / "renders" / uuid4().hex)
    require_current(backend, binding)
    result = {"kind": "sciplot_plot_render", "status": "rendered", "plot": str(root),
              "revision": document["revision"], "preview": output.get("preview"), "cache_hit": False}
    if "publication_qa" in output:
        result["publication_qa"] = output["publication_qa"]
    write(cache_path, {"build_key": key, "artifact_files": artifact_files(output), "result": result})
    return result


def export_head(root: Path, head: dict[str, Any], backend: PlotBackend) -> dict[str, Any]:
    pending = active(root)
    if pending and pending["phase"] not in {"complete", "rejected"}:
        if pending["phase"] in {"committed", "exporting", "export_pending"}:
            from .execution import replay

            return replay(root, pending, backend)
        raise EngineError("document_transaction_pending", "Finish or reject the existing transaction before exporting this managed plot.")
    document = head["document"]
    key = "export:" + digest([document["revision"], head["binding"]["fingerprint"]])
    from .storage import transaction_path

    path = transaction_path(root, key)
    if path.exists():
        from .execution import replay

        return replay(root, read(path), backend)
    request = {"idempotency_key": key, "base_revision": document["revision"], "action": "export"}
    tx = {"id": digest(key), "request": request, "request_hash": digest(request), "document": document,
          "before": document, "binding": head["binding"], "diff": [], "risk": "presentation", "phase": "committed"}
    reserve(root, tx)
    persist(root, tx)
    return advance(root, tx, backend)
