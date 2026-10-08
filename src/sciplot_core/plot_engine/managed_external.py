"""Observe managed native drift without adopting it or publishing a new revision."""

from pathlib import Path
from typing import Any, Protocol

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_backends.managed import compiler_identity
from sciplot_core.plot_document import DocumentError, apply_patch

from .errors import EngineError
from .external_mutation import record_external_mutation, semantic_delta_sha256
from .managed_state import read_canonical, require_inputs, resolved_ir
from .storage import read


class NativeInspector(Protocol):
    def inspect_ir(self, ir: dict[str, Any], document: Path) -> dict[str, Any]: ...


def inspect_managed_mutation(root: Path, binding: dict[str, Any], compiler: NativeInspector) -> dict[str, Any]:
    """A matching complete candidate state is required even for a known style diff."""
    document = read_canonical(binding)
    require_inputs(document)
    original = resolved_ir(root, document)
    if original["ir_hash"] != binding["ir_hash"]:
        raise EngineError("managed_ir_conflict", "The canonical document does not reproduce this artifact's bound IR.")
    native = Path(binding["document"])
    marker = native.parent / "build.json"
    if not marker.is_file():
        raise EngineError("managed_external_mutation_untracked", "An existing managed native file lacks its original build receipt.",
                          action="inspect_external_mutation")
    build = read(marker)
    if build.get("ir_hash") != original["ir_hash"] or not isinstance(build.get("document_sha256"), str):
        raise EngineError("managed_external_mutation_untracked", "The original build receipt does not identify this managed artifact.",
                          action="inspect_external_mutation")
    before, after = build["document_sha256"], file_sha256(native)
    observed = compiler.inspect_ir(original, native)
    if observed.get("document_sha256") != after or file_sha256(native) != after:
        raise EngineError("external_mutation_observation_changed", "The managed native document changed during its inspection.")
    differences = observed["semantic_diff"]
    identity = compiler_identity()
    proof = None
    baseline_matches = (observed.get("expected_native_state_hash") == build.get("native_state_hash")
                        and build.get("compiler_identity") == identity)
    if baseline_matches and observed.get("scientific_audit", {}).get("status") == "passed":
        candidate = document
        valid = True
        if differences:
            try:
                for item in differences:
                    if document["presentation"]["objects"][item["target"]]["properties"][item["property"]] != item["before"]:
                        raise ValueError("Semantic observation does not match canonical before value")
                candidate, _diff, _risk = apply_patch(document, {
                    "plot_id": document["plot_id"], "base_revision": document["revision"],
                    "idempotency_key": "observe-external-mutation", "intent_class": "presentation",
                    "changes": [{"op": "set", "target": [item["target"]], "property": item["property"],
                                 "value": item["after"]} for item in differences]})
            except (DocumentError, ValueError, KeyError, TypeError):
                valid = False
        if valid:
            # inspect_ir constructs the full expected native state from candidate IR.
            # It never modifies the observed VSZ or canonical revision.
            comparison = compiler.inspect_ir(resolved_ir(root, candidate), native) if differences else observed
            if comparison.get("document_sha256") != after:
                raise EngineError("external_mutation_observation_changed", "The managed native document changed before candidate comparison.")
            if comparison.get("scientific_audit", {}).get("status") == "passed":
                proof = {"method": "canonical_native_state", "coverage": "complete_native_state",
                         "backend_identity": identity["content_hash"], "base_native_sha256": before,
                         "observed_native_sha256": after, "expected_native_sha256": None,
                         "observed_state_sha256": comparison["native_state_hash"],
                         "expected_state_sha256": comparison["expected_native_state_hash"],
                         "semantic_delta_sha256": semantic_delta_sha256(document["revision"], differences)}
    require_inputs(document)
    if file_sha256(native) != after:
        raise EngineError("external_mutation_observation_changed", "The managed native document changed before its record was sealed.")
    return record_external_mutation(plot_id=document["plot_id"], base_revision=document["revision"],
        authority="ManagedPlot", backend="veusz", before_native_sha256=before, after_native_sha256=after,
        represented_diff=differences, equivalence=proof)
