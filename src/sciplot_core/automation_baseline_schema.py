"""Closed field and scenario vocabularies for R0 automation evidence."""

from __future__ import annotations

from sciplot_core.automation_states import (
    HUMAN_CONFIRMATION_STATE,
    READY_STATE,
    RULE_REPAIR_STATE,
)


AUTOMATION_BASELINE_KIND = "sciplot_automation_r0_baseline"
AUTOMATION_BASELINE_VERSION = 1
AUTOMATION_BASELINE_SCENARIOS = (
    "ready_zero_ai",
    "scientific_confirmation",
    "rule_repair",
    "selected_object_visual_edit",
)
BASELINE_RULE_ID = "performance_comparison"
BASELINE_TEMPLATE = "scatter"
BASELINE_READY_RULE_FLOOR = 24
BASELINE_SELECTION_POLICY = "explicit_supported_template"
BASELINE_PRIMARY_FIGURE_ID = "performance_scatter"
BASELINE_VISUAL_PROVIDER_ID = "studio_assistant_probe"
BASELINE_VISUAL_WIDGET_TYPE = "axis"
BASELINE_VISUAL_SETTING_SUFFIX = "/label"

SCENARIO_DESCRIPTIONS = {
    "ready_zero_ai": (
        "Explicit certified performance rule: cold plan, execute, QA, and "
        "exact-current delivery."
    ),
    "scientific_confirmation": (
        "Controlled medium-confidence replay of the current performance "
        "semantic contract."
    ),
    "rule_repair": (
        "Controlled stale-certificate invocation preflight before source or "
        "filesystem write."
    ),
    "selected_object_visual_edit": (
        "Offline selected-object proposal, validation, apply, render capture, "
        "and native Undo."
    ),
}

BASELINE_LIMITATIONS = (
    "peak_python_memory_bytes is tracemalloc-managed Python memory; Qt native "
    "and child-worker RSS remain outside this portable measurement.",
    "Every ready sample clears the process inspection cache before timing, so "
    "its combined plan plus Autoplot path is a cold-cache measurement.",
    "raw_source_read_opens counts read-mode builtins.open/io.open calls for the "
    "exact fixture path inside one measured in-process operation. It excludes "
    "the initial, per-ready-sample, and final integrity hashes (repetitions + 2 "
    "full reads), native-library I/O, and child processes.",
    "Every measured operation rejects instrumented process-local Python path "
    "mutations outside its sample root and rejects unapproved child-process "
    "launches. Ready additionally compares the persistent source-parent tree "
    "before and after the operation. This is not an operating-system sandbox "
    "for native code.",
    "The confirmation and stale-certificate cases are controlled in-memory "
    "contract replays. The stale invocation records zero exact-fixture reads "
    "and zero builtins.open/io.open write-mode calls; a write attempt is "
    "blocked before the underlying opener runs.",
    "The selected-object provider is deterministic and offline. Production "
    "OpenAI adapter and SSE-client call attempts are blocked and counted "
    "separately; unavailable real token usage is null rather than zero.",
    "Current confirmation evidence exposes a state and reasons but no minimal "
    "question payload; the frozen future contract closes that R1/R2 gap.",
    "Source-derived VSZ, PNG, and history artifacts exist only inside a unique "
    "ephemeral work directory that is deleted before the closed JSON and "
    "Markdown report is written.",
    "Payload component hashes and sizes are producer-measured replay references. "
    "The self-contained validator checks closed shape and internal consistency, "
    "not coordinated report substitution; future compression gates must rerun "
    "the producer against live current-owner objects.",
)

