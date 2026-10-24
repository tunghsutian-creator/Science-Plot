"""Finite Mach-O diagnostic policy controls; no private inputs."""
from copy import deepcopy
import inspect
from pathlib import Path
import plistlib
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.verification import evidence_runtime as runtime
from sciplot_core.verification import native_probe_boundary as policy
from sciplot_core.verification.evidence_identity import digest


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    tool, target = tmp_path / 'llvm-otool', tmp_path / 'target'
    for path in (tool, target):
        path.write_bytes(b'\xcf\xfa\xed\xfe' + path.name.encode())
    system = tmp_path / 'system.plist'
    system.write_bytes(plistlib.dumps(dict(ProductName='TestOS', ProductVersion='1', ProductBuildVersion='A')))
    monkeypatch.setattr(policy, 'inspector_path', lambda: tool)
    monkeypatch.setattr(policy, '_SYSTEM', system)
    monkeypatch.setattr(policy, 'owned_caller', lambda *args: policy.owner_identity(*args))
    return tool, target, system


def invocation(tool, target, **changes):
    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=policy.probe_environment())
    kwargs.update(changes)
    # Model the original bound fields, independent of an active observer port.
    return inspect.BoundArguments(inspect.Signature(),
        dict(self=None, args=[str(tool), '-L', str(target)], **kwargs))


def attempt_for(value):
    return {'argv_sha256': value['argv_sha256'], 'expected_executable_sha256': value['tool_sha256']}


def test_exact_inspection_requires_native_domain_tool_target_and_system(inputs):
    tool, target, system = inputs
    value = policy.native_probe_call(invocation(tool, target))
    records = {digest(str(p)): {'sha256': policy.file_sha256(p)} for p in inputs}
    assert policy.native_probe_bound(value, records, attempt_for(value))
    for path in inputs:
        missing = {k: v for k, v in records.items() if k != digest(str(path))}
        assert not policy.native_probe_bound(value, missing, attempt_for(value))
    target.write_bytes(b'changed')
    records[digest(str(target))]['sha256'] = policy.file_sha256(target)
    assert not policy.native_probe_bound(value, records, attempt_for(value))


@pytest.mark.parametrize('change', ['loader', 'shell', 'executable', 'cwd', 'fds', 'binary', 'mode', 'relative', 'non_macho', 'callsite'])
def test_unreviewed_native_invocation_cannot_obtain_boundary(inputs, monkeypatch, change):
    tool, target, _ = inputs
    kwargs = {'loader': {'env': {**policy.probe_environment(), 'DYLD_INSERT_LIBRARIES': '/injected'}},
              'shell': {'shell': True}, 'executable': {'executable': str(tool)},
              'cwd': {'cwd': str(target.parent)}, 'fds': {'pass_fds': (5,)}}.get(change, {})
    bound = invocation(tool, target, **kwargs)
    if change == 'binary':
        bound.arguments['args'][0] = '/usr/bin/otool'
    elif change == 'mode':
        bound.arguments['args'][1] = '-h'
    elif change == 'relative':
        bound.arguments['args'][2] = 'target'
    elif change == 'non_macho':
        target.write_text('ordinary bytes')
    elif change == 'callsite':
        monkeypatch.setattr(policy, 'owned_caller', lambda *args: None)
    assert policy.native_probe_call(bound) is None


@pytest.mark.parametrize('field', ['owner', 'mode', 'environment_sha256', 'tool_sha256', 'tool_path_sha256', 'system_sha256', 'extra'])
def test_altered_diagnostic_descriptor_is_rejected(inputs, field):
    tool, target, _ = inputs
    value = deepcopy(policy.native_probe_call(invocation(tool, target)))
    actual_attempt = attempt_for(value)
    value[field] = 'changed'
    records = {digest(str(p)): {'sha256': policy.file_sha256(p)} for p in inputs}
    assert not policy.native_probe_bound(value, records, actual_attempt)


@pytest.mark.parametrize('field', ['argv_sha256', 'expected_executable_sha256'])
def test_native_descriptor_cannot_replace_actual_launch_identity(inputs, field):
    tool, target, _ = inputs
    value = policy.native_probe_call(invocation(tool, target))
    actual_attempt = attempt_for(value)
    actual_attempt[field] = 'changed'
    records = {digest(str(p)): {'sha256': policy.file_sha256(p)} for p in inputs}
    assert not policy.native_probe_bound(value, records, actual_attempt)


def test_host_metadata_uses_actual_bound_build_and_kernel_without_probe(inputs, monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: pytest.fail('host spawned a probe'))
    _, _, system = inputs
    host = policy.system_identity(system)
    assert host['system'] == dict(ProductName='TestOS', ProductVersion='1', ProductBuildVersion='A')
    assert host['machine'] == policy.os.uname().machine
    assert host['kernel']['release'] == policy.os.uname().release


