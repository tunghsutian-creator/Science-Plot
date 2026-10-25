# Scientific executor host grants

Scientific executor descriptors seal calculations; they grant no operating-system
rights. `scientific_executors` and `executor.registration` can reference only a
host-granted identity. Full legacy declarations remain readable and retain their
original seals. A grant is checked before an external process is launched, including
cold rebuild/recovery. Reading already adopted scientific results does not run an
executor. An unknown prior outcome is never automatically retried.

The host expert explicitly configures the private host registry with:

```
skill/scripts/sciplot host grant --id fixed-normalizer \
  --registration /absolute/registration.json --action transform.execute \
  --source A=/absolute/original.csv
skill/scripts/sciplot host list
skill/scripts/sciplot host revoke --id fixed-normalizer
```

The equivalent `python -m sciplot_core.host_grants` module uses the same implementation.

The default file is `~/.sciplot/host-executors.json`, in a private user-owned
directory. The local administrative entry supports an explicit deployment/test
`--registry`; scientific requests, RPC/MCP methods and environment allow flags
cannot select a registry or mint grants. Trusted Python composition may inject a
`HostRegistry` with `using_host_registry`. Each grant binds one exact executor
identity, the `transform.execute` action and exact original source ID/path/SHA
scopes. Every contributing input must be in scope, including transformed inputs.

This is an application authorization boundary, not an OS sandbox. A host-approved
script still has the normal rights of its OS user, including network/file access
available to that user. The host must trust that code. SciPlot neither changes
system settings nor treats hashes, timeouts, JSON schemas or `side_effect_free`
declarations as evidence of OS isolation. A process already running under the host
user can administer their own registry; this does not defend against that user.
