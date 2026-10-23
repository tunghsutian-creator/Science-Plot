"""A queued declaration cannot authorize an unrelated process or exit."""
import json
from types import SimpleNamespace

import pytest

from sciplot_core.verification.private_observer import ZERO, frame_digest, source_hashes
from sciplot_core.verification.private_native_exit_port import _live_request, _parent_exit, validated_exits


def producer(tmp_path, pid):
    epoch, token = "a" * 32, "b" * 32
    frame = {"event": "process_start", "pid": pid, "sequence": 0, "previous_sha256": ZERO,
             "observer_sources_sha256": source_hashes()}
    frame["sha256"] = frame_digest(frame)
    (tmp_path / (epoch + ".jsonl")).write_text(json.dumps(frame) + "\n")
    return {"epoch": epoch, "token": token, "generation": epoch + ":" + token, "actor": {}}


def test_unrelated_parent_cannot_register_a_foreign_pid(tmp_path):
    request = producer(tmp_path, 101)
    with pytest.raises(ValueError, match="actual source producer's child"):
        _live_request(tmp_path, request, SimpleNamespace(pid=301, ppid=201))


def test_current_source_hashes_and_parent_pid_are_insufficient_without_actual_server_spawn(tmp_path):
    request = producer(tmp_path, 101)
    with pytest.raises(ValueError, match="actual source-owned server launch"):
        _live_request(tmp_path, request, SimpleNamespace(pid=301, ppid=101))


def test_request_cannot_select_an_external_stream(tmp_path):
    with pytest.raises(ValueError, match="source epoch/token"):
        _live_request(tmp_path, {"epoch": "../outside", "token": "b" * 32}, SimpleNamespace(pid=301, ppid=101))


@pytest.mark.parametrize("primary", [100, 200])
def test_unclosed_or_different_primary_sensor_never_supplies_exit_status(primary):
    declared = {"event": "native_exit_sensor_start", "pid": 100, "binding": {"watcher_identity": {"pid": 100}}}
    assert validated_exits([declared], primary=primary) == {}


@pytest.mark.parametrize("returncode", [None, 0, -15])
def test_orphan_lineage_requires_genuine_finish_and_actual_normal_parent_exit(tmp_path, returncode):
    parent_epoch, ancestor_epoch, token = "a" * 32, "c" * 32, "b" * 32

    def write(epoch, frames):
        previous = ZERO
        for sequence, row in enumerate(frames):
            row.update(sequence=sequence, previous_sha256=previous)
            row["sha256"] = frame_digest(row)
            previous = row["sha256"]
        (tmp_path / (epoch + ".jsonl")).write_text("".join(json.dumps(row) + "\n" for row in frames))

    parent = [{"event": "process_start", "pid": 101, "observer_sources_sha256": source_hashes(),
               "parent_epoch": ancestor_epoch, "child_token": token},
              {"event": "process_finish", "pid": 101, "recorded_events": 1, "lost_events": 0}]
    ancestor = [{"event": "process_start", "pid": 100, "observer_sources_sha256": source_hashes()}]
    if returncode is not None:
        ancestor.append({"event": "child_exit", "child_pid": 101, "child_token": token, "returncode": returncode})
    write(parent_epoch, parent)
    write(ancestor_epoch, ancestor)
    if returncode == 0:
        assert _parent_exit(tmp_path, parent_epoch, 101) == {
            "producer_epoch": parent_epoch, "producer_finish_sha256": parent[-1]["sha256"],
            "ancestor_epoch": ancestor_epoch, "actual_parent_exit_sha256": ancestor[-1]["sha256"]}
    else:
        with pytest.raises(ValueError, match="actual normal parent exit"):
            _parent_exit(tmp_path, parent_epoch, 101)


