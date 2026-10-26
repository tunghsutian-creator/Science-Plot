"""Local panel assembly ownership and its bounded iteration gates."""

from sciplot_core.verification.owner_model import ChangedOwner

ASSEMBLY_TESTS = (
    "tests/test_panel_assembly_model.py",
    "tests/test_panel_assembly_storage.py",
    "tests/test_panel_assembly_writer_lease.py",
    "tests/test_panel_assembly_export.py",
    "tests/test_panel_assembly_sources.py",
    "tests/test_panel_assembly_preview.py",
    "tests/test_panel_assembly_physical_styles.py",
    "tests/test_panel_assembly_desktop_previews.py",
    "tests/test_panel_assembly_desktop.py",
    "tests/test_panel_assembly_desktop_review.py",
    "tests/test_panel_assembly_entries.py",
    "tests/test_figure_layout_spans.py",
    "tests/test_figure_grammar_spans.py",
    "tests/test_snapshot_consumer_source_versions.py",
)

PANEL_ASSEMBLY_OWNER = ChangedOwner(
    owner_id="local_panel_assembly",
    path_prefixes=("src/sciplot_core/panel_assembly/",),
    exact_paths=frozenset({
        "src/sciplot_core/cli/parsers/composition.py",
        "src/sciplot_core/cli/dispatch/composition.py",
        "src/sciplot_core/verification/assembly_owners.py",
    }),
    owned_test_paths=frozenset(ASSEMBLY_TESTS),
    pytest_targets=(*ASSEMBLY_TESTS, "tests/test_figure_layout.py", "tests/test_figure_grammar.py",
                    "tests/test_mcp_server.py", "tests/test_cli_surface.py",
                    "tests/test_mcp_stdio.py::test_stdio_composition_intents_reopen_and_preserve_generated_image"),
    mypy_required=True,
    handoff_gates=("doctor",),
    final_milestone_gates=("smoke",),
    release_gates=("full_pytest",),
)
