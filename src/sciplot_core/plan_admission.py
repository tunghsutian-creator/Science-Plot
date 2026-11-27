"""Expected-plan replay admission; the preview producer owns data resolution."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.plan_identity import preview_identity_for
from sciplot_core.plan_preview_contract import PlanPreviewPayload


def expected_plan_request(
    source: Path,
    expected: dict[str, Any],
    *,
    rule_id: str | None,
    template: str | None,
) -> tuple[dict[str, Any], str]:
    """Validate identity and recover the admitted request without observing the source."""

    if (
        not isinstance(expected, dict)
        or expected.get("kind") != "sciplot_figure_plan_preview"
        or type(expected.get("version")) is not int
        or expected.get("version") != 1
        or expected.get("status") not in ("planned", "not_applicable")
        or expected.get("blocker") is not None
    ):
        raise ValueError("--expected-plan requires a successful current plan preview.")
    identity = expected.get("preview_identity")
    digest = identity.get("source_tree_sha256") if isinstance(identity, dict) else None
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("Expected plan has no valid input identity; run plan again.")
    if canonical_json_sha256(identity, allow_nan=False) != canonical_json_sha256(
        preview_identity_for(expected, source_sha256=digest), allow_nan=False
    ):
        raise ValueError("Expected plan contents or identity changed; run plan again.")
    if source_tree_sha256(source) != digest:
        raise ValueError("Source changed since the expected plan; run plan again.")
    selected = {
        "rule_id": rule_id if rule_id is not None else expected.get("rule_id"),
        "template": template if template is not None else expected.get("template"),
    }
    if "source_options" in expected:
        from sciplot_core.plan_source_options import expected_source_options

        selected.update(expected_source_options(expected["source_options"]))
    mapping = expected.get("data_mapping")
    if mapping is not None:
        if not isinstance(mapping, dict):
            raise ValueError("Expected plan has an invalid confirmed mapping binding.")
        selected.update({
            key: mapping.get(key)
            for key in ("data_mapping_execution", "data_mapping_proposal_id")
        })
    return selected, digest


def require_expected_observation(
    source: Path, expected: dict[str, Any], current: PlanPreviewPayload, *,
    selected: dict[str, Any], digest: str, reused_observation: bool,
) -> None:
    """Admit the unchanged scientific observation as close as possible to use."""
    if reused_observation and (current.get("rule_id") != selected["rule_id"] or current.get("template") != selected["template"]):
        raise ValueError("Expected plan is stale or its rule, template, or scientific selections changed; run plan again.")
    if current["status"] == "blocked":
        blocker = current.get("blocker")
        raise ValueError(
            "Expected plan can no longer execute: "
            + (
                blocker["message"]
                if blocker
                else "the current scientific plan is blocked"
            )
        )
    if canonical_json_sha256(current, allow_nan=False) != canonical_json_sha256(
        expected, allow_nan=False
    ):
        raise ValueError(
            "Expected plan is stale or its rule, template, or scientific selections changed; run plan again."
        )
    # Recheck as close as possible to run_one_step's source consumer. The normal
    # workflow owns source snapshots and publication checks after this preflight.
    if source_tree_sha256(source) != digest:
        raise ValueError(
            "Source changed during expected-plan validation; run plan again."
        )


def request_fields_from_verified_plan(source: Path, verified: dict[str, Any]) -> dict[str, Any]:
    """Recover the admitted scientific request, independent of the output route."""

    from sciplot_core.data_mapping.plan_binding import resolve_mapping_plan_request

    current = None
    if "data_mapping" in verified:
        mapping = verified["data_mapping"]
        request, current = resolve_mapping_plan_request(
            source, {**mapping, "rule_id": verified["rule_id"], "template": verified["template"]},
        )
        if current != mapping:
            raise ValueError("The confirmed mapping changed after the expected plan.")
    else:
        request = {"input": str(source), "rule_id": verified["rule_id"], "template": verified["template"]}
    request.update(deepcopy(verified.get("source_options", {})))
    if request.get("summary_statistic") == "raw_only":
        request["render_options"] = {**request.get("render_options", {}), "summary_statistic": "raw_only"}
    request["resolved_figure_plan"] = deepcopy(verified["resolved_figure_plan"])
    if current is not None:
        request["data_mapping_plan_binding"] = current
    if verified["rule_id"] == "rheology_stress_relaxation":
        # The canonical-request route must reuse the rule-default owner just as
        # raw-source intake does. A top-level scientific choice alone is not a
        # render option and must never leave a log projection on a linear axis.
        scale = request.get("xscale", "log")
        request["render_options"] = {"xscale": scale,
            **({"x_tick_format": "Auto"} if scale == "linear" else {})}
    return request