def _launch_model(tmp_path):
    from dataclasses import replace
    import os
    from pathlib import Path
    import sys
    from sciplot_core.verification import private_native_exit_port as port
    from sciplot_core.verification.native_exit_boundary import ProcessIdentity
    from sciplot_core.verification.private_process_boundaries import executable_hash

    producer_image = str(tmp_path / "modeled-runtime" / "Python")
    producer = ProcessIdentity(os.getpid(), 1, os.getuid(), 1, 1, producer_image, str(tmp_path), "b" * 64)
    entry = ProcessIdentity(31999, producer.pid, producer.uid, 2, 3,
        str(Path(sys.executable).resolve()), str(tmp_path), executable_hash(sys.executable))
    settled = replace(entry, executable=producer.executable, executable_sha256=producer.executable_sha256)
    return port, producer, entry, settled


def test_modeled_launch_resolves_only_the_same_generation_actual_image(tmp_path, monkeypatch):
    import time

    port, producer, entry, settled = _launch_model(tmp_path)
    for identities in ([entry, settled], [settled]):
        reads = list(identities)
        def read(pid, reads=reads):
            return producer if pid == producer.pid else reads.pop(0)
        monkeypatch.setattr(port, "read_identity", read)
        assert port._server_identity(entry.pid, str(tmp_path / "engine.sock"), time.monotonic() + 1) == settled
        assert not reads


def test_modeled_launch_rejects_generation_drift_or_unbound_images(tmp_path, monkeypatch):
    from dataclasses import replace
    import time

    port, producer, entry, settled = _launch_model(tmp_path)
    changes = ({"pid": entry.pid + 1}, {"ppid": entry.ppid + 1}, {"uid": entry.uid + 1},
        {"start_sec": entry.start_sec + 1}, {"start_usec": entry.start_usec + 1},
        {"cwd": str(tmp_path / "other")}, {"executable": str(tmp_path / "other" / "Python")},
        {"executable_sha256": "c" * 64})
    for change in changes:
        reads = [entry, replace(settled, **change)]
        def read(pid, reads=reads):
            return producer if pid == producer.pid else reads.pop(0)
        monkeypatch.setattr(port, "read_identity", read)
        with pytest.raises(ValueError, match="generation or launch image changed"):
            port._server_identity(entry.pid, str(tmp_path / "engine.sock"), time.monotonic() + 1)


def test_unsettled_or_unreadable_launch_cannot_submit_a_registration(tmp_path, monkeypatch):
    port, producer, entry, settled = _launch_model(tmp_path)
    for current in (entry, settled):
        monkeypatch.setattr(port, "read_identity", lambda pid, current=current: producer if pid == producer.pid else current)
        with pytest.raises(ValueError, match="did not settle"):
            port._server_identity(entry.pid, str(tmp_path / "engine.sock"), -1)
    directory = tmp_path / "native-exits"
    directory.mkdir()
    queue = directory / "requests"
    queue.touch()
    recorded = []
    observer = SimpleNamespace(directory=tmp_path, epoch="a" * 32,
        record=lambda value, **kwargs: recorded.append(value))
    for failure in (PermissionError("modeled permission"), ProcessLookupError("modeled exit")):
        def unreadable(pid, failure=failure):
            if pid == producer.pid:
                return producer
            raise failure
        monkeypatch.setattr(port, "read_identity", unreadable)
        assert port.register_server(observer, SimpleNamespace(pid=entry.pid), "b" * 32,
            {"socket": str(tmp_path / "engine.sock")}) is False
        assert queue.read_bytes() == b"" and recorded == []


