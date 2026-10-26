"""Generated source/entry controls for a frozen qualitative recipe display."""

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from public_curve_inputs import paired_source
from sciplot_core.semantic_sources.scientific_source import resolve_scientific_source
from sciplot_core.studio_render.models import StudioSeries


def _series(count):
    return [
        StudioSeries(
            str(index),
            "Wavenumber",
            "Response",
            (400.0, 800.0, 1200.0),
            (1.0, 3.0, 2.0),
            "#222222",
        )
        for index in range(count)
    ]


def _readable(request, count):
    from sciplot_core.studio_render.domain_defaults import _apply_domain_render_defaults
    from sciplot_core.studio_render.readability_defaults import (
        _apply_readability_render_defaults,
    )

    axis = {
        "x_label": "Wavenumber (cm⁻¹)",
        "y_label": "Response",
        "series_count": count,
    }
    options = _apply_domain_render_defaults(
        dict(request.get("render_options", {})), request=request, axis_info=axis
    )
    return _apply_readability_render_defaults(
        options,
        request=request,
        axis_info=axis,
        series=_series(count),
        template_id="stacked_curve",
    )


@pytest.mark.parametrize(("show", "count"), [(False, 1), (True, 2)])
def test_terminal_preserves_actual_bool_even_when_it_is_not_user_explicit(show, count):
    request = {
        "rule_id": "ftir_spectrum",
        "template": "stacked_curve",
        "render_options": {"show_y_ticks": show, "baseline": "none"},
        "explicit_render_option_keys": [],
    }
    before = deepcopy(request)
    assert _readable(request, count)["show_y_ticks"] is show
    assert request == before


def test_missing_historical_stack_display_retains_its_single_multi_fallback():
    request = {
        "rule_id": "ftir_spectrum",
        "template": "stacked_curve",
        "render_options": {},
    }
    assert _readable(request, 1)["show_y_ticks"] is True
    assert _readable(request, 2)["show_y_ticks"] is False


def test_actual_ftir_single_response_rule_merge_retains_quantitative_readout(tmp_path):
    from sciplot_core.materials_rules import get_rule, semantic_payload_from_rule
    from sciplot_core.studio_render.series_domain import _resolved_domain_render_options
    from sciplot_core.studio_render.readability_defaults import (
        _apply_readability_render_defaults,
    )
    from sciplot_core.workflow.scientific_source_resolution import (
        bind_workflow_semantic_render_options,
    )

    semantic = semantic_payload_from_rule(get_rule("ftir_spectrum"), confidence=100.0)
    assert "show_y_ticks" not in semantic["render_options"]
    for response, unit in (("Absorbance", "a.u."), ("Transmittance", "%")):
        source = tmp_path / f"{response}.csv"
        source.write_text(
            f"Wavenumber,{response}\ncm^-1,{unit}\nGenerated,Generated\n4000,10\n2000,30\n500,20\n"
        )
        resolved = resolve_scientific_source(
            source, rule_id="ftir_spectrum", template="stacked_curve", request={}
        )
        assert resolved is not None and resolved.transform is not None
        original = resolved.transform.series[0]
        series = [
            StudioSeries(
                original.sample,
                "x",
                "y",
                tuple(x for x, _ in original.points),
                tuple(y for _, y in original.points),
                "#222222",
            )
        ]
        request = {
            "input": str(source),
            "rule_id": "ftir_spectrum",
            "template": "stacked_curve",
            "render_options": {},
            "explicit_render_option_keys": [],
        }
        bound = bind_workflow_semantic_render_options(
            request=request,
            semantic=semantic,
            figure_plan=resolved.figure_plan,
            resolved_scientific_source=resolved,
            new_creation=True,
        )
        assert "show_y_ticks" not in bound["render_options"]
        axis = {
            "x_label": "Wavenumber (cm⁻¹)",
            "y_label": f"{response} ({unit})",
            "series_count": 1,
        }
        options = _resolved_domain_render_options(bound, axis_info=axis, series=series)
        terminal = _apply_readability_render_defaults(
            options,
            request=bound,
            axis_info=axis,
            series=series,
            template_id="stacked_curve",
        )
        assert terminal["show_y_ticks"] is True


