"""Focused ownership of the explicit source-bound TTS suite."""

from sciplot_core.verification.owner_model import ChangedOwner

RHEOLOGY_TTS_OWNER = ChangedOwner(
    owner_id="rheology_tts_suite",
    path_prefixes=("src/sciplot_core/workflow/rheology_tts", "src/sciplot_core/rheology_tts",
                   "src/sciplot_core/semantic_sources/rheology_tts"),
    exact_paths=frozenset({
        "src/sciplot_core/semantic_sources/rheology_tts.py",
        "src/sciplot_core/cli/parsers/rheology.py", "src/sciplot_core/cli/dispatch/rheology.py",
    }),
    owned_test_paths=frozenset({"tests/test_rheology_tts.py", "tests/test_rheology_tts_errors.py", "tests/test_rheology_tts_render.py", "tests/test_rheology_tts_native_edit.py", "tests/test_rheology_tts_suite.py",
                              "tests/test_rheology_tts_separated_plan.py", "tests/test_rheology_tts_revision_tables.py",
                              "tests/test_rheology_tts_style.py", "tests/test_rheology_tts_style_update.py",
                              "tests/test_rheology_tts_prepared.py", "tests/test_rheology_tts_prepared_recovery.py",
                              "tests/test_rheology_tts_render_creation.py", "tests/test_rheology_tts_presentation_plan.py",
                              "tests/test_rheology_tts_creation_repair.py", "tests/test_rheology_tts_native_failure_wire.py"}),
    pytest_targets=("tests/test_rheology_tts.py", "tests/test_rheology_tts_errors.py", "tests/test_rheology_tts_render.py", "tests/test_rheology_tts_native_edit.py", "tests/test_rheology_tts_suite.py",
                    "tests/test_rheology_tts_separated_plan.py", "tests/test_rheology_tts_revision_tables.py",
                    "tests/test_rheology_tts_style.py", "tests/test_rheology_tts_style_update.py",
                    "tests/test_rheology_tts_prepared.py", "tests/test_rheology_tts_prepared_recovery.py",
                              "tests/test_rheology_tts_render_creation.py", "tests/test_rheology_tts_presentation_plan.py",
                              "tests/test_rheology_tts_creation_repair.py", "tests/test_rheology_tts_native_failure_wire.py"),
    handoff_gates=("doctor",), final_milestone_gates=("smoke",), release_gates=("full_pytest",),
)