def test_startup_binding_separates_entrypoint_from_kernel_image():
    from copy import deepcopy
    from sciplot_core.verification.private_native_exit_port import _startup_bound

    runtime = {"loaded_core_sha256": ["b" * 64, "c" * 64], "kind": "modeled pure data"}
    request = {"epoch": "producer", "token": "launch", "identity": {"pid": 3, "ppid": 2,
        "uid": 501, "executable": "/modeled/runtime/Python", "executable_sha256": "b" * 64}}
    binding = {"watcher_identity": {"pid": 1, "uid": 501, "executable": "/modeled/runtime/Python",
        "executable_sha256": "b" * 64}, "native_images": {"python_core": {"sha256": "c" * 64}}}
    frames = [{"event": "process_start", "pid": pid, "epoch": epoch,
        "executable_sha256": "a" * 64, "python_runtime": deepcopy(runtime), **extra}
        for pid, epoch, extra in ((1, "primary", {}), (2, "producer", {}),
            (3, "child", {"parent_epoch": "producer", "child_token": "launch", "continuation": None}))]
    attempt = {"expected_executable_sha256": "a" * 64}
    assert _startup_bound(frames, request, attempt, binding)
    assert not _startup_bound(frames, request, {"expected_executable_sha256": "b" * 64}, binding)
    for missing in (None, "", "entry"):
        assert not _startup_bound(frames, request, {"expected_executable_sha256": missing}, binding)
    for change in ({"executable": "/other/runtime/Python"}, {"executable_sha256": "c" * 64}, {"uid": 502}):
        bad = deepcopy(request)
        bad["identity"].update(change)
        assert not _startup_bound(frames, bad, attempt, binding)
    for change in ({"child_token": "other"}, {"parent_epoch": "other"},
            {"python_runtime": {"loaded_core_sha256": ["b" * 64, "c" * 64], "kind": "other"}},
            {"executable_sha256": "b" * 64}):
        bad = deepcopy(frames)
        bad[-1].update(change)
        assert not _startup_bound(bad, request, attempt, binding)
    assert not _startup_bound([*frames, frames[-1]], request, attempt, binding)


def test_socket_ready_preserves_creation_and_records_settled_permission_identity(monkeypatch):
    from sciplot_core.verification import private_audit_runtime as runtime
    import socket

    owner = runtime.owner_identity("server.py", "serve")
    assert owner.get("owner") == "server.py" and len(owner["bytecode_sha256"]) == 64
    assert runtime.owner_identity("server.py", "unknown") == {}
    assert owner["source_sha256"] == runtime.file_sha256(__import__("pathlib").Path(runtime.__file__).parents[1] / "plot_protocol/server.py")
    frames, state = [], {"ctime_ns": 1, "mode": 0o755}
    class Endpoint:
        family = socket.AF_UNIX
        def bind(self, address):
            pass
        def listen(self, backlog):
            pass
        def connect(self, address):
            pass
        def fileno(self):
            return 7
    def record(row, **kwargs):
        frame = {"pid":100,"epoch":"primary","sequence":len(frames), **row, "sha256": "frame-" + str(len(frames))}
        frames.append(frame)
        return frame
    observer = SimpleNamespace(guard=SimpleNamespace(), record=record)
    endpoint = {"device": 1, "inode": 2, "uid": 501}
    with monkeypatch.context() as patch:
        patch.setattr(runtime.socket, "socket", Endpoint)
        patch.setattr(runtime, "_endpoint", lambda address: (__import__('pathlib').Path(address), {**endpoint, **state}))
        patch.setattr(runtime, "owned_caller", lambda *args: runtime.owner_identity("server.py", "serve"))
        runtime.install_socket_ports(observer)
        server = Endpoint()
        server.bind('/tmp/generated-listen.sock')
        state.update(ctime_ns=2,mode=0o600)  # The source-owned serve chmod precedes listen.
        server.listen(16)
    assert [row['event'] for row in frames] == ['audit_socket_bind', 'audit_socket_listen']
    assert frames[0]['endpoint']['ctime_ns'] == 1
    assert frames[1]['endpoint']['ctime_ns'] == 2
    assert frames[1]['binding_token'] == frames[0]['binding_token']
    assert frames[1]['creation_sha256'] == frames[0]['sha256']
    from copy import deepcopy
    assert runtime.settled_binding(frames[1],[frames[0]])
    assert not runtime.settled_binding(frames[1],[frames[0],dict(frames[0])])
    for key,value in [('owner',None),('sequence',0),('binding_token','unobserved')]:
        assert not runtime.settled_binding({**frames[1],key:value},[frames[0]])
    for key,value in [('inode',99),('mode',0o666)]:
        bad = deepcopy(frames[1])
        bad['endpoint'][key] = value
        assert not runtime.settled_binding(bad,[frames[0]])