@pytest.mark.parametrize('value', [[], {}, {'ProductName': 'OS', 'ProductVersion': '1', 'ProductBuildVersion': ''}])
def test_unknown_host_build_remains_blocked(tmp_path, value):
    path = tmp_path / 'system'
    path.write_bytes(plistlib.dumps(value))
    with pytest.raises(ValueError, match='malformed'):
        policy.system_identity(path)


@pytest.mark.comprehensive
@pytest.mark.skipif(sys.platform != 'darwin', reason='finite CLT inspector is macOS-specific')
def test_actual_clt_inspector_uses_closed_environment_and_bound_native_target():
    from sciplot_core.verification.evidence_runtime import native_dependencies
    tool = policy.inspector_path()
    bindings = {}
    files = native_dependencies([], executable=Path(sys.executable), environment=dict(policy.os.environ), bindings=bindings)
    assert tool in files and Path(sys.executable).resolve() in files
    assert bindings[digest(str(tool))] == policy.file_sha256(tool)


# Generated TestOS/Mach-O component controls, never native acceptance.
_STATIC_MACHO_MAGIC = b'\xcf\xfa\xed\xfe'


class _StaticInspectionWorld:
    def __init__(self, root):
        self.tool, self.main = root / 'otool', root / 'main.so'
        self.extra_source, self.system = root / 'source.py', root / 'system.plist'
        self.helper = root / 'helper.dylib'
        self.extra_source.write_text('value = 1\n')
        self.set_system('A')
        for path in (self.tool, self.main, self.helper):
            path.write_bytes(_STATIC_MACHO_MAGIC + path.name.encode())
        self.tool.chmod(0o755)
        self.calls = []
        self.dependencies = {}
        self.loads = {}
        self.fail = self.drift = self.tool_drift = False

    def set_system(self, build):
        self.system.write_bytes(plistlib.dumps(dict(ProductName='TestOS', ProductVersion='1', ProductBuildVersion=build)))

    def install(self, patch, *, platform='darwin'):
        # Generated component prerequisite only; real sys/observer/host stay intact.
        patch.setattr(runtime, 'sys', SimpleNamespace(platform=platform))
        patch.setattr(policy, '_TOOL', self.tool)
        patch.setattr(policy, '_SYSTEM', self.system)
        patch.setattr(runtime, 'inspector_path', policy.inspector_path)
        # Replace only this module reference, never global subprocess.run.
        patch.setattr(runtime, 'subprocess', SimpleNamespace(run=self.inspect))

    def inspect(self, command, **kwargs):
        self.calls.append(tuple(command))
        target = Path(command[-1])
        if self.fail and target == self.main:
            raise subprocess.CalledProcessError(1, command, stderr='original inspection failure')
        if self.drift and target == self.main:
            target.write_bytes(_STATIC_MACHO_MAGIC + b'mutated during actual inspection')
        if self.tool_drift and target == self.main:
            self.tool.write_bytes(_STATIC_MACHO_MAGIC + b'inspector mutated during inspection')
        text = (str(target) + ':\n' + ''.join('\t' + name + ' (compatibility version 1)\n'
                for name in self.dependencies.get(target, []))) if command[1] == '-L' else self.loads.get(target, '')
        return SimpleNamespace(stdout=text)

    def bindings(self):
        return {digest(str(path.resolve())): file_sha256(path) for path in
                (Path(runtime.__file__), Path(policy.__file__), self.extra_source)}

    def read(self, memo, environment=None, paths=None, bindings=None):
        result, aliases = {}, {}
        result.update(self.bindings() if bindings is None else bindings)
        found = runtime.native_dependencies([str(self.main)] if paths is None else paths,
                    executable=self.main, environment=environment or {}, bindings=result,
                    aliases=aliases, repo_root=self.main.parent, _inspections=memo)
        return found, result, aliases


def _static_inspection_engine():
    memo = runtime._StaticNativeInspections()
    # Pure generated engine seam only; the actual outer observer stays enabled.
    memo._unobserved = lambda environment: True
    return memo


