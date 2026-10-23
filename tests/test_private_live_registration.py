"""Deterministic lifecycle models; these tests do not establish kernel evidence."""
from dataclasses import replace
import json
import os
import threading
from types import SimpleNamespace

import pytest

from sciplot_core.plot_protocol import paths
from sciplot_core.verification import private_native_exit_port as port
from sciplot_core.verification.native_exit_boundary import ProcessIdentity, validate_actor_launch
from sciplot_core.verification.private_process_boundaries import ZERO, frame_digest, source_hashes


def _scene(tmp_path, monkeypatch, prefix):
    """Replay the full/short-prefix difference without timing or real processes."""
    primary = ProcessIdentity(os.getpid(), os.getppid(), os.getuid(), 1, 1,
                              '/modeled/Python', '/tmp', 'a' * 64)
    parent = replace(primary, pid=primary.pid + 100_000, ppid=primary.pid, start_sec=2)
    peer = replace(parent, pid=parent.pid + 1, ppid=parent.pid, start_sec=3)
    epoch, token, node = 'a' * 32, 'b' * 32, 'modeled-live-item'
    directory = tmp_path / 'audit'
    directory.mkdir()
    stream = directory / (epoch + '.jsonl')
    frames, history_reads, observations = [], [], []
    state = {'parent_exited': False, 'record_failed': False}
    observer = SimpleNamespace(epoch=epoch, directory=directory,
        guard=SimpleNamespace(active=False),
        _audit_socket_scope=({'sockets': ['/tmp/modeled-source-owned.sock'], 'test_nodeid': node}, {}))

    def record(value, **kwargs):
        if state['record_failed'] and value['event'] == 'native_registration_request':
            return None
        if value['event'] == 'native_registration_request' and 'mutate_request' in state:
            state['mutate_request'](value['request'])
        row = {**value, 'pid': primary.pid, 'epoch': epoch, 'sequence': len(frames),
               'monotonic_ns': len(frames) + 1, 'nodeid': value.get('nodeid', node + ' (call)'),
               'previous_sha256': frames[-1]['sha256'] if frames else ZERO}
        row['sha256'] = frame_digest(row)
        with stream.open('a') as output:
            output.write(json.dumps(row, sort_keys=True) + '\n')
        frames.append(row)
        if value['event'] == 'native_registration_request' and 'transform_return' in state:
            return state['transform_return'](row)
        return row

    observer.record = record
    record({'event': 'process_start', 'observer_sources_sha256': source_hashes()})
    attempt = record({'event': 'spawn_attempt', 'child_token': token, 'nodeid': node})
    record({'event': 'child_spawn', 'child_token': token, 'child_pid': parent.pid})
    for index in range(prefix):
        record({'event': 'os.scandir', 'modeled_unrelated_prefix': index})
    def identity(pid):
        if pid == peer.pid:
            return replace(peer, ppid=1) if state['parent_exited'] else peer
        if pid == parent.pid and not state['parent_exited']:
            return parent
        if pid == primary.pid:
            return primary
        raise ProcessLookupError('modeled CLI finished')

    class Sensor:
        def __init__(self):
            self.binding = {'watcher_identity': primary.to_dict()}

        def register(self, generation, expected):
            state['sensor_calls'] = state.get('sensor_calls', 0) + 1
            if state.get('drift_at_sensor'):
                state['parent_exited'] = True
            before = identity(expected.pid)
            fact = {'generation': generation, 'identity': expected.to_dict(),
                    'status': 'REGISTERED' if before == expected else 'UNKNOWN',
                    'before': before.to_dict()}
            observations.append(fact)
            return fact

    instance = port._Port.__new__(port._Port)
    instance.observer, instance.discovered = observer, set()
    instance.sensor, instance.lock, instance.requests = Sensor(), threading.RLock(), {}
    instance.directory = tmp_path / 'native-exits'
    instance.directory.mkdir()
    instance.launches = {token: (SimpleNamespace(pid=parent.pid), attempt, parent, False)}
    endpoint = {'device': 1, 'inode': 2, 'uid': primary.uid, 'ctime_ns': 3, 'mode': 0o600}
    owner = {'pid': peer.pid, 'device': 1, 'inode': 2, 'instance_id': 'modeled-instance'}

    class Connection:
        def __init__(self, *args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, timeout):
            pass

        def connect(self, name):
            assert observer.guard.active

        def sendall(self, data):
            pytest.fail('An observer must not send a business request')

    original_rows = port._epoch_rows

    def history(bound_directory, bound_epoch):
        rows = original_rows(bound_directory, bound_epoch)
        history_reads.append(len(rows))
        if prefix:
            # A deterministic schedule: the CLI finishes during growing history
            # admission, after the actual held-parent and kernel-peer snapshot.
            state['parent_exited'] = True
        return rows

    monkeypatch.setattr(port, '_epoch_rows', history)
    monkeypatch.setattr(port, 'read_identity', identity)
    monkeypatch.setattr(port, 'endpoint_identity', lambda *args, **kwargs: (None, endpoint))
    monkeypatch.setattr(port, 'kernel_peer_pid', lambda connection: peer.pid)
    monkeypatch.setattr(port.socket, 'socket', Connection)
    monkeypatch.setattr(paths, 'read_owner', lambda path: owner)
    return SimpleNamespace(instance=instance, state=state, frames=frames, peer=peer,
        primary=primary, token=token, epoch=epoch, observations=observations,
        history_reads=history_reads, original_rows=original_rows)


