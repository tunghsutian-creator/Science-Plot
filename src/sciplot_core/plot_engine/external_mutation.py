"""Sealed external native changes, with explicit authority and complete-state proof.

Only backend owners produce equivalence evidence. A semantic diff on its own says
nothing about unrepresented native content and must never promote native state to
managed document authority.
"""

from copy import deepcopy
import hashlib
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_document.schema import DIGEST, IDENTIFIER, closed
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.studio_core.project_query_paths import canonical_path

from .errors import EngineError

_MODES = ["LegacyPlot", "ManagedPlot"]


def authority_status(mode: str) -> dict[str, Any]:
    if mode not in _MODES:
        raise EngineError("plot_authority_invalid", "Use an explicit LegacyPlot or ManagedPlot authority.")
    return {"mode": mode,
            "source_of_truth": "saved_native_document" if mode == "LegacyPlot" else "sciplot_document",
            "rebuild_from_document": mode == "ManagedPlot",
            "unknown_external_change": "preserve_with_explicit_review" if mode == "LegacyPlot" else "reject_or_explicit_downgrade"}


def _digest(value: Any) -> str:
    return canonical_json_sha256(value, allow_nan=False)


def semantic_delta_sha256(base_revision: int, represented_diff: list[dict[str, Any]]) -> str:
    """Bind backend comparison evidence to this exact base and represented delta."""
    return _digest({"base_revision": base_revision, "represented_diff": represented_diff})


def equivalence_schema() -> dict[str, Any]:
    return closed({
        "method": {"enum": ["exact_native_bytes", "canonical_native_state", "closed_saved_transcript"]},
        "coverage": {"const": "complete_native_state"},
        "backend_identity": DIGEST,
        "base_native_sha256": DIGEST,
        "observed_native_sha256": DIGEST,
        "expected_native_sha256": {"oneOf": [DIGEST, {"type": "null"}]},
        "observed_state_sha256": DIGEST,
        "expected_state_sha256": DIGEST,
        "semantic_delta_sha256": DIGEST,
    })


def external_mutation_schema() -> dict[str, Any]:
    return closed({
        "kind": {"const": "sciplot_external_mutation"}, "schema_version": {"const": 1},
        "mutation_id": DIGEST, "plot_id": IDENTIFIER,
        "base_revision": {"type": "integer", "minimum": 0},
        "authority": {"enum": _MODES}, "backend": {"type": "string", "minLength": 1},
        "before_native_sha256": DIGEST, "after_native_sha256": DIGEST,
        "classification": {"enum": ["known_semantic_delta", "opaque_native_change"]},
        "represented_diff": {"type": "array", "items": closed({
            "target": IDENTIFIER, "property": {"type": "string", "minLength": 1},
            "before": {}, "after": {},
        })},
        "equivalence": {"oneOf": [{"type": "null"}, equivalence_schema()]},
    })


def exact_native_equivalence(*, backend_identity: str, before_native_sha256: str,
                             observed_native_sha256: str, expected_native_sha256: str,
                             base_revision: int, represented_diff: list[dict[str, Any]]) -> dict[str, Any]:
    """The strongest proof: every compiled native byte equals the observed file."""
    proof = {"method": "exact_native_bytes", "coverage": "complete_native_state",
             "backend_identity": backend_identity, "base_native_sha256": before_native_sha256,
             "observed_native_sha256": observed_native_sha256, "expected_native_sha256": expected_native_sha256,
             "observed_state_sha256": observed_native_sha256, "expected_state_sha256": expected_native_sha256,
             "semantic_delta_sha256": semantic_delta_sha256(base_revision, represented_diff)}
    validate_wire(proof, equivalence_schema(), code="external_mutation_invalid_equivalence")
    return proof


def _classification(record: dict[str, Any]) -> str:
    proof = record["equivalence"]
    if proof is None:
        return "opaque_native_change"
    if (proof["base_native_sha256"] != record["before_native_sha256"]
            or proof["observed_native_sha256"] != record["after_native_sha256"]
            or proof["semantic_delta_sha256"] != semantic_delta_sha256(record["base_revision"], record["represented_diff"])):
        raise EngineError("external_mutation_equivalence_mismatch", "The native comparison does not identify this frozen external change.")
    if proof["method"] == "exact_native_bytes" and (
            proof["observed_state_sha256"] != proof["observed_native_sha256"]
            or proof["expected_state_sha256"] != proof["expected_native_sha256"]):
        raise EngineError("external_mutation_equivalence_mismatch", "Exact native comparison must cover the original complete bytes.")
    return ("known_semantic_delta" if proof["observed_state_sha256"] == proof["expected_state_sha256"]
            else "opaque_native_change")


def validate_external_mutation(value: Any) -> dict[str, Any]:
    validate_wire(value, external_mutation_schema(), code="external_mutation_invalid")
    assert isinstance(value, dict)
    result = deepcopy(value)
    if result["before_native_sha256"] == result["after_native_sha256"]:
        raise EngineError("external_mutation_unchanged", "Unchanged native bytes are not an external mutation.")
    expected = _digest({key: item for key, item in result.items() if key != "mutation_id"})
    if result["mutation_id"] != expected or result["classification"] != _classification(result):
        raise EngineError("external_mutation_record_changed", "The external mutation record or its classification changed.")
    return result


