"""Explicit expert host setup over generated original CSVs for executor controls."""
from contextlib import contextmanager
import csv

from sciplot_core.host_grants import (
    EXECUTE_TRANSFORM, HostRegistry, SourceScope, execution_context, using_host_registry,
)


@contextmanager
def trusted_external(executor, datasets, directory):
    source = directory.resolve() / "host-granted-original.csv"
    columns = datasets["A"]["columns"]
    with source.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([c["label"] for c in columns.values()])
        writer.writerow([c["unit"] for c in columns.values()])
        writer.writerows(zip(*(c["values"] for c in columns.values()), strict=True))
    scope = SourceScope.local_file("A", source)
    datasets["A"]["provenance"]["sources"][0]["sha256"] = scope.sha256
    store = HostRegistry(directory.resolve() / "explicit-host/grants.json")
    store.grant("fixed", executor.to_dict("fixed"), [scope], action=EXECUTE_TRANSFORM)
    with using_host_registry(store), execution_context([scope]):
        yield store, scope
