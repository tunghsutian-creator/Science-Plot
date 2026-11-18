"""Exact Managed frequency ownership and feedback for the reviewed workflow leaves."""

from sciplot_core.verification.owner_model import ChangedOwner

_FREQUENCY_GROUP_TEST = "tests/test_rheology_mean_suite_publication.py"
_FREQUENCY_CREATION_TEST = "tests/test_managed_frequency_creation.py"
FREQUENCY_WORKFLOW_PATHS = frozenset({
    "src/sciplot_core/workflow/frequency_managed_grouping.py",
    "src/sciplot_core/workflow/frequency_managed_metrics.py",
    "src/sciplot_core/workflow/frequency_managed_requests.py",
    "src/sciplot_core/workflow/frequency_managed_suite.py",
    "src/sciplot_core/workflow/frequency_managed_workflow.py",
    _FREQUENCY_GROUP_TEST,
})
FREQUENCY_ENTRY_PATHS = frozenset({
    "src/sciplot_core/studio_core/managed_frequency_creation.py",
    "src/sciplot_core/studio_core/managed_frequency_query.py",
    _FREQUENCY_CREATION_TEST,
})
FREQUENCY_FOCUSED = (_FREQUENCY_GROUP_TEST, "tests/test_rheology_managed_sparse_metric.py")
FREQUENCY_WORKFLOW_NATIVE = tuple(_FREQUENCY_GROUP_TEST + "::" + name for name in (
    "test_frequency_mean_suite_publishes_real_managed_heads_and_analysis_as_one_generation",
    "test_frequency_suite_preaccept_retry_cold_resumes_only_the_unfinished_figure",
    "test_default_frequency_cli_publishes_and_retries_same_managed_editable_group",
))
FREQUENCY_ENTRY_NATIVE = (_FREQUENCY_CREATION_TEST,)
MANAGED_FREQUENCY_OWNER = ChangedOwner(
    owner_id="managed_frequency_workflow",
    exact_paths=FREQUENCY_ENTRY_PATHS | FREQUENCY_WORKFLOW_PATHS,
    pytest_targets=(
        *FREQUENCY_FOCUSED, *FREQUENCY_WORKFLOW_NATIVE, *FREQUENCY_ENTRY_NATIVE,
        "tests/test_architecture_boundaries.py::test_first_party_import_graph_is_acyclic",
    ),
)
