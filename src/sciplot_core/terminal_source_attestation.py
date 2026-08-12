"""Bridge same-transaction preparation evidence into terminal rendering."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.terminal_source_binding import (
    MaterializedTerminalSourceBinding,
    SourceArtifactBinding,
    TerminalSourceBindingError,
)


def terminal_binding_from_preparation_attestation(
    *,
    task_key: str,
    rule_id: str,
    template: str,
    x_metric: str,
    y_metric: str,
    source_attestation: PreparationSourceAttestation,
    terminal_source: Path,
    sample_order: Iterable[str],
    point_counts: Mapping[str, int],
) -> MaterializedTerminalSourceBinding:
    """Reuse captured artifact identities instead of hashing them again."""

    if source_attestation.rule_id != rule_id:
        _mismatch("Preparation attestation rule does not match terminal rendering.")
    prepared = SourceArtifactBinding(
        path=source_attestation.prepared_source.path,
        sha256=source_attestation.prepared_source.sha256,
    )
    if str(terminal_source.expanduser().resolve()) != prepared.path:
        _mismatch("Prepared and terminal source identities diverged.")
    samples = tuple(sample_order)
    if set(point_counts) != set(samples):
        _mismatch("Terminal point counts do not exactly cover the sample order.")
    return MaterializedTerminalSourceBinding(
        task_key=task_key,
        rule_id=rule_id,
        template=template,
        x_metric=x_metric,
        y_metric=y_metric,
        raw_sources=tuple(
            SourceArtifactBinding(path=item.path, sha256=item.sha256)
            for item in source_attestation.selected_sources
        ),
        prepared_source=prepared,
        terminal_source=prepared,
        sample_order=samples,
        point_counts=tuple((sample, point_counts[sample]) for sample in samples),
    )


def _mismatch(message: str) -> None:
    raise TerminalSourceBindingError(
        "terminal_source_binding_contract_mismatch",
        message,
    )


__all__ = ["terminal_binding_from_preparation_attestation"]