def test_static_inspection_raw_pairs_hit_and_all_fresh_key_inputs_invalidate(tmp_path, monkeypatch):
    world, memo = _StaticInspectionWorld(tmp_path), _static_inspection_engine()
    observations = []
    with monkeypatch.context() as patch:
        world.install(patch)
        first = world.read(memo)
        observations.append(len(world.calls))
        second = world.read(memo)
        observations.append(len(world.calls))
        world.main.write_bytes(_STATIC_MACHO_MAGIC + b'new target bytes')
        world.read(memo)
        observations.append(len(world.calls))
        world.tool.write_bytes(_STATIC_MACHO_MAGIC + b'new tool bytes')
        world.read(memo)
        observations.append(len(world.calls))
        world.extra_source.write_text('value = 2\n')
        world.read(memo)
        observations.append(len(world.calls))
        world.set_system('B')
        world.read(memo)
        observations.append(len(world.calls))
        world.read(memo, {'DYLD_FRAMEWORK_PATH': str(tmp_path / 'fresh-loader')})
        observations.append(len(world.calls))
        original_host = policy.system_identity
        def changed_kernel(path):
            value = original_host(path)
            value['kernel']['release'] += '-generated-counterexample'
            return value
        patch.setattr(policy, 'system_identity', changed_kernel)
        world.read(memo)
        observations.append(len(world.calls))
    assert first == second
    assert observations == [4, 6, 10, 14, 18, 22, 26, 30]


def test_static_inspection_alias_missing_resolution_and_non_system_inspector_stay_fresh(tmp_path, monkeypatch):
    world, memo = _StaticInspectionWorld(tmp_path), _static_inspection_engine()
    old, new, preferred = tmp_path / 'old', tmp_path / 'new', tmp_path / 'preferred'
    for parent in (old, new, preferred):
        parent.mkdir()
    for parent in (old, new):
        (parent / 'lib.dylib').write_bytes(_STATIC_MACHO_MAGIC + parent.name.encode())
    alias = tmp_path / 'current'
    alias.symlink_to(old, target_is_directory=True)
    world.dependencies[world.main] = ['@rpath/lib.dylib']
    world.loads[world.main] = ''.join('cmd LC_RPATH\ncmdsize 40\npath ' + str(path) + ' (offset 12)\n'
                                    for path in (preferred, alias))
    with monkeypatch.context() as patch:
        world.install(patch)
        first = world.read(memo)
        alias.unlink()
        alias.symlink_to(new, target_is_directory=True)
        second = world.read(memo)
        (preferred / 'lib.dylib').write_bytes(_STATIC_MACHO_MAGIC + b'new preferred')
        try:
            world.read(memo)
        except ValueError as error:
            ambiguous = str(error)
        else:
            ambiguous = ''
        world.main.write_bytes(_STATIC_MACHO_MAGIC + b'one explicit rpath')
        world.loads[world.main] = 'cmd LC_RPATH\ncmdsize 40\npath ' + str(preferred) + ' (offset 12)\n'
        # A new tool with a non-system dependency cannot admit raw memo hits.
        world.tool.write_bytes(_STATIC_MACHO_MAGIC + b'non-system tool')
        world.dependencies[world.tool] = [str(world.helper)]
        before = len(world.calls)
        world.read(memo)
        first_unclosed = len(world.calls) - before
        before = len(world.calls)
        world.read(memo)
        second_unclosed = len(world.calls) - before
    assert old / 'lib.dylib' in first[0] and new / 'lib.dylib' in second[0]
    assert first[2][digest(str(alias / 'lib.dylib'))] != second[2][digest(str(alias / 'lib.dylib'))]
    assert 'unresolved or ambiguous' in ambiguous
    assert first_unclosed == second_unclosed and first_unclosed >= 6


def test_static_inspection_failures_source_mismatch_rights_and_final_activation_never_cache(tmp_path, monkeypatch):
    world, memo = _StaticInspectionWorld(tmp_path), _static_inspection_engine()
    with pytest.raises(subprocess.CalledProcessError, match='non-zero'):
        with monkeypatch.context() as patch:
            world.install(patch)
            world.fail = True
            world.read(memo)
    assert memo.outputs == {}
    world.fail = False
    with pytest.raises(ValueError, match='changed during dependency'):
        with monkeypatch.context() as patch:
            world.install(patch)
            world.drift = True
            world.read(memo)
    assert memo.outputs == {}
    world.drift = False
    world.tool_drift = True
    with pytest.raises(ValueError, match='inspector changed during dependency'):
        with monkeypatch.context() as patch:
            world.install(patch)
            world.read(memo)
    assert memo.outputs == {}
    world.tool_drift = False
    invalid = world.bindings()
    invalid[digest(str(Path(policy.__file__).resolve()))] = 'stale source binding'
    with pytest.raises(ValueError, match='current source binding'):
        with monkeypatch.context() as patch:
            world.install(patch)
            world.read(memo, bindings=invalid)
    assert memo.outputs == {}
    world.tool.chmod(0o644)
    with pytest.raises(ValueError, match='inspector is unavailable'):
        with monkeypatch.context() as patch:
            world.install(patch)
            world.read(memo)
    assert memo.outputs == {}
    world.tool.chmod(0o755)
    with pytest.raises(ValueError, match='fixed probe environment'):
        with monkeypatch.context() as patch:
            world.install(patch)
            original_environment = runtime.probe_environment()
            patch.setattr(runtime, 'probe_environment', lambda: {**original_environment, 'LANG': 'other'})
            world.read(memo)
    assert memo.outputs == {}
    with monkeypatch.context() as patch:
        world.install(patch)
        world.read(memo)
    admitted = iter((True, True, False))
    memo._unobserved = lambda environment: next(admitted)
    with pytest.raises(ValueError, match='scope changed before discovery completed'):
        with monkeypatch.context() as patch:
            world.install(patch)
            world.read(memo)