def test_new_xrd_freezes_registered_purpose_without_reinterpreting_source_values(
    tmp_path,
):
    from sciplot_core.studio_render.spectral_axis_display import (
        freeze_new_spectral_axis_display,
    )

    source, _ = paired_source(tmp_path / "raw", "xrd_pattern")
    original = source.read_bytes()
    resolved = resolve_scientific_source(
        source, rule_id="xrd_pattern", template="curve", request={}
    )
    assert resolved is not None and resolved.transform is not None
    contract = resolved.transform.contract.to_payload()
    scientific_snapshot = deepcopy(resolved.transform)
    request = {
        "input": str(source),
        "rule_id": "xrd_pattern",
        "template": "curve",
        "render_options": {},
        "explicit_render_option_keys": [],
    }
    frozen = freeze_new_spectral_axis_display(
        request, rule_id="xrd_pattern", template="curve", transform_contract=contract
    )
    assert frozen["render_options"] == {"show_y_ticks": False}
    assert frozen["explicit_render_option_keys"] == []
    assert request["render_options"] == {}
    assert resolved.transform == scientific_snapshot
    assert source.read_bytes() == original
    # No observations, labels or series count enter this persisted decision.
    saved = json.loads(json.dumps(frozen))
    saved["series_order"] = ["new label", "another label", "third"]
    changed = deepcopy(contract)
    changed["output"]["series"] = []
    assert (
        freeze_new_spectral_axis_display(
            saved, rule_id="xrd_pattern", template="curve", transform_contract=changed
        )["render_options"]
        == frozen["render_options"]
    )

    for options in (
        {"show_y_ticks": True},
        {"show_y_ticks": False},
        {"y_ticks": [0, 1]},
        {"y_min": 0},
        {"y_max": 1},
        {"yscale": "log"},
    ):
        selected = {
            **request,
            "render_options": options,
            "explicit_render_option_keys": list(options),
        }
        result = freeze_new_spectral_axis_display(
            selected,
            rule_id="xrd_pattern",
            template="curve",
            transform_contract=contract,
        )
        assert result["render_options"]["show_y_ticks"] is options.get(
            "show_y_ticks", True
        )
    for normalizer in (None, {}, {"scope": "global", "operation": "normalize"}):
        unknown = {**contract, "normalizer": normalizer}
        assert (
            freeze_new_spectral_axis_display(
                request,
                rule_id="xrd_pattern",
                template="curve",
                transform_contract=unknown,
            )["render_options"]["show_y_ticks"]
            is True
        )
    assert (
        freeze_new_spectral_axis_display(
            {**request, "intent": {"y": {"quantity": "intensity"}}},
            rule_id="xrd_pattern",
            template="curve",
            transform_contract=contract,
        )["render_options"]
        == {}
    )
    for rule in ("uvvis_spectrum", "saxs_profile", "ftir_spectrum"):
        assert (
            freeze_new_spectral_axis_display(
                request, rule_id=rule, template="curve", transform_contract=contract
            )
            == request
        )


def test_ordinary_raw_task_creation_reaches_frozen_xrd_before_native_transaction(
    tmp_path, monkeypatch
):
    from sciplot_core.plan_preview import build_plan_preview
    from sciplot_core.studio_core import prepare_generated
    from sciplot_core.studio_core.project_creation import create_project
    from sciplot_core.studio_core.studio_prepare import prepare_studio_document

    captured = []

    class BeforeNative(Exception):
        pass

    def stop(**kwargs):
        captured.append(deepcopy(kwargs))
        raise BeforeNative

    monkeypatch.setattr(
        prepare_generated, "_prepare_generated_figure_set_transaction", stop
    )
    for rule in ("xrd_pattern", "uvvis_spectrum", "saxs_profile"):
        source, _ = paired_source(tmp_path / rule, rule)
        original = source.read_bytes()
        plan = build_plan_preview(
            source, request={"rule_id": rule, "template": "curve"}
        )
        assert plan["status"] == "planned", plan
        with pytest.raises(BeforeNative):
            create_project(
                source,
                expected_plan=plan,
                output_dir=tmp_path / ("delivery_" + rule),
                publish=False,
            )
        current = captured[-1]
        expected = False if rule == "xrd_pattern" else None
        assert (
            current["request"].get("render_options", {}).get("show_y_ticks") is expected
        )
        assert (
            current["primary_render_request"]
            .get("render_options", {})
            .get("show_y_ticks")
            is expected
        )
        assert "show_y_ticks" not in current["request"].get(
            "explicit_render_option_keys", []
        )
        assert source.read_bytes() == original
    source = tmp_path / "xrd_pattern" / "generated_xrd_pattern.csv"
    # A historical canonical JSON is a replay, even when it has no VSZ yet.
    replay_dir = tmp_path / "historical"
    replay_dir.mkdir()
    replay = replay_dir / "plot_request.json"
    replay.write_text(
        json.dumps(
            {"input": str(source), "rule_id": "xrd_pattern", "template": "curve"}
        )
    )
    with pytest.raises(BeforeNative):
        prepare_studio_document(replay)
    assert "show_y_ticks" not in captured[-1]["request"].get("render_options", {})
    for index, options in enumerate((
        {"show_y_ticks": True},
        {"y_min": 0, "y_max": 1, "y_ticks": [0, 0.5, 1]},
    )):
        # Each explicit new creation is a separate draft. Do not overwrite the
        # admitted historical request left by the preceding stopped preview.
        explicit = tmp_path / f"explicit_{index}"
        explicit.mkdir()
        explicit_request = explicit / "plot_request.json"
        explicit_request.write_text(
            json.dumps(
                {
                    "input": str(source),
                    "rule_id": "xrd_pattern",
                    "template": "curve",
                    "render_options": options,
                }
            )
        )
        with pytest.raises(BeforeNative):
            prepare_studio_document(explicit_request, _new_creation=True)
        assert captured[-1]["request"]["render_options"]["show_y_ticks"] is True


