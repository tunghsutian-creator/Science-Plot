"""Actual Mac generated process controls; no private inputs or Qt rendering."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.verification.process_private_exclusion import (
    actual_launch_facts,
    invocation_snapshot,
    original_stdio_facts,
    prepare_private_exclusion,
    source_private_exclusion,
    validate_excluded_proof,
    validate_private_exclusion,
    wrap_private_exclusion,
)
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.verification.private_observer import reserve_child_environment

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Actual Mac process boundary control")


@pytest.fixture
def generated(tmp_path):
    origin = tmp_path / "movable-origin"
    private = origin / "tests/fixtures/real_world"
    private.mkdir(parents=True)
    canary = private / "literal.txt"
    canary.write_bytes(b"literal generated protected bytes\n")
    public = tmp_path / "public"
    public.mkdir()
    allowed = public / "allowed.txt"
    allowed.write_bytes(b"literal generated public bytes\n")
    alias = public / "symlink"
    alias.symlink_to(canary)
    audit = tmp_path / "outer-audit"
    audit.mkdir()
    evidence = audit / "existing.jsonl"
    evidence.write_bytes(b"literal generated evidence\n")
    witness = tmp_path / "primary-receipt.json"
    witness.write_text("original witness")
    frozen = prepare_private_exclusion(origin, {}, audit_directory=audit, evidence_paths=[witness])
    return origin, canary, public, allowed, alias, audit, evidence, witness, frozen


def execute(frozen, code, arguments=(), *, environment=None, stdin=subprocess.DEVNULL, input_bytes=None):
    with wrap_private_exclusion(frozen, ["/usr/bin/python3", "-I", "-c", code, *map(str, arguments)],
            environment=dict(os.environ) if environment is None else environment,
            stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as invocation:
        process = subprocess.Popen(invocation.argv, env=invocation.environment, stdin=invocation.stdio[0],
            stdout=invocation.stdio[1], stderr=invocation.stdio[2], close_fds=True)
        stdout, stderr = process.communicate(input=input_bytes, timeout=15)
        assert process.returncode is not None
        validate_private_exclusion(frozen)
        return process.pid, process.returncode, stdout, stderr


def test_actual_strong_boundary_blocks_namespace_alias_and_evidence_mutations(generated):
    origin, canary, public, allowed, alias, audit, evidence, witness, frozen = generated
    code = """
import errno,json,os,subprocess,sys
from pathlib import Path
origin,canary,public,allowed,alias,audit,evidence,witness=map(Path,sys.argv[1:])
out={"pid":os.getpid(),"allowed":allowed.read_bytes()==b'literal generated public bytes\\n'}
def refused(name,operation):
    try: operation()
    except OSError as error: out[name]=error.errno in (errno.EPERM,errno.EACCES)
    else: out[name]=False
refused('direct',canary.read_bytes)
refused('symlink',alias.read_bytes)
refused('new_hardlink',lambda:os.link(canary,public/'hardlink'))
refused('file_rename',lambda:os.rename(canary,public/'moved-file'))
refused('root_rename',lambda:os.rename(canary.parent,public/'moved-root'))
refused('ancestor_rename',lambda:os.rename(origin,public/'moved-origin'))
refused('audit_overwrite',lambda:evidence.write_text('forged'))
refused('audit_create',lambda:(audit/'forged.jsonl').write_text('forged'))
refused('audit_rename',lambda:os.rename(audit,public/'moved-audit'))
refused('witness_overwrite',lambda:witness.write_text('forged'))
refused('witness_rename',lambda:os.rename(witness,public/'moved-witness'))
native=subprocess.run(['/bin/cat',str(canary)],stdin=subprocess.DEVNULL,capture_output=True,close_fds=True)
out['native']=native.returncode==1 and not native.stdout
inner="import subprocess,sys; p=subprocess.run(['/bin/cat',sys.argv[1]],capture_output=True,close_fds=True); raise SystemExit(0 if p.returncode==1 and not p.stdout else 2)"
child=subprocess.run([sys.executable,'-I','-c',inner,str(canary)],env={},stdin=subprocess.DEVNULL,capture_output=True,close_fds=True)
out['clear_env_grandchild']=child.returncode==0
print(json.dumps(out))
"""
    pid, returncode, stdout, stderr = execute(frozen, code, generated[:8])
    assert returncode == 0, stderr
    observed = json.loads(stdout)
    assert observed.pop("pid") == pid
    assert observed == dict.fromkeys(("allowed", "direct", "symlink", "new_hardlink", "file_rename", "root_rename",
        "ancestor_rename", "audit_overwrite", "audit_create", "audit_rename", "witness_overwrite", "witness_rename",
        "native", "clear_env_grandchild"), True)
    assert canary.read_bytes() == b"literal generated protected bytes\n"
    assert evidence.read_bytes() == b"literal generated evidence\n"
    assert witness.read_text() == "original witness"


def test_actual_pipe_protocol_and_post_kernel_environment_projection(generated):
    frozen = generated[-1]
    environment = dict(os.environ, SCIPLOT_PRIVATE_AUDIT_DIR="generated-outer-routing", GENERATED_KEEP="kept")
    code = "import os,sys;assert 'SCIPLOT_PRIVATE_AUDIT_DIR' not in os.environ;assert os.environ['GENERATED_KEEP']=='kept';sys.stdout.buffer.write(sys.stdin.buffer.read()[::-1])"
    with wrap_private_exclusion(frozen, ["/usr/bin/python3", "-I", "-c", code], environment=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            drop_environment=["SCIPLOT_PRIVATE_AUDIT_DIR"]) as invocation:
        assert invocation.environment == environment  # The launcher receives the original environment.
        process = subprocess.Popen(invocation.argv, env=invocation.environment, stdin=invocation.stdio[0],
            stdout=invocation.stdio[1], stderr=invocation.stdio[2], close_fds=True)
        output, error = process.communicate(b"literal stdin protocol\n", timeout=15)
        assert process.returncode == 0 and error is None
        assert output == b"\nlocotorp nidts laretil"
    validate_private_exclusion(frozen)


def test_actual_close_fds_and_devnull_do_not_inherit_generated_raw_descriptor(generated):
    _, canary, *_, frozen = generated
    descriptor = os.open(canary, os.O_RDONLY)
    os.set_inheritable(descriptor, True)
    value = os.fstat(descriptor)
    code = """
