"""Bind one successful numeric replay to that invocation's exact read facts.

This digest proves neither historical namespace-directory contents nor a new
filesystem permission. Ordinary per-file and complete-tree guards still apply.
"""
from sciplot_core.data_mapping.execution_inputs import MappingInputReadSet
from sciplot_core.foundation.json_hashing import canonical_json_sha256


def numeric_input_digest(readset: MappingInputReadSet) -> str:
    return canonical_json_sha256({
        'execution': readset.execution,
        'expected_source': str(readset.expected_source) if readset.expected_source is not None else None,
        'files': {literal: {'sha256': item.sha256, 'mode': item.mode}
                  for literal, item in sorted(readset.files.items())},
        'metadata': sorted(readset.metadata),
        'trees': {literal: tree.to_payload() for literal, tree in sorted(readset.trees.items())},
    })