def test_public_intake_factories_reach_new_xrd_display_without_changing_generic_callback(
    tmp_path, monkeypatch
):
    import sciplot_core.intake as intake
    from sciplot_core.intake import application
    from sciplot_core.intake.models import IncomingFile, IntakeGroupInput
    from sciplot_core.intake.session import prepare_intake_session
    from sciplot_core.studio_core import prepare_generated

    source, _ = paired_source(tmp_path / "raw", "xrd_pattern")
    original = source.read_bytes()
    captured = []

    def stop(**kwargs):
        captured.append(deepcopy(kwargs))
        raise RuntimeError("Stopped before native transaction")

    monkeypatch.setattr(
        prepare_generated, "_prepare_generated_figure_set_transaction", stop
    )
    created = application.create_intake_project(
        project_name="Qualitative pattern",
        data_type_id="scattering",
        experiment_type_id="xrd_pattern",
        groups=[
            IntakeGroupInput(
                sample="Generated",
                files=(IncomingFile(name=source.name, content=original),),
            )
        ],
        output_root=tmp_path / "direct",
    )
    assert created["studio"]["status"] == "blocked"
    for index, factory in enumerate(
        (
            application.create_intake_project_from_session,
            intake.create_intake_project_from_session,
        )
    ):
        session = prepare_intake_session(
            source,
            output_root=tmp_path / f"session_{index}",
            requested_rule_id="xrd_pattern",
        )
        assert factory(session)["studio"]["status"] == "blocked"
    assert len(captured) == 3
    assert all(
        item["request"]["render_options"]["show_y_ticks"] is False
        and item["primary_render_request"]["render_options"]["show_y_ticks"] is False
        for item in captured
    )
    assert source.read_bytes() == original


def test_workflow_freezes_new_snapshot_but_replays_old_request_without_new_default(
    tmp_path, monkeypatch
):
    from sciplot_core.materials_rules import get_rule, semantic_payload_from_rule
    from sciplot_core.workflow import request_run
    from sciplot_core.workflow.scientific_source_resolution import (
        bind_workflow_semantic_render_options,
    )

    source, _ = paired_source(tmp_path / "raw", "xrd_pattern")

    class BeforeNative(Exception):
        pass

    def stop(*_args, **_kwargs):
        raise BeforeNative

    monkeypatch.setattr(request_run, "verify_workflow_figure_plan_source_binding", stop)
    for index, (new, options, expected) in enumerate(
        (
            (True, {}, False),
            (False, {}, None),
            (False, {"show_y_ticks": False}, False),
            (False, {"show_y_ticks": True}, True),
        )
    ):
        path = tmp_path / f"request_{index}.json"
        output = tmp_path / f"run_{index}"
        path.write_text(
            json.dumps(
                {
                    "input": str(source),
                    "output": str(output),
                    "rule_id": "xrd_pattern",
                    "template": "curve",
                    "render_options": options,
                    "explicit_render_option_keys": [],
                }
            )
        )
        with pytest.raises(BeforeNative):
            request_run.run_request(path, _new_creation=new)
        snapshot = json.loads((output / "request_snapshot.json").read_text())
        assert snapshot["render_options"].get("show_y_ticks") is expected
        assert snapshot["explicit_render_option_keys"] == []
        assert (
            json.loads(path.read_text())["render_options"].get("show_y_ticks")
            is expected
        )
    # A recorded typed bool has priority over a later semantic default, but
    # never gains user-explicit provenance merely by surviving that merge.
    semantic = semantic_payload_from_rule(get_rule("xrd_pattern"), confidence=100.0)
    semantic["render_options"]["show_y_ticks"] = True
    bound = bind_workflow_semantic_render_options(
        request={
            "render_options": {"show_y_ticks": False},
            "explicit_render_option_keys": [],
        },
        semantic=semantic,
        figure_plan=None,
    )
    assert bound["render_options"]["show_y_ticks"] is False
    assert bound["explicit_render_option_keys"] == []