import errno,json,os,sys
try:
    row=os.fstat(int(sys.argv[1])); closed=(row.st_dev,row.st_ino)!=(int(sys.argv[2]),int(sys.argv[3]))
except OSError as error: closed=error.errno==errno.EBADF
print(json.dumps({'private_fd_not_inherited':closed,'stdin_eof':os.read(0,1)==b''}))
"""
    try:
        _, result, stdout, stderr = execute(frozen, code, (descriptor, value.st_dev, value.st_ino))
    finally:
        os.close(descriptor)
    assert result == 0, stderr
    assert json.loads(stdout) == {"private_fd_not_inherited": True, "stdin_eof": True}


def test_pinned_interpreter_loader_environment_is_preserved(generated):
    environment = dict(os.environ, SCIPLOT_PRIVATE_AUDIT_DIR="generated-outer-routing")
    expected_loader = environment["DYLD_FRAMEWORK_PATH"]
    code = "import hashlib,json,os,sys;value=hashlib.sha256(json.dumps(dict(os.environ),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest();print(json.dumps({'environment_sha256':value,'loader':os.environ.get('DYLD_FRAMEWORK_PATH'),'executable':sys.executable,'version':list(sys.version_info[:3])}))"
    with wrap_private_exclusion(generated[-1], [sys.executable, "-I", "-c", code], environment=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            drop_environment=["SCIPLOT_PRIVATE_AUDIT_DIR"]) as invocation:
        process = subprocess.Popen(invocation.argv, env=invocation.environment, stdin=invocation.stdio[0],
            stdout=invocation.stdio[1], stderr=invocation.stdio[2], close_fds=True)
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        expected_environment = invocation.proof["actual"]["target_environment_sha256"]
    observed = json.loads(stdout)
    assert observed["version"] == list(sys.version_info[:3])
    assert observed["loader"] == expected_loader, observed
    assert os.path.samefile(observed["executable"], sys.executable), observed
    assert observed["environment_sha256"] == expected_environment, observed
    print(json.dumps({"actual_pinned_target": observed, "pid": process.pid, "exit": process.returncode}, sort_keys=True))


@pytest.mark.parametrize("code,expected", [("import os;os._exit(79)", 79),
    ("import os,signal;os.kill(os.getpid(),signal.SIGTERM)", -15)])
def test_actual_nonzero_and_signal_outcomes_are_retained(generated, code, expected):
    _, actual, _, _ = execute(generated[-1], code)
    assert actual == expected


@pytest.fixture
def short_socket_directory():
    from socket_fixture_helpers import socket_directory

    with socket_directory(prefix="sp-central-", dir="/private/tmp",
            endpoints=("cold-engine.sock", "engine.sock")) as directory:
        yield Path(directory).resolve()


def test_actual_same_launch_composition_preserves_two_finite_socket_endpoints(generated, tmp_path, short_socket_directory):
    origin, canary, _, _, _, audit, _, witness, _ = generated
    directory = short_socket_directory
    assert not list(directory.iterdir())
    value = directory.stat()
    scope = {"sockets": [str(directory / "cold-engine.sock"), str(directory / "engine.sock")],
        "directory": {"device": value.st_dev, "inode": value.st_ino, "uid": value.st_uid, "mode": 0o700},
        "initial_absent": True}
    outer = prepare_private_exclusion(origin, {}, audit_directory=audit, evidence_paths=[witness], socket_scope=scope)
    inner_root = tmp_path / "inner-origin"
    inner_raw = inner_root / "tests/fixtures/real_world/literal.txt"
    inner_raw.parent.mkdir(parents=True)
    inner_raw.write_bytes(b"literal generated inner bytes")
    inner = prepare_private_exclusion(inner_root, {}, socket_scope=scope)
    code = """
