"""Single external execution/admission authority over host-owned grants."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, TYPE_CHECKING

from .context import dataset_sources, host_registry
from .models import SourceScope, denied

if TYPE_CHECKING:
    from sciplot_core.plot_transforms.external_descriptor import ExternalExecutor


def _registered(identifier: str, identity: dict[str, Any], sources: tuple[SourceScope, ...]) -> dict[str, Any]:
    from sciplot_core.plot_transforms.external_descriptor import ExternalExecutor

    registration = host_registry().require(identifier, identity, sources)
    executor = ExternalExecutor.from_dict(registration)
    if executor.descriptor(identifier) != identity:
        denied("host_executor_changed", "The host-registered executor no longer matches this scientific identity.")
    return registration


def authorize_external(node: dict[str, Any], source: dict[str, Any], registry: dict[str, ExternalExecutor]) -> ExternalExecutor:
    from sciplot_core.plot_transforms.external_descriptor import ExternalExecutor

    identifier = node["executor"]["id"]
    if identifier not in registry:
        denied("host_executor_ungranted", "An external execution declaration is missing; declarations never grant host rights.")
    registration = _registered(identifier, node["executor"], dataset_sources(source))
    declared = registry[identifier]
    if declared.to_dict(identifier) != registration:
        denied("host_executor_registration_mismatch", "The saved/request executor differs from its explicit host registration.")
    return ExternalExecutor.from_dict(registration)


def _source_lineage(document: dict[str, Any]) -> dict[str, set[str]]:
    from sciplot_core.plot_transforms.schema import ordered_nodes

    source_ids = [item["source_id"] for item in document["scientific"]["data_sources"]]
    lineage = {name: {name} for name in source_ids}
    for node in ordered_nodes(document["scientific"]["transforms"], source_ids):
        lineage[node["output"]] = set().union(*(lineage[name] for name in node["inputs"]))
    return lineage


def admit_registration(document: dict[str, Any], identifier: str, value: dict[str, Any]) -> dict[str, Any]:
    """A wire identity references a grant; full old declarations remain readable."""
    if not isinstance(value, dict) or not isinstance(value.get("identity"), dict):
        denied("host_executor_ungranted", "Reference the identity of an executor explicitly registered by this host.")
    lineage = _source_lineage(document)
    used: set[str] = set()
    for node in document["scientific"]["transforms"]:
        if node["kind"] == "external" and node["executor"]["id"] == identifier:
            used.update(lineage[node["output"]])
    sources = tuple(SourceScope.of(item) for item in document["scientific"]["data_sources"] if item["source_id"] in used)
    registration = _registered(identifier, value["identity"], sources)
    if value != {"identity": value["identity"]} and value != registration:
        denied("host_executor_registration_mismatch", "Request paths, deadlines or schemas cannot replace the host's fixed registration.")
    return deepcopy(registration)


def admit_document_executors(document: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.project_lifecycle.errors import EngineError

    used = {node["executor"]["id"] for node in document["scientific"]["transforms"] if node["kind"] == "external"}
    if set(supplied) != used:
        raise EngineError("managed_executor_membership", "Declare exactly the fixed executors used by this plot's transform closure.")
    return {identifier: admit_registration(document, identifier, value) for identifier, value in supplied.items()}