REPORT_FIELDS = frozenset(
    {
        "kind",
        "version",
        "generated_at",
        "status",
        "platform",
        "repetitions",
        "session_payloads",
        "scenario_order",
        "scenarios",
        "summary",
        "artifacts",
        "limitations",
    }
)
SCENARIO_FIELDS = frozenset(
    {
        "scenario_id",
        "description",
        "expected_state",
        "status",
        "samples",
        "metrics",
        "stable_evidence",
    }
)
SAMPLE_FIELDS = frozenset(
    {
        "sample_index",
        "status",
        "observed_state",
        "next_action",
        "provider_mode",
        "provider_outcome",
        "metrics",
        "payload_components",
        "token_usage",
        "evidence_identity",
        "reason_codes",
        "checks",
    }
)
METRIC_FIELDS = frozenset(
    {
        "wall_time_ms",
        "peak_python_memory_bytes",
        "raw_source_read_opens",
        "full_decision_payload_bytes",
        "provider_payload_bytes",
        "provider_context_bytes",
        "image_bytes",
        "provider_requests",
        "model_calls",
        "submit_to_proposal_ms",
        "proposal_to_applied_ms",
    }
)
NULLABLE_METRIC_FIELDS = frozenset(
    {"submit_to_proposal_ms", "proposal_to_applied_ms"}
)
INTEGER_METRIC_FIELDS = frozenset(
    {
        "peak_python_memory_bytes",
        "raw_source_read_opens",
        "full_decision_payload_bytes",
        "provider_payload_bytes",
        "provider_context_bytes",
        "image_bytes",
        "provider_requests",
        "model_calls",
    }
)
TOKEN_USAGE_FIELDS = frozenset({"input_tokens", "output_tokens", "basis"})
PLATFORM_FIELDS = frozenset({"python", "system", "release", "machine"})
SESSION_FIELDS = frozenset(
    {
        "doctor_status",
        "doctor_payload_bytes",
        "doctor_payload_sha256",
        "ready_rule_count",
        "fixture_sha256",
        "fixture_sha256_after",
        "fixture_integrity_reads_outside_measurements",
        "rule_catalog_payload_bytes",
        "rule_catalog_payload_sha256",
        "selected_rule_payload_bytes",
        "selected_rule_payload_sha256",
    }
)
SUMMARY_FIELDS = frozenset(
    {
        "scenario_count",
        "passed_count",
        "model_calls",
        "provider_requests",
        "raw_dataset_arrays_sent",
        "user_delivery_created",
    }
)
ARTIFACT_FIELDS = frozenset({"root", "json", "markdown"})
EVIDENCE_IDENTITY_FIELDS = frozenset({"stable", "sample"})
PAYLOAD_COMPONENT_FIELDS = frozenset({"bytes", "sha256"})
TEXT_EVIDENCE_FIELDS = frozenset(
    {
        "rule_id",
        "plan_id",
        "selection_policy",
        "primary_figure_id",
        "template",
        "provider_id",
        "selected_widget_type",
        "setting_suffix",
    }
)
STABLE_EVIDENCE_FIELDS = frozenset({"identical_across_samples", "first"})
DISTRIBUTION_FIELDS = frozenset({"values", "p50", "p95"})
SCENARIO_STATES = dict(
    zip(
        AUTOMATION_BASELINE_SCENARIOS,
        (
            READY_STATE,
            HUMAN_CONFIRMATION_STATE,
            RULE_REPAIR_STATE,
            READY_STATE,
        ),
        strict=True,
    )
)
SCENARIO_ACTIONS = {
    "ready_zero_ai": "handoff_ready",
    "scientific_confirmation": "ask_human",
    "rule_repair": "handoff_rule_repair",
    "selected_object_visual_edit": "handoff_ready",
}
SCENARIO_PAYLOAD_COMPONENTS = {
    "ready_zero_ai": frozenset({"rule_show", "plan_preview", "autoplot_result"}),
    "scientific_confirmation": frozenset(
        {
            "semantic",
            "source_package",
            "mapping_package",
            "render_request",
            "evaluation",
        }
    ),
    "rule_repair": frozenset({"rule_show"}),
    "selected_object_visual_edit": frozenset(
        {
            "intent",
            "base_revision",
            "context",
            "visual_preview_metadata",
            "provider_response",
            "apply_result",
            "transaction_history",
            "undo_evidence",
        }
    ),
}
SCENARIO_CHECKS = {
    "ready_zero_ai": frozenset(
        {
            "plan_is_planned",
            "autoplot_is_ready",
            "direct_and_planned_facts_match",
            "validated_envelope_is_current",
            "delivery_is_complete",
            "one_delivered_vsz_exists",
            "raw_source_bytes_unchanged",
            "current_and_delivered_vsz_match",
            "instrumented_writes_confined_to_sample_root",
            "source_parent_unchanged",
        }
    ),
    "scientific_confirmation": frozenset(
        {
            "state_requires_human_confirmation",
            "ready_without_ai_is_false",
            "no_rule_repair_reason",
            "one_state_reason_exists",
            "current_runtime_has_no_question_payload",
            "instrumented_writes_confined_to_sample_root",
        }
    ),
    "rule_repair": frozenset(
        {
            "state_requires_rule_repair",
            "stale_registry_is_reported",
            "invocation_stops_before_execution",
            "raw_source_was_not_opened",
            "filesystem_was_not_opened_for_write",
            "show_reuses_same_invocation",
            "instrumented_writes_confined_to_sample_root",
        }
    ),
    "selected_object_visual_edit": frozenset(
        {
            "one_offline_provider_request",
            "proposal_completed_before_apply",
            "manual_accept_applied_one_batch",
            "exact_current_preview_was_bound",
            "raw_dataset_arrays_absent",
            "render_changed_after_apply",
            "history_has_one_complete_transaction",
            "native_undo_restores_prior_state",
            "source_and_copy_bytes_remain_unchanged",
            "upstream_ready_document_is_bound",
            "source_data_was_not_read",
            "instrumented_writes_confined_to_sample_root",
        }
    ),
}
SCENARIO_EVIDENCE_FIELDS = {
    "ready_zero_ai": {
        "stable": frozenset(
            {
                "rule_id",
                "rule_contract_sha256",
                "rule_semantic_contract_sha256",
                "plan_id",
                "plan_sha256",
                "selection_policy",
                "primary_figure_id",
                "template",
                "source_sha256",
                "selected_figure_ids",
                "tasks_sha256",
                "fixture_sha256",
            }
        ),
        "sample": frozenset({"request_sha256", "delivered_vsz_sha256"}),
    },
    "scientific_confirmation": {
        "stable": frozenset(
            {
                "rule_id",
                "current_contract_sha256",
                "current_semantic_contract_sha256",
                "fixture_sha256",
                "controlled_confidence",
                "question_payload_present",
            }
        ),
        "sample": frozenset(),
    },
    "rule_repair": {
        "stable": frozenset(
            {
                "rule_id",
                "current_contract_sha256",
                "current_semantic_contract_sha256",
                "certified_contract_sha256",
                "certified_semantic_contract_sha256",
                "invocation_reason_codes",
            }
        ),
        "sample": frozenset({"filesystem_write_opens"}),
    },
    "selected_object_visual_edit": {
        "stable": frozenset(
            {
                "provider_id",
                "selected_widget_type",
                "setting_suffix",
                "history_statuses",
                "upstream_plan_sha256",
            }
        ),
        "sample": frozenset(
            {
                "source_document_sha256",
                "request_sha256",
                "context_sha256",
                "provider_payload_sha256",
                "base_revision",
                "before_render_sha256",
                "applied_render_sha256",
                "undo_render_sha256",
            }
        ),
    },
}
SCENARIO_REASON_CODES = {
    "ready_zero_ai": (),
    "scientific_confirmation": (
        "mapping_requires_confirmation",
        "semantic_match_requires_confirmation",
    ),
    "rule_repair": (
        "certified_rule_contract_sha256_mismatch",
        "certified_rule_semantic_contract_sha256_mismatch",
    ),
    "selected_object_visual_edit": (),
}