def test_explicit_actor_actual_wait_is_observation_without_default_management(monkeypatch):
    from pathlib import Path
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    from sciplot_core.verification import private_audit_runtime as runtime

    source = Path(__file__).resolve()
    directory = {'device': 1, 'inode': 2, 'uid': 501, 'mode': 0o700}
    node = 'tests/test_private_native_exit_port.py::generated'
    scope = dict(manifest_sha256='manifest', collection_sha256='collection', suite_root_sha256='suite', nodes={node})
    path = str(Path('/tmp').resolve() / 'sp-audit-generated-explicit/engine.sock')
    base = dict(pid=100, epoch='primary', socket=path, test_nodeid=node)
    owner = runtime.owner_identity('socket_client.py', 'ensure_server')
    start = {**base, 'event':'audit_socket_enter', 'sequence':1, 'sha256':'item', 'initial_absent':True,
             'owner':runtime.owner_identity('private_audit_runtime.py','start_node'), 'directory':directory,
             'test_source_sha256':runtime.file_sha256(source), **{k:v for k,v in scope.items() if k!='nodes'}}
    spawned = {**base, 'event':'audit_server_spawn', 'sequence':3, 'child_pid':200,
               'child_token':'actual', 'default_owned':False, 'owner':owner}
    end = {**base, 'event':'audit_socket_exit', 'sequence':8, 'directory':directory}
    records = {canonical_json_sha256(str(source)):{'sha256':runtime.file_sha256(source)}}
    monkeypatch.setattr(runtime,'_directory',lambda _:directory)
    for code, closed_boundary, expected in [(0,False,[]),(-9,True,[]),(-9,False,['observed explicit engine has no closed actual exit'])]:
        actual = {**base,'event':'child_exit','sequence':7,'child_token':'actual','child_pid':200,'returncode':code}
        frames = [start,spawned,actual,end]
        assert runtime.review_sockets(frames,primary=100,scope=scope,records=records,native_exits={},
            source_exclusions={'primary:actual'} if closed_boundary else set()) == expected
        assert runtime.review_sockets([*frames,dict(actual)],primary=100,scope=scope,records=records,native_exits={},
            source_exclusions={'primary:actual'}) == ['observed explicit engine has no closed actual exit']


def _peer_scene(monkeypatch, *, changed_parent=False, peer_pid=302, live=True):
    import os
    from sciplot_core.verification import private_native_exit_port as port
    from sciplot_core.verification.native_exit_boundary import ProcessIdentity
    from sciplot_core.plot_protocol import paths

    root = ProcessIdentity(201, 101, os.getuid(), 12, 2, '/modeled/Python', '/tmp', 'a' * 64)
    peer = ProcessIdentity(302, root.pid, root.uid, 13, 3, root.executable, root.cwd, root.executable_sha256)
    calls, frames, registrations = [], [], []
    observer = SimpleNamespace(epoch='primary', guard=SimpleNamespace(active=False),
        _audit_socket_scope=({'sockets':['/tmp/source-owned.sock'],'test_nodeid':'actual-node'}, {}),
        record=lambda row, **kwargs: frames.append({**row,'epoch':'primary','pid':101,'sequence':3,'monotonic_ns':3}))
    instance = port._Port.__new__(port._Port)
    instance.observer, instance.discovered = observer, set()
    attempt = {'nodeid':'actual-node','sha256':'actual-attempt','event':'spawn_attempt',
               'epoch':'primary','child_token':'actual-token','sequence':1,'monotonic_ns':1}
    instance.launches = {'actual-token':(SimpleNamespace(pid=root.pid),attempt,root,False)}
    instance.register = lambda request: registrations.append(request)
    endpoint = {'device':1,'inode':2,'uid':root.uid,'ctime_ns':3,'mode':0o600}
    owner = {'pid':peer.pid,'device':1,'inode':2,'instance_id':'actual-instance'}
    def identity(pid):
        if pid == peer.pid:
            return peer
        if not live:
            raise ProcessLookupError('finished source CLI')
        return __import__('dataclasses').replace(root, start_usec=99) if changed_parent else root
    class Connection:
        def __init__(self, *args):
            calls.append('socket')
        def __enter__(self):
            return self
        def __exit__(self, *args):
            calls.append('close')
        def settimeout(self, timeout):
            calls.append(('timeout',timeout))
        def connect(self, name):
            assert observer.guard.active is True
            calls.append(('connect',name))
        def sendall(self, data):
            pytest.fail('Observer cannot send business requests')
    monkeypatch.setattr(port,'endpoint_identity',lambda *args,**kwargs:(None,endpoint))
    monkeypatch.setattr(paths,'read_owner',lambda path:owner)
    monkeypatch.setattr(port,'read_identity',identity)
    monkeypatch.setattr(port,'kernel_peer_pid',lambda connection:peer_pid)
    monkeypatch.setattr(port.socket,'socket',Connection)
    return instance,root,peer,attempt,calls,frames,registrations


