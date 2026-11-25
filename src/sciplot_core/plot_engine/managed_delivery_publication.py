"""Publish one sealed set through the existing exclusive directory installer."""

import json
from collections.abc import Callable
from pathlib import Path
import subprocess
import sys
from typing import Any
from uuid import uuid4
import zipfile

from sciplot_core.delivery import native_snapshot
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.storage import digest
from sciplot_core.studio_core.source_update_files import file_inventory
from sciplot_core.veusz_runtime import veusz_worker_environment


def inspect_managed_native(binding: dict[str, Any]) -> dict[str, Any]:
    """Fresh existing compiler audit without its rebuild-on-runtime-change path."""
    result = subprocess.run([sys.executable, "-m", "sciplot_core.veusz_worker", "inspect-plot-ir",
                             binding["ir_path"], binding["document"]],
                            env=veusz_worker_environment(), capture_output=True, text=True,
                            timeout=120, check=False)
    if result.returncode:
        raise EngineError("managed_delivery_native_audit_failed", result.stderr[-2000:])
    payload = json.loads(result.stdout)
    if (payload.get("status") != "unchanged" or payload.get("ir_hash") != binding["ir_hash"]
            or payload.get("scientific_audit", {}).get("status") != "passed"):
        raise EngineError("managed_delivery_native_audit_failed", "The exact saved native state failed its existing PlotIR scientific audit.")
    return dict(payload)


def publish(root: Path, state: dict[str, Any], *, checkpoint: Callable[[], None], validate: Callable[[], None]) -> dict[str, str]:
    out = Path(state["request"]["out"])
    candidate = root / "candidates" / uuid4().hex
    candidate.mkdir(parents=True)
    for directory in ("project", "pdf", "tiff", "data/originals", "data/imports"):
        (candidate / directory).mkdir(parents=True, exist_ok=True)
    entries = []
    assembled: dict[str, str] = {}
    for index, (selection, item) in enumerate(zip(state["request"]["items"], state["items"], strict=True), 1):
        layout = {name: name for name in item["files"] if Path(name).parts[0] in ("project", "pdf", "tiff", "data")}
        stem = item["stem"]
        try:
            native_snapshot.stage_native(Path(item["attempt"]), candidate, item["files"],
                                         layout=layout, assembled=assembled, stem=stem, portable=item["portable"])
        except native_snapshot.SnapshotSealChanged as exc:
            raise EngineError("managed_delivery_staging_changed", str(exc)) from exc
        except native_snapshot.NativeSnapshotError as exc:
            raise EngineError("managed_delivery_reopen_failed", str(exc)) from exc
        entries.append({"id": stem, "order": index, "label": selection["label"],
                        "mode": "native_snapshot", "managed_project_included": False,
                        "local_managed_continuation": {key: selection[key] for key in ("plot", "plot_id", "revision")},
                        "scientific_hash": item["scientific_hash"], "presentation_hash": item["presentation_hash"],
                        "export_configuration": item["export_configuration"], "audit": item["audit"],
                        "sources": item["sources"], "plotted_data": item["plotted_data"], "native_state_sha256": item["portable"]["native_state_sha256"],
                        "files": {"editable": f"project/{stem}.vsz", "pdf": f"pdf/{stem}.pdf",
                                  "tiff_300": f"tiff/{stem}_300dpi.tiff"}})
    manifest = {"kind": "sciplot_managed_delivery", "version": 1, "title": state["request"]["title"],
                "mode": "native_snapshot", "managed_project_included": False, "items": entries,
                "continuation": "Local ManagedPlot paths are provenance, not portable registry bindings. Continue changes through the current original ManagedPlot AI commands; these independent native snapshots never update the originals.",
                "publication_qa": "Each original ManagedPlot passed its existing export owner; native Save preserved its complete state.",
                "journal_acceptance_evaluated": False}
    (candidate / "README.txt").write_text(
        "Independent native snapshots / 独立原生快照\n"
        "This package contains independent native snapshots. Continue canonical changes through the original ManagedPlot AI commands; snapshots do not update originals.\n"
        "Original source bytes are retained under data/originals. Exact sealed PlotIR and per-dataset CSVs are under data/plotted. CSVs retain each dataset length and round-trip numeric values; roles/units/provenance remain in the IR and index.json.\n"
        "This is not a portable ManagedPlot project. Local continuation paths only work while their original bindings remain current.\n"
        "Figures.zip contains this frozen delivery; later package changes are not included.\n", encoding="utf-8")
    manifest["snapshot_files"] = file_inventory(candidate)
    manifest["manifest_sha256"] = digest(manifest)
    (candidate / "index.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # The archive belongs to the same exclusively installed directory, avoiding
    # a second publication destination with an unrelated overwrite policy.
    inventory = file_inventory(candidate)
    with zipfile.ZipFile(candidate / "Figures.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(inventory):
            archive.write(candidate / name, name)

    def freeze(files: dict[str, str]) -> None:
        state["publication_candidate"] = {"path": str(candidate), "files": files}
        checkpoint()

    try:
        return native_snapshot.publish_snapshot(candidate, out, assembled=assembled, freeze=freeze, validate=validate)
    except native_snapshot.SnapshotSealChanged as exc:
        raise EngineError("managed_delivery_staging_changed", str(exc)) from exc
