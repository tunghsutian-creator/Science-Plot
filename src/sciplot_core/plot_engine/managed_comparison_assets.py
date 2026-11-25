"""Adopt the exact native/preview bytes already reviewed for a Managed comparison."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.delivery.install import install_new_delivery
from sciplot_core.delivery.native_snapshot import SnapshotSealChanged, copy_sealed_file
from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.plot_backends.managed import compiler_identity
from sciplot_core.project_lifecycle.context import exists, read, write
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot

from .errors import EngineError


def _changed() -> EngineError:
    return EngineError("comparison_candidate_changed", "The exact reviewed native candidate or preview is unavailable. Reopen the comparison before selecting again.",
                       action="restart_comparison")


def adopt(binding: dict[str, Any], ir: dict[str, Any], output: Path,
          selected: dict[str, Any]) -> dict[str, Any]:
    evidence = selected["assets"]
    folder = canonical_path(Path(evidence["directory"]))
    preview = evidence["preview"]
    preview_name = Path(preview["path"]).name
    ir_name = f"plot-ir-{selected['ir_hash']}.json"
    checks = evidence["files"]
    if (set(checks) != {"document.vsz", ir_name, preview_name} or Path(preview["path"]).parent != folder
            or checks[preview_name] != preview["sha256"] or selected["ir_hash"] != ir["ir_hash"]
            or evidence["scientific_audit"].get("status") != "passed"):
        raise _changed()
    renderer = compiler_identity()
    if renderer != selected["compiler_identity"]:
        raise EngineError("comparison_compiler_changed", "Restore the renderer that produced the selected review before committing.")
    try:
        observed = stable_file_snapshot(canonical_path(folder / ir_name), label="Reviewed comparison PlotIR",
                                        expected_sha256=checks[ir_name])
        if json.loads(observed["bytes"]) != ir:
            raise _changed()
        native = canonical_path(Path(binding["document"]))
        marker, intent_path = native.parent / "build.json", native.parent / "compile-intent.json"
        intent = {"ir_hash": ir["ir_hash"], "canonical_sha256": binding["canonical_sha256"],
                  "compiler_identity": renderer, "compile_id": selected["operation_id"]}
        state = {"ir_hash": ir["ir_hash"], "compiler_identity": renderer,
                 "native_state_hash": selected["native_state_hash"], "document_sha256": checks["document.vsz"]}
        previous = read(marker) if exists(marker) else None
        if native.exists():
            if (existing_file_sha256(native) != checks["document.vsz"]
                    or previous is not None and any(previous.get(key) != value for key, value in state.items())
                    or previous is None and (not exists(intent_path) or read(intent_path) != intent)):
                raise _changed()
        else:
            if previous is not None:
                raise _changed()
            write(intent_path, intent)
            with TemporaryDirectory(prefix=".adopting-comparison-", dir=native.parent) as staging:
                candidate = Path(staging) / native.name
                copy_sealed_file(canonical_path(folder / "document.vsz"), candidate, checks["document.vsz"])
                install_new_delivery(candidate, native)
        output.mkdir(parents=True, exist_ok=True)
        image = output / "preview.png"
        copy_sealed_file(canonical_path(folder / preview_name), image, checks[preview_name])
        if (existing_file_sha256(native) != checks["document.vsz"] or compiler_identity() != renderer):
            raise _changed()
        if previous is None:
            write(marker, {**state, "compile_id": intent["compile_id"]})
    except (OSError, SnapshotSealChanged) as exc:
        raise _changed() from exc
    return {"scientific_audit": evidence["scientific_audit"], "preview": {**preview, "path": str(image)},
            "_managed_binding": binding, "native_state_hash": selected["native_state_hash"], "compiler_identity": renderer,
            "_selected_native_sha256": checks["document.vsz"]}