def record_external_mutation(*, plot_id: str, base_revision: int, authority: str, backend: str,
                             before_native_sha256: str, after_native_sha256: str,
                             represented_diff: list[dict[str, Any]],
                             equivalence: dict[str, Any] | None = None) -> dict[str, Any]:
    record = {"kind": "sciplot_external_mutation", "schema_version": 1, "mutation_id": "0" * 64,
              "plot_id": plot_id, "base_revision": base_revision, "authority": authority, "backend": backend,
              "before_native_sha256": before_native_sha256, "after_native_sha256": after_native_sha256,
              "represented_diff": deepcopy(represented_diff), "equivalence": deepcopy(equivalence),
              "classification": "opaque_native_change"}
    validate_wire(record, external_mutation_schema(), code="external_mutation_invalid")
    record["classification"] = _classification(record)
    record["mutation_id"] = _digest({key: value for key, value in record.items() if key != "mutation_id"})
    return validate_external_mutation(record)


def require_managed_representability(record: dict[str, Any]) -> dict[str, Any]:
    result = validate_external_mutation(record)
    if result["authority"] != "ManagedPlot":
        raise EngineError("external_mutation_authority_mismatch", "Managed adoption requires explicit document authority.")
    if result["classification"] != "known_semantic_delta":
        raise EngineError("managed_external_mutation_opaque",
                          "The saved native change is not completely represented by the canonical document.",
                          action="reject_or_explicit_downgrade", mutation_id=result["mutation_id"],
                          represented_diff_count=len(result["represented_diff"]))
    return result


def capture_baseline(root: Path, binding: dict[str, Any]) -> dict[str, Any]:
    """Keep exact legacy authority outside project inventory before external saves."""
    source = canonical_path(Path(binding["document"]))
    expected = binding["fingerprint"]["files"][str(source)]
    raw = source.read_bytes()
    observed = hashlib.sha256(raw).hexdigest()
    if observed != expected or file_sha256(source) != expected:
        raise EngineError("external_mutation_baseline_changed", "The saved native document changed while capturing its immutable baseline.")
    target = canonical_path(root / "native-baselines" / f"{expected}.vsz")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if file_sha256(target) != expected:
            raise EngineError("external_mutation_baseline_corrupt", "The immutable native baseline no longer matches its recorded bytes.")
    else:
        temporary = target.with_name(target.name + "." + uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, target)
        except FileExistsError:
            if not target.is_file() or file_sha256(target) != expected:
                raise EngineError("external_mutation_baseline_corrupt", "A different native baseline occupies the content address.") from None
        finally:
            temporary.unlink(missing_ok=True)
        descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    if file_sha256(source) != expected:
        raise EngineError("external_mutation_baseline_changed", "The saved native document changed before its baseline could be bound.")
    result = deepcopy(binding)
    result["native_baseline"] = {"path": str(target), "sha256": expected}
    return result


def record_legacy_mutation(root: Path, head: dict[str, Any], binding: dict[str, Any],
                           represented_diff: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify only what an exact pre-change legacy baseline can prove."""
    old = head["binding"]
    native = binding["document"]
    before, after = old["fingerprint"]["files"][native], binding["fingerprint"]["files"][native]
    proof = None
    reference = old.get("native_baseline")
    if reference is not None:
        baseline = canonical_path(Path(reference["path"]))
        expected_path = canonical_path(root / "native-baselines" / f"{before}.vsz")
        if baseline != expected_path or reference["sha256"] != before or not baseline.is_file():
            raise EngineError("external_mutation_baseline_corrupt", "The frozen native baseline no longer identifies this revision.")
        baseline_raw = baseline.read_bytes()
        if hashlib.sha256(baseline_raw).hexdigest() != before or file_sha256(baseline) != before:
            raise EngineError("external_mutation_baseline_corrupt", "The frozen native baseline bytes changed.")
        observed = canonical_path(Path(native)).read_bytes()
        if hashlib.sha256(observed).hexdigest() != after or file_sha256(Path(native)) != after:
            raise EngineError("external_mutation_observation_changed", "The external native document changed during comparison.")
        changes = []
        for item in represented_diff:
            setting = old["targets"][item["target"]]["properties"][item["property"]]
            if setting["kind"] != "setting":
                break
            changes.append({"setting_path": setting["setting_path"], "before": item["before"], "after": item["after"]})
        else:
            from sciplot_core.plot_backends.veusz_external_mutation import compare_setting_transcript

            compared = compare_setting_transcript(baseline_raw, observed, changes)
            if compared is not None:
                proof = {**compared, "base_native_sha256": before, "observed_native_sha256": after,
                         "semantic_delta_sha256": semantic_delta_sha256(head["document"]["revision"], represented_diff)}
    return record_external_mutation(plot_id=head["document"]["plot_id"], base_revision=head["document"]["revision"],
        authority="LegacyPlot", backend="veusz", before_native_sha256=before, after_native_sha256=after,
        represented_diff=represented_diff, equivalence=proof)
