from __future__ import annotations

import pytest

import sciplot_core.setting_catalog as setting_catalog
from sciplot_core.assistant_provider import (
    ASSISTANT_PROPOSAL_KINDS,
    AssistantProviderDescriptor,
)
from sciplot_core.assistant_operations import (
    SUPPORTED_VEUSZ_SETTING_OPERATIONS,
    VEUSZ_SETTING_OPERATION_BATCH_KIND,
    VEUSZ_SETTING_OPERATION_KIND,
    VEUSZ_SETTING_OPERATION_VERSION,
    VeuszSettingOperation,
    VeuszSettingOperationBatch,
)


def test_assistant_operation_contract_is_set_setting_only() -> None:
    assert SUPPORTED_VEUSZ_SETTING_OPERATIONS == frozenset({"set_setting"})

    with pytest.raises(ValueError, match="Unsupported VeuszSettingOperation"):
        VeuszSettingOperation(
            operation_type="add_widget",
            target_id="selected",
            arguments={"widget_type": "label"},
        )


def test_assistant_provider_rejects_retired_data_mapping_proposals() -> None:
    assert ASSISTANT_PROPOSAL_KINDS == frozenset(
        {"veusz_setting_operation_batch"}
    )
    with pytest.raises(
        ValueError,
        match="provider capabilities contains unsupported values",
    ):
        AssistantProviderDescriptor(
            provider_id="legacy-mapping-provider",
            display_name="Legacy mapping provider",
            capabilities=("data_mapping_proposal",),
        )


def test_set_setting_batch_preserves_serialized_kind_and_version() -> None:
    operation = VeuszSettingOperation.set_setting(
        target_id="selected",
        setting_path="/page1/graph1/x/label",
        value="Time (s)",
        expected_value="Time",
        require_expected_value=True,
    )
    batch = VeuszSettingOperationBatch(
        base_revision=7,
        operations=(operation,),
        provider="test-provider",
        rationale="Clarify the selected axis label.",
    )

    operation_payload = operation.to_dict()
    batch_payload = batch.to_dict()
    assert operation_payload["kind"] == VEUSZ_SETTING_OPERATION_KIND
    assert batch_payload["kind"] == VEUSZ_SETTING_OPERATION_BATCH_KIND
    assert operation_payload["version"] == VEUSZ_SETTING_OPERATION_VERSION == 1
    assert batch_payload["version"] == VEUSZ_SETTING_OPERATION_VERSION
    assert VeuszSettingOperation.from_dict(operation_payload) == operation
    assert VeuszSettingOperationBatch.from_dict(batch_payload) == batch


def test_serialized_legacy_operations_fail_closed() -> None:
    operation = VeuszSettingOperation.set_setting(
        target_id="selected",
        setting_path="/page1/graph1/x/label",
        value="Time (s)",
    )
    payload = operation.to_dict()
    payload["operation_type"] = "composition_set_layout"
    payload["arguments"] = {
        "layout_id": "two_equal",
        "expected_layout_id": "one_panel",
    }

    with pytest.raises(ValueError, match="Unsupported VeuszSettingOperation"):
        VeuszSettingOperation.from_dict(payload)


def test_setting_catalog_exposes_specs_without_legacy_inspector_models() -> None:
    assert not hasattr(setting_catalog, "INSPECTOR_MODEL_KIND")
    assert not hasattr(setting_catalog, "INSPECTOR_MODEL_VERSION")
    assert setting_catalog.specs_for_object_type("axis")
    assert setting_catalog.specs_for_object_type("unsupported") == ()