def test_static_inspection_requested_observation_keeps_real_probe_calls_and_no_reusable_pair(tmp_path, monkeypatch):
    world, memo = _StaticInspectionWorld(tmp_path), runtime._StaticNativeInspections()
    with monkeypatch.context() as patch:
        world.install(patch)
        world.read(memo, {'SCIPLOT_PRIVATE_AUDIT_DIR': ''})
        world.read(memo, {'SCIPLOT_PRIVATE_AUDIT_DIR': ''})
    assert memo.outputs == {} and len(world.calls) == 8


def test_static_inspection_generated_hot_key_cost_is_explicit(tmp_path, monkeypatch):
    world, memo = _StaticInspectionWorld(tmp_path), _static_inspection_engine()
    paths = []
    for number in range(200):
        path = tmp_path / f'node{number}.so'
        path.write_bytes(_STATIC_MACHO_MAGIC + str(number).encode())
        paths.append(str(path))
    with monkeypatch.context() as patch:
        world.install(patch)
        start = time.perf_counter()
        world.read(memo, paths=paths)
        cold = time.perf_counter() - start
        count = len(world.calls)
        start = time.perf_counter()
        world.read(memo, paths=paths)
        hot = time.perf_counter() - start
        hot_calls = len(world.calls) - count
    assert hot_calls == 2  # The inspector itself is always actually called.
    print({'generated_targets': 201, 'cold_seconds': cold, 'hot_seconds': hot,
           'hot_real_component_calls': hot_calls, 'not_end_to_end_speedup': True})


def test_static_inspection_record_context_restores_on_errors_nested_reuse_and_before_checks(tmp_path, monkeypatch):
    from sciplot_core.verification import changed_evidence as evidence

    root = tmp_path / 'repo'
    root.mkdir()
    inner = root / '.tmp_verify/inner'
    inner.mkdir(parents=True)
    plan = {'comparison': {}, 'checks': [{'check_id': 'generated', 'command': ['generated']}]}
    states = []
    original = evidence._RECORD_PREPARATION.get()

    def nested_prepare(current, repo, directory):
        states.append(('prepare', directory.name, evidence._RECORD_PREPARATION.get()))
        if directory.name == 'outer':
            evidence.run_evidence_checks(current, repo_root=repo, directory=inner, reuse=True)
            states.append(('restored_outer', evidence._RECORD_PREPARATION.get()))
        raise ValueError('generated prepare rejection')

    with monkeypatch.context() as patch:
        patch.setattr(evidence, '_prepare_specs', nested_prepare)
        blocked = evidence.run_evidence_checks(plan, repo_root=root, directory=root / '.tmp_verify/outer', reuse=False)
    after_nested = evidence._RECORD_PREPARATION.get()

    def prepared(current, repo, directory):
        states.append(('prepare_check', evidence._RECORD_PREPARATION.get()))
        return [{'command': ['generated'], 'scope': {}}]

    def stop_before_launch(**kwargs):
        states.append(('before_actual_checks', evidence._RECORD_PREPARATION.get()))
        raise ValueError('generated stop before launch')

    with monkeypatch.context() as patch:
        patch.setattr(evidence, '_prepare_specs', prepared)
        patch.setattr(evidence, 'start_run', stop_before_launch)
        stopped = evidence.run_evidence_checks(plan, repo_root=root, directory=root / '.tmp_verify/checks', reuse=False)
    after_checks = evidence._RECORD_PREPARATION.get()
    assert blocked['status'] == stopped['status'] == 'BLOCKED'
    assert original is after_nested is after_checks is False
    assert states == [('prepare', 'outer', True), ('prepare', 'inner', False),
                      ('restored_outer', True), ('prepare_check', True), ('before_actual_checks', False)]



@pytest.mark.parametrize('platform', ['linux', 'win32'])
def test_static_inspection_unsupported_component_platform_keeps_real_guard(tmp_path, monkeypatch, platform):
    world, memo = _StaticInspectionWorld(tmp_path), _static_inspection_engine()
    with pytest.raises(ValueError, match='requires macOS'):
        with monkeypatch.context() as patch:
            world.install(patch, platform=platform)
            world.read(memo)
    assert world.calls == [] and memo.outputs == {}