@pytest.mark.parametrize('prefix', [0, 1024])
def test_live_kernel_observation_is_independent_of_accumulated_history(tmp_path, monkeypatch, prefix):
    scene = _scene(tmp_path, monkeypatch, prefix)
    scene.instance.discover()
    assert len(scene.observations) == 1
    assert scene.observations[0]['status'] == 'REGISTERED'
    assert scene.observations[0]['identity'] == scene.peer.to_dict()
    if prefix:
        assert scene.history_reads == []
    request = next(iter(scene.instance.requests.values()))['request']
    # Final source admission still checks the complete generated history and
    # fails if the source exclusion is absent. It is not a kernel certificate.
    rows = scene.original_rows(scene.instance.observer.directory, scene.epoch)
    assert validate_actor_launch(request, rows, scene.primary.pid, {scene.epoch + ':' + scene.token})
    assert not validate_actor_launch(request, rows, scene.primary.pid, set())


def _capture_source_request(scene):
    register, captured = scene.instance.register, []
    scene.instance.register = lambda request, **kwargs: captured.append((request, kwargs['recorded']))
    scene.instance.discover()
    scene.instance.register = register
    assert len(captured) == 1 and scene.observations == []
    return register, *captured[0]


def test_copied_real_frame_and_owner_do_not_authorize_a_foreign_caller(tmp_path, monkeypatch):
    scene = _scene(tmp_path, monkeypatch, 0)
    register, request, recorded = _capture_source_request(scene)
    with pytest.raises(ValueError, match='actual current source record'):
        register(request, recorded=recorded)
    assert scene.observations == [] and scene.instance.requests == {}
    assert not list(scene.instance.directory.iterdir())


def test_queue_retains_complete_history_admission_and_strict_identity_refusal(tmp_path, monkeypatch):
    scene = _scene(tmp_path, monkeypatch, 1024)
    register, request, _ = _capture_source_request(scene)
    register(request)
    assert scene.history_reads and scene.history_reads[0] > 1024
    assert len(scene.observations) == 1
    assert scene.observations[0]['status'] == 'UNKNOWN'
    assert scene.observations[0]['before']['ppid'] == 1


@pytest.mark.parametrize('corruption', ['missing', 'pid', 'epoch', 'node', 'hash', 'request_copy'])
def test_failed_or_replaced_source_record_never_registers_an_actor(tmp_path, monkeypatch, corruption):
    scene = _scene(tmp_path, monkeypatch, 0)
    if corruption == 'missing':
        scene.state['record_failed'] = True
    else:
        def corrupt(row):
            result = dict(row)
            if corruption == 'pid':
                result['pid'] += 1
            elif corruption == 'epoch':
                result['epoch'] = 'f' * 32
            elif corruption == 'node':
                result['test_nodeid'] = 'another-item'
            elif corruption == 'request_copy':
                result['request'] = dict(result['request'])
            result['sha256'] = frame_digest({key: value for key, value in result.items() if key != 'sha256'})
            if corruption == 'hash':
                result['sha256'] = 'f' * 64
            return result
        scene.state['transform_return'] = corrupt
    scene.instance.discover()
    assert scene.observations == [] and scene.instance.requests == {}
    assert scene.history_reads == []
    assert not list(scene.instance.directory.iterdir())


def test_pre_sensor_parent_drift_remains_unknown_and_is_not_retried(tmp_path, monkeypatch):
    scene = _scene(tmp_path, monkeypatch, 0)
    scene.state['drift_at_sensor'] = True
    scene.instance.discover()
    scene.instance.discover()
    assert len(scene.observations) == 1
    assert scene.observations[0]['status'] == 'UNKNOWN'
    assert scene.observations[0]['before']['ppid'] == 1
    assert scene.history_reads == []


def test_live_record_cannot_change_the_held_actor_management_responsibility(tmp_path, monkeypatch):
    scene = _scene(tmp_path, monkeypatch, 0)
    scene.state['mutate_request'] = lambda request: request['actor'].__setitem__('default_owned', True)
    scene.instance.discover()
    assert scene.observations == [] and scene.instance.requests == {}
    assert scene.state.get('sensor_calls', 0) == 0
    assert not list(scene.instance.directory.iterdir())


@pytest.mark.parametrize('change', [{'ppid': 999}, {'uid': os.getuid() + 1}])
def test_record_mutation_cannot_register_a_foreign_peer_under_a_real_caller(tmp_path, monkeypatch, change):
    scene = _scene(tmp_path, monkeypatch, 0)
    scene.state['mutate_request'] = lambda request: request['identity'].update(change)
    scene.instance.discover()
    assert scene.observations == [] and scene.instance.requests == {}
    assert scene.state.get('sensor_calls', 0) == 0
    assert not list(scene.instance.directory.iterdir())
