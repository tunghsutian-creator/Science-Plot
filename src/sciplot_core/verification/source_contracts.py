"""The shared cheap source contracts used before broader behavior checks."""

TYPE_SCOPE_PARTITION_TARGET = (
    "tests/test_ordinary_plotting_owners.py::test_reviewed_strict_additions_extend_the_preserved_residual_scope_once"
)

ARCHITECTURE_CORE_TARGETS = (
    "tests/test_architecture_boundaries.py::test_ordinary_source_files_stay_within_the_size_boundary",
    "tests/test_architecture_boundaries.py::test_first_party_import_graph_is_acyclic",
    "tests/test_iso_timestamps.py::test_first_party_contract_timestamp_implementation_has_one_owner",
    "tests/test_architecture_boundaries.py::test_process_wide_no_io_patches_end_before_test_teardown",
    TYPE_SCOPE_PARTITION_TARGET,
)

CHEAP_SOURCE_TARGETS = (
    *ARCHITECTURE_CORE_TARGETS,
    "tests/test_architecture_boundaries.py::test_non_probe_source_has_no_exact_duplicate_function_implementations",
    "tests/test_architecture_boundaries.py::test_scoped_type_gate_has_one_strict_owned_scope_and_ci_entrypoint",
    "tests/test_export_format_contract.py::test_native_filename_policy_is_outside_the_retained_rendering_closure",
)