def test_same_selected_presentation_regeneration_preserves_frozen_bool(tmp_path):
    from sciplot_core.studio_core.request_overrides import (
        _apply_studio_request_overrides,
    )

    for index, (show, template) in enumerate((
        (False, "curve"),
        (True, "curve"),
        (False, None),
        (True, None),
    )):
        # Independent frozen-request cases cannot mutate another case's head.
        project = tmp_path / f"frozen_{index}"
        project.mkdir()
        path = project / "plot_request.json"
        original_template = {"template": template} if template is not None else {}
        path.write_text(
            json.dumps(
                {
                    "rule_id": "xrd_pattern",
                    **original_template,
                    "render_options": {"show_y_ticks": show},
                    "explicit_render_option_keys": [],
                }
            )
        )
        _apply_studio_request_overrides(
            project, request_path=path, rule_id="xrd_pattern", template="curve"
        )
        saved = json.loads(path.read_text())
        assert saved["render_options"]["show_y_ticks"] is show
        assert saved["explicit_render_option_keys"] == []


def test_one_step_new_runs_keep_actual_selection_across_auto_explicit_and_new_recipes(
    tmp_path, monkeypatch
):
    from sciplot_core.semantic import classify_source
    from sciplot_core.workflow import request_run
    from sciplot_core.workflow.one_step_entry import run_one_step
    from sciplot_core.workflow.scientific_source_resolution import (
        previous_workflow_request,
    )

    source, _ = paired_source(tmp_path / "raw", "xrd_pattern")
    original = source.read_bytes()
    path = tmp_path / "projects" / "same_figure" / "plot_request.json"
    classifications = []

    class BeforeNative(Exception):
        pass

    def stop(*_args, **_kwargs):
        raise BeforeNative

    def classified(input_path, **kwargs):
        result = classify_source(input_path, **kwargs)
        classifications.append((kwargs["requested_rule_id"], result["reason"]))
        return result

    def run(request_path, **context):
        return request_run.run_request(request_path, _classifier=classified, **context)

    def invoke(selected_source=source, *, rule=None, template=None):
        with pytest.raises(BeforeNative):
            run_one_step(
                selected_source,
                output_root=tmp_path / "projects",
                project_name="same figure",
                rule_id=rule,
                template=template,
                _request_runner=run,
            )
        canonical = json.loads(path.read_text())
        snapshot = json.loads(
            (Path(canonical["output"]) / "request_snapshot.json").read_text()
        )
        return canonical, snapshot

    monkeypatch.setattr(request_run, "verify_workflow_figure_plan_source_binding", stop)
    canonical, _ = invoke()
    assert "rule_id" not in canonical and "template" not in canonical
    assert canonical["resolved_figure_plan"]["rule_id"] == "xrd_pattern"
    assert canonical["render_options"]["show_y_ticks"] is False
    assert (
        classifications[-1][0] is None
        and "Explicit material rule" not in classifications[-1][1]
    )
    assert (
        invoke(rule="xrd_pattern", template="curve")[1]["render_options"][
            "show_y_ticks"
        ]
        is False
    )
    assert classifications[-1][0] == "xrd_pattern"
    assert invoke()[1]["render_options"]["show_y_ticks"] is False
    assert classifications[-1][0] is None

    # A pre-02 automatic request can recover only its exact owned run snapshot.
    old = json.loads(path.read_text())
    old.pop("resolved_figure_plan")
    old.pop("explicit_render_option_keys")
    old["render_options"]["show_y_ticks"] = True
    path.write_text(json.dumps(old))
    recovered = previous_workflow_request(path)
    assert (
        recovered is not None
        and recovered["resolved_figure_plan"]["rule_id"] == "xrd_pattern"
    )
    canonical, snapshot = invoke(rule="xrd_pattern", template="curve")
    assert snapshot["render_options"]["show_y_ticks"] is True
    assert snapshot["explicit_render_option_keys"] == ["show_y_ticks"]
    canonical, snapshot = invoke()
    assert snapshot["render_options"]["show_y_ticks"] is True
    assert "rule_id" not in canonical and "template" not in canonical
    assert classifications[-1][0] is None
    canonical["render_options"]["show_y_ticks"] = False
    path.write_text(json.dumps(canonical))
    assert invoke(rule="xrd_pattern")[1]["render_options"]["show_y_ticks"] is False

    uvvis, _ = paired_source(tmp_path / "uvvis", "uvvis_spectrum")
    assert (
        invoke(uvvis, rule="uvvis_spectrum", template="curve")[1]["render_options"].get(
            "show_y_ticks"
        )
        is not False
    )
    assert (
        invoke(rule="xrd_pattern", template="curve")[1]["render_options"][
            "show_y_ticks"
        ]
        is False
    )
    # A foreign/stale snapshot cannot establish a missing prior identity.
    old = json.loads(path.read_text())
    old.pop("resolved_figure_plan")
    path.write_text(json.dumps(old))
    recorded_path = Path(old["output"]) / "request_snapshot.json"
    recorded = json.loads(recorded_path.read_text())
    recorded["input"] = str(uvvis)
    recorded_path.write_text(json.dumps(recorded))
    assert "resolved_figure_plan" not in previous_workflow_request(path)
    assert source.read_bytes() == original