import errno,hashlib,json,os,socket,sys
result={'pid':os.getpid(),'endpoints':0,'raw_denied':0}
for path in sys.argv[1:3]:
    server=socket.socket(socket.AF_UNIX);server.bind(path);server.listen(1)
    client=socket.socket(socket.AF_UNIX);client.connect(path);client.sendall(b'generated-protocol')
    peer,_=server.accept();assert peer.recv(64)==b'generated-protocol'
    peer.close();client.close();server.close();os.unlink(path);result['endpoints']+=1
for path in sys.argv[3:]:
    try: open(path,'rb').read()
    except OSError as error: result['raw_denied']+=error.errno in (errno.EPERM,errno.EACCES)
result['environment_sha256']=hashlib.sha256(json.dumps(dict(os.environ),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
print(json.dumps(result,sort_keys=True))
"""
    environment = dict(os.environ, GENERATED_INNER_ROUTE="inner", GENERATED_OUTER_ROUTE="old")
    target = (sys.executable, "-I", "-c", code, *scope["sockets"], str(canary), str(inner_raw))
    with wrap_private_exclusion(inner, target, environment=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, drop_environment=["GENERATED_INNER_ROUTE"]) as source:
        effective = dict(environment, GENERATED_OUTER_ROUTE="new")
        reference = source_private_exclusion(source.argv, effective, stdio=source.stdio,
            drop_environment=["GENERATED_OUTER_ROUTE"])
        assert reference is not None
        caller = actual_launch_facts(reference[0], source.argv, effective, stdio=source.stdio, drop_environment=reference[1])
        with wrap_private_exclusion(outer, source.argv, environment=effective, stdin=source.stdio[0],
                stdout=source.stdio[1], stderr=source.stdio[2], drop_environment=["GENERATED_OUTER_ROUTE"]) as combined:
            assert combined.argv.count("/usr/bin/sandbox-exec") == 1
            launch = actual_launch_facts(invocation_snapshot(combined), combined.argv, combined.environment,
                stdio=combined.stdio, drop_environment=["GENERATED_INNER_ROUTE", "GENERATED_OUTER_ROUTE"])
            validate_excluded_proof(combined.proof, expected_snapshot=outer,
                original_argv_sha256=canonical_json_sha256(list(source.argv)), original_environment_sha256=canonical_json_sha256(effective),
                original_executable_sha256=hashlib.sha256(Path("/usr/bin/sandbox-exec").read_bytes()).hexdigest(),
                original_cwd=os.getcwd(), original_stdio=original_stdio_facts(*source.stdio), actual_launch=launch,
                caller_launch=caller, drop_environment=["GENERATED_OUTER_ROUTE"])
            dropped = {"GENERATED_INNER_ROUTE", "GENERATED_OUTER_ROUTE"}
            before_public = {key: value for key, value in combined.environment.items() if key not in dropped}
            assert launch["target_environment_sha256"] == canonical_json_sha256(before_public)
            # Bind the same finite target projection used by the actual public launch.
            # This preview does not reserve a child token or grant an exclusion proof.
            target_environment = reserve_child_environment(combined.environment, reserve=False)
            expected = canonical_json_sha256({key: value for key, value in target_environment.items() if key not in dropped})
            process = subprocess.Popen(combined.argv, env=combined.environment, stdin=combined.stdio[0],
                stdout=combined.stdio[1], stderr=combined.stdio[2], close_fds=True)
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stderr
    observed = json.loads(stdout)
    assert observed == {"pid": process.pid, "endpoints": 2, "raw_denied": 2, "environment_sha256": expected}
    validate_private_exclusion(outer)
    validate_private_exclusion(inner)
    print(json.dumps({"same_launch_composition": observed, "exit": process.returncode}, sort_keys=True))
