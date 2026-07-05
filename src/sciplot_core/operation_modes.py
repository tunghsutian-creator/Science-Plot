from __future__ import annotations

from typing import Any

NORMAL_MODE = "normal"
ASSISTED_CLEANUP_MODE = "assisted_cleanup"
DEFAULT_ASSISTANT_PROVIDER = "codex"


def normal_mode_payload(*, route: str, renderer: str = "veusz") -> dict[str, Any]:
    return {
        "kind": "sciplot_operation_mode",
        "mode": NORMAL_MODE,
        "ui_mode": "independent",
        "frontend_default": True,
        "route": route,
        "renderer": renderer,
        "base_pipeline_ready": True,
        "assistant_required": False,
        "assistant_optional": True,
        "assistant_provider": DEFAULT_ASSISTANT_PROVIDER,
        "assistant_purpose": "messy_data_cleanup_or_rule_repair",
        "codex_controlled": False,
        "user_switch_required": False,
    }


def assisted_cleanup_mode_payload(
    *,
    reason: str | None = None,
    provider: str = DEFAULT_ASSISTANT_PROVIDER,
) -> dict[str, Any]:
    return {
        "kind": "sciplot_operation_mode",
        "mode": ASSISTED_CLEANUP_MODE,
        "ui_mode": "assisted",
        "frontend_default": False,
        "reason": reason or "input_cleanup_or_rule_repair",
        "base_pipeline_ready": False,
        "base_pipeline_state": "blocked_until_assistant_or_clean_input_is_ready",
        "assistant_required": False,
        "assistant_optional": True,
        "assistant_provider": provider,
        "activation": "automatic_when_codex_runs_or_pipeline_blocks",
        "codex_controlled": provider == DEFAULT_ASSISTANT_PROVIDER,
        "user_switch_required": False,
        "human_review_role": "review_outputs_not_switch_modes",
        "raw_data_policy": "preserve_raw_inputs",
        "human_review_required_before_final_render": True,
    }


__all__ = [
    "ASSISTED_CLEANUP_MODE",
    "DEFAULT_ASSISTANT_PROVIDER",
    "NORMAL_MODE",
    "assisted_cleanup_mode_payload",
    "normal_mode_payload",
]