def test_native_peer_handoff_requires_live_held_ancestry_and_actual_kernel_peer(monkeypatch):
    for changed_parent, actual_peer, live, accepted in [(False,302,True,True),
            (True,302,True,False),(False,999,True,False),(False,302,False,False)]:
        with monkeypatch.context() as patch:
            instance,_,_,_,calls,frames,registered = _peer_scene(patch,changed_parent=changed_parent,peer_pid=actual_peer,live=live)
            instance.discover()
            assert len(registered) == int(accepted)
            assert instance.observer.guard.active is False
            if not live or changed_parent:
                assert calls == []  # Even a probe cannot contact an unproved process.
            if accepted:
                assert [row['event'] for row in frames] == ['native_registration_request']
                assert registered[0]['actor']['default_owned'] is False
                assert calls[-1] == 'close'
                instance.discover()
                assert len(registered) == 1


def test_native_actor_binding_retains_source_exclusion_and_generation_counterproofs(monkeypatch):
    from copy import deepcopy
    from sciplot_core.verification.native_exit_boundary import validate_actor_launch

    with monkeypatch.context() as patch:
        instance,root,_,attempt,_,recorded,registered = _peer_scene(patch)
        instance.discover()
    request = registered[0]
    actual_owner = request["actor"]["owner"]
    assert actual_owner.get("owner") == "private_native_exit_port.py"
    assert actual_owner["function"] == "_Port.discover" and len(actual_owner["bytecode_sha256"]) == 64
    from sciplot_core.verification.private_process_boundaries import owner_identity
    assert owner_identity("private_native_exit_port.py", "discover") == {}
    frames = [attempt,{'event':'child_spawn','epoch':'primary','child_token':'actual-token','child_pid':root.pid,
                       'sequence':2,'monotonic_ns':2},*recorded]
    assert validate_actor_launch(request,frames,101,{'primary:actual-token'})
    assert not validate_actor_launch(request,frames,101,set())
    assert not validate_actor_launch(request,frames+[dict(frames[1])],101,{'primary:actual-token'})
    for target,update in [('identity',{'pid':999}),('identity',{'ppid':999}),
                         ('parent',{'start_usec':99}),('owner',{'pid':999}),('endpoint',{'inode':99})]:
        bad = deepcopy(request)
        value = bad['identity'] if target=='identity' else bad['actor']['launch']['parent'] if target=='parent' else bad['actor']['ready']['socket_owner'] if target=='owner' else bad['actor']['ready']['endpoint']
        value.update(update)
        bad_frames = [*frames[:-1],{**frames[-1],'request':bad}]
        assert not validate_actor_launch(bad,bad_frames,101,{'primary:actual-token'})

    bad = deepcopy(request)
    bad['actor']['ready']['peer_pid'] = 999
    bad_frames = [*frames[:-1],{**frames[-1],'request':bad}]
    assert not validate_actor_launch(bad,bad_frames,101,{'primary:actual-token'})
    for row_index, update in [(1,{'sequence':0}),(2,{'monotonic_ns':1})]:
        bad_frames = deepcopy(frames)
        bad_frames[row_index].update(update)
        assert not validate_actor_launch(request,bad_frames,101,{'primary:actual-token'})
    assert not validate_actor_launch(request,[*frames,dict(frames[-1])],101,{'primary:actual-token'})
    bad = deepcopy(request)
    bad['actor']['owner'] = {}
    assert not validate_actor_launch(bad,[*frames[:-1],{**frames[-1],'request':bad}],101,{'primary:actual-token'})