def test_hidden_managed_ticks_are_presentation_and_survive_saved_append(tmp_path):
    from test_current_view_lifecycle import _append, _create, _sources
    from sciplot_core.plot_engine.current_unit_admission import prepare_current_update
    from sciplot_core.plot_engine.managed_resolution import resolve_science
    from sciplot_core.plot_ir.figure_document import figure_spec, store_spec

    a, b = _sources(tmp_path)
    root = tmp_path / "store"
    initial = _create([a], root)
    original = deepcopy(initial["scientific"])
    spec = figure_spec(initial)
    axis = spec["views"][0]["axes"][1]
    axis.update(
        {
            "ticks": [],
            "ticks_mode": "fixed",
            "style": {**axis["style"], "minor_ticks_visible": False},
        }
    )
    hidden = store_spec(initial, spec)
    assert hidden["scientific_hash"] == initial["scientific_hash"]
    assert hidden["scientific"] == original
    reopened = json.loads(json.dumps(hidden))
    other = _create([b], tmp_path / "other")
    candidate = prepare_current_update(root, reopened, _append(reopened, other))[0]
    appended = resolve_science(root, candidate)[0]
    assert figure_spec(appended)["views"][0]["axes"][1] == axis


def test_existing_y_visibility_projects_all_three_native_settings_without_science_change():
    from sciplot_core.studio_core.veusz_axis_apply import _add_veusz_axis
    from sciplot_core.studio_render.axes_spec import _veusz_axes_spec
    from sciplot_core.studio_render.models import (
        _VeuszAxisContract,
        _VeuszStyleContract,
    )

    class Settings:
        def __init__(self):
            self.values = {}

        def Add(self, *_args, **_kwargs):
            pass

        def To(self, *_args):
            pass

        def Set(self, key, value):
            self.values[key] = value

    style = _VeuszStyleContract()
    domain = _VeuszAxisContract(
        x_min=10, x_max=30, y_min=0, y_max=10, x_ticks=(10, 20, 30), y_ticks=(0, 5, 10)
    )
    options = {"show_y_ticks": False}
    axes = _veusz_axes_spec(
        render_options=options,
        axis_info={"x_label": "2θ (deg)", "y_label": "Intensity (a.u.)"},
        axis_contract=domain,
        categorical_contract=None,
        style=style,
    )
    settings = Settings()
    _add_veusz_axis(settings, "y", axes["y"], asdict(style))
    for group in ("MajorTicks", "MinorTicks", "TickLabels"):
        assert settings.values[group + "/hide"] is True
    assert settings.values["Line/hide"] is False
    assert settings.values["Label/hide"] is False
    assert settings.values["MajorTicks/manualTicks"] == [0.0, 5.0, 10.0]
    assert axes["y"]["min"] == 0 and axes["y"]["max"] == 10
    assert "show_ticks" not in axes["x"]
