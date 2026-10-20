"""Run review-only inputs under the immutable original documentation runtime."""
from __future__ import annotations

import argparse
from functools import partial
import hashlib
import json
import os
import secrets
import shutil
import time
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen

IMAGE = 'python:3.12-bookworm@sha256:e91fec3d1ac69f04e4eddcd29c327e630ce34658cf31075bfa7e8b0e052bafea'
REPOSITORY = 'https://github.com/honua-io/honua-sdk-python'


def run(command: list[str]) -> bytes:
    environment = {key: os.environ[key] for key in ('PATH','HOME','LANG','SYSTEMROOT') if key in os.environ}
    return subprocess.check_output(command, env=environment, stderr=subprocess.PIPE)


def clone(source: Path, destination: Path, revision: str) -> None:
    actual = run(['git','-C',str(source),'rev-parse','HEAD']).decode().strip()
    if actual != revision or run(['git','-C',str(source),'status','--porcelain','--untracked-files=all']).strip():
        raise ValueError('input checkout is not the requested immutable clean revision')
    remote = run(['git','-C',str(source),'remote','get-url','origin']).decode().strip()
    if remote.removesuffix('.git') not in (REPOSITORY,'git@github.com:honua-io/honua-sdk-python'):
        raise ValueError('input repository identity differs')
    run(['git','clone','--quiet','--no-hardlinks','--no-checkout',str(source),str(destination)])
    run(['git','-C',str(destination),'checkout','--quiet','--detach',revision])
    run(['git','-C',str(destination),'remote','set-url','origin',REPOSITORY])
    if run(['git','-C',str(destination),'status','--porcelain','--untracked-files=all']).strip():
        raise ValueError('isolated clone is not clean')


def inspect_container(container: str) -> dict:
    # Only fixed, safe daemon projections; never capture Config.Env.
    template = '{"id":{{json .Id}},"imageId":{{json .Image}},"declaredImage":{{json .Config.Image}},"path":{{json .Path}},"args":{{json .Args}},"user":{{json .Config.User}},"readonlyRootfs":{{json .HostConfig.ReadonlyRootfs}},"mounts":{{json .Mounts}},"tmpfs":{{json .HostConfig.Tmpfs}},"exitCode":{{json .State.ExitCode}},"status":{{json .State.Status}},"running":{{json .State.Running}},"startedAt":{{json .State.StartedAt}},"finishedAt":{{json .State.FinishedAt}},"ownerNonce":{{json (index .Config.Labels "io.honua.development-input-owner")}}}'
    return json.loads(run(['docker','inspect','--format',template,container]))


def validate_container(observed: dict, container: str, *, owner: str, image_id: str, arguments: list[str], mounts: list, user: str, tmpfs: str) -> None:
    tmpfs_root,tmpfs_options = tmpfs.split(':',1)
    if (observed['id'] != container or observed['ownerNonce'] != owner or observed['user'] != user
            or observed['imageId'] != image_id or observed['declaredImage'] != IMAGE or observed['readonlyRootfs'] is not True
            or observed['path'] != arguments[0] or observed['args'] != arguments[1:]
            or observed.get('tmpfs') != {tmpfs_root: tmpfs_options}):
        raise ValueError('actual container identity, command or private tmpfs differs')
    actual_binds, temporary = [], []
    for row in observed['mounts']:
        if type(row['RW']) is not bool:
            raise ValueError('daemon mount read/write flag is not boolean')
        if row['Type'] == 'bind':
            actual_binds.append((row['Source'],row['Destination'],row['RW']))
        elif row['Type'] == 'tmpfs' and row['Source'] == '' and row['Destination'] == tmpfs_root and row['RW'] is True:
            temporary.append(row)
        else:
            raise ValueError('unexpected daemon mount')
    expected = [(str(source),target,not readonly) for source,target,readonly in mounts]
    if len(actual_binds) != len(expected) or set(actual_binds) != set(expected) or len(temporary) > 1:
        raise ValueError('actual readonly bind mount census differs')


def exited(observed: dict) -> bool:
    return (observed['running'] is False and observed['status'] == 'exited' and type(observed['exitCode']) is int
            and not observed['startedAt'].startswith('0001-') and not observed['finishedAt'].startswith('0001-'))


def wait_for_terminal(container: str, observed: dict, output: Path, validate) -> dict:
    # A detached transport failure is never authority to cancel admitted work.
    while observed['running'] is True:
        output.write_text(json.dumps({'status':'pending-live-action','container':observed,'sourceAdmitted':False},indent=2)+'\n')
        time.sleep(2)
        observed = inspect_container(container)
        output.with_suffix('.observed.json').write_text(json.dumps(observed,indent=2)+'\n')
        validate(observed, container)
    return observed


def capture_action(container: str, action: str, destination: Path, validate) -> tuple[bytes,bytes,dict]:
    environment = {key: os.environ[key] for key in ('PATH','HOME','LANG','SYSTEMROOT') if key in os.environ}
    result = subprocess.run(['docker','start','--attach',container],env=environment,capture_output=True,check=False)  # noqa: S603
    # Both streams and actual daemon state are retained BEFORE enforcing success.
    (destination/(action+'.stdout')).write_bytes(result.stdout)
    (destination/(action+'.stderr')).write_bytes(result.stderr)
    after = inspect_container(container)
    (destination/(action+'.container-after.json')).write_text(json.dumps(after,indent=2)+'\n')
    validate(after,container)
    after = wait_for_terminal(container,after,destination/(action+'.pending.json'),validate)
    (destination/(action+'.container-after.json')).write_text(json.dumps(after,indent=2)+'\n')
    (destination/(action+'.attach.json')).write_text(json.dumps({'returnCode':result.returncode,'sourceAdmitted':False})+'\n')
    if result.returncode != 0 or not exited(after) or after['exitCode'] != 0:
        raise ValueError('governed producer action failed; original streams and terminal state retained')
    return result.stdout,result.stderr,after


def cleanup_owned(owner: str, action: str, destination: Path, validate) -> dict:
    owned = run(['docker','ps','--all','--quiet','--no-trunc','--filter','label=io.honua.development-input-owner='+owner]).decode().splitlines()
    if len(owned) != 1:
        raise ValueError('owned container cleanup census is missing or ambiguous')
    candidate = owned[0]
    observed = inspect_container(candidate)
    (destination/(action+'.cleanup-observed.json')).write_text(json.dumps(observed,indent=2)+'\n')
    validate(observed,candidate)
    observed = wait_for_terminal(candidate,observed,destination/(action+'.cleanup-pending.json'),validate)
    never_started = (observed['running'] is False and observed['status'] == 'created'
                     and observed['startedAt'].startswith('0001-') and observed['finishedAt'].startswith('0001-'))
    if not exited(observed) and not never_started:
        raise ValueError('refusing cleanup without a terminal or never-started owned state')
    cleanup = run(['docker','rm',candidate])  # Normal removal only; no force/cancel.
    if cleanup.decode().strip() != candidate:
        raise ValueError('normal owned container removal did not acknowledge exact identity')
    result = {'ownedContainerId':candidate,'ownerNonce':owner,'originalState':observed,'removed':True,'sourceAdmitted':False}
    (destination/(action+'.cleanup.json')).write_text(json.dumps(result,indent=2)+'\n')
    return result


def execute(implementation: Path, subject: Path, revision: str, destination: Path, wheel: Path) -> dict:
    implementation,subject,wheel = implementation.resolve(),subject.resolve(),wheel.resolve()
    if destination.exists() or destination.resolve().is_relative_to(implementation) or destination.resolve().is_relative_to(subject):
        raise ValueError('runtime output must be new and outside both immutable inputs')
    destination.mkdir(mode=0o700)
    destination = destination.resolve()
    implementation_sha = run(['git','-C',str(implementation),'rev-parse','HEAD']).decode().strip()
    policy = json.loads((implementation/'scripts/development-inputs/governed-runtime.json').read_bytes())
    binding = policy['executionBinding']
    if binding['containerImage'] != IMAGE or wheel.name != binding['implementationPackagingFilename'] or hashlib.sha256(wheel.read_bytes()).hexdigest() != binding['implementationPackagingSha256']:
        raise ValueError('runtime image or implementation tool bytes differ')
    image = json.loads(run(['docker','image','inspect','--format','{"Id":{{json .Id}},"RepoDigests":{{json .RepoDigests}}}',IMAGE]))
    if (not isinstance(image.get('Id'),str) or not image['Id'].startswith('sha256:') or len(image['Id']) != 71
            or any(character not in '0123456789abcdef' for character in image['Id'][7:])
            or not any(item in {'python@'+IMAGE.split('@')[1],'docker.io/library/python@'+IMAGE.split('@')[1]} for item in image['RepoDigests'])):
        raise ValueError('actual daemon image differs from governed digest')
    image_receipt = {'id':image['Id'],'repoDigests':image['RepoDigests'],'declaredImage':IMAGE}
    (destination/'image.json').write_text(json.dumps(image_receipt,indent=2)+'\n')
    commands,containers = [],[]
    scratch = Path(tempfile.mkdtemp(prefix='honua-governed-inputs-',dir=str(Path(tempfile.gettempdir()).resolve())))
    pending = False
    try:
        producer_copy,subject_copy = scratch/'implementation',scratch/'subject'
        clone(implementation,producer_copy,implementation_sha)
        clone(subject,subject_copy,revision)
        for action in ('probe','probe-refusals','generate','verify','mutations'):
            arguments = ['/usr/local/bin/python3.12','-I','/implementation/scripts/governed_source_inputs_bootstrap.py',
                '--implementation-packaging-wheel','/implementation-tools/'+wheel.name,'--action',action,
                '--source','/subject','--revision',revision,'--destination','/output/proposal',
                '--runtime-policy','/implementation/scripts/development-inputs/governed-runtime.json']
            mounts = [(producer_copy,'/implementation',True),(subject_copy,'/subject',True),(wheel,'/implementation-tools/'+wheel.name,True),(destination,'/output',False)]
            owner = secrets.token_hex(16)
            user = str(os.getuid())+':'+str(os.getgid())
            tmpfs = f'/tmp:rw,exec,mode=0700,uid={os.getuid()},gid={os.getgid()}'  # noqa: S108 -- owned private container tmpfs
            command = ['docker','create','--label','io.honua.development-input-owner='+owner,'--read-only','--user',user,
                       '--workdir','/implementation','--env','HOME=/tmp','--env','PYTHONDONTWRITEBYTECODE=1','--tmpfs',tmpfs]
            for source_path,target,readonly in mounts:
                command.extend(['--mount','type=bind,src='+str(source_path)+',dst='+target+(',readonly' if readonly else '')])
            command.extend([IMAGE,*arguments])
            validate = partial(validate_container,owner=owner,image_id=image['Id'],arguments=arguments,mounts=mounts,user=user,tmpfs=tmpfs)
            try:
                container = run(command).decode().strip()
                if len(container) != 64 or any(character not in '0123456789abcdef' for character in container):
                    raise ValueError('daemon returned malformed owned container ID')
                before = inspect_container(container)
                (destination/(action+'.container-before.json')).write_text(json.dumps(before,indent=2)+'\n')
                validate(before,container)
                output,errors,after = capture_action(container,action,destination,validate)
                commands.append({'action':action,'command':command,'stdoutSha256':hashlib.sha256(output).hexdigest(),'stderrSha256':hashlib.sha256(errors).hexdigest()})
                containers.append({'action':action,'before':before,'after':after})
            finally:
                try:
                    cleanup = cleanup_owned(owner,action,destination,validate)
                    if containers and containers[-1]['action'] == action:
                        containers[-1]['cleanup'] = cleanup
                except Exception:
                    pending = True
                    raise
    finally:
        if pending:
            (destination/'scratch-pending.json').write_text(json.dumps({'scratchRoot':str(scratch),'status':'retained-for-live-or-unverified-owned-action','sourceAdmitted':False},indent=2)+'\n')
        else:
            shutil.rmtree(scratch)
    receipt = {'schema':'honua.python-governed-input-execution/v1','implementationSha':implementation_sha,
        'subjectSourceSha':revision,'image':image_receipt,'implementationPackaging':{'filename':wheel.name,'sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'installed':False},
        'commands':commands,'containers':containers,'sourceAdmitted':False,'candidateQualified':False,'publishedWheelIdentity':False}
    (destination/'execution.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


def download_implementation_tool(policy: dict, directory: Path) -> tuple[Path, dict]:
    binding = policy["executionBinding"]
    registry = "https://pypi.org/pypi/packaging/" + policy["packaging"] + "/json"
    with urlopen(registry) as response:  # fixed public registry; no operator URL
        if response.url != registry:
            raise ValueError("implementation tool registry redirected")
        raw = response.read()
    values = [item for item in json.loads(raw)["urls"] if item["filename"] == binding["implementationPackagingFilename"]]
    if len(values) != 1 or values[0]["digests"]["sha256"] != binding["implementationPackagingSha256"]:
        raise ValueError("implementation tool registry identity differs")
    origin = values[0]["url"]
    parts = urlsplit(origin)
    if (parts.scheme != "https" or parts.hostname != "files.pythonhosted.org" or parts.netloc != "files.pythonhosted.org"
            or not parts.path.startswith("/packages/") or not parts.path.endswith("/" + binding["implementationPackagingFilename"])
            or parts.query or parts.fragment):
        raise ValueError("implementation tool origin is not canonical")
    with urlopen(origin) as response:  # noqa: S310 -- exact canonical HTTPS origin validated above
        if response.url != origin:
            raise ValueError("implementation tool origin redirected")
        data = response.read()
    if hashlib.sha256(data).hexdigest() != binding["implementationPackagingSha256"]:
        raise ValueError("implementation tool download bytes differ")
    wheel = directory / binding["implementationPackagingFilename"]
    wheel.write_bytes(data)
    return wheel, {"filename": wheel.name, "origin": origin, "sha256": hashlib.sha256(data).hexdigest(),
                   "registry": registry, "registrySha256": hashlib.sha256(raw).hexdigest(), "installed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--implementation',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--revision',required=True)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--implementation-packaging-wheel',type=Path)
    args=parser.parse_args()
    if args.implementation_packaging_wheel:
        execute(args.implementation,args.source,args.revision,args.destination,args.implementation_packaging_wheel)
    else:
        policy = json.loads((args.implementation/'scripts/development-inputs/governed-runtime.json').read_bytes())
        with tempfile.TemporaryDirectory(prefix='honua-implementation-tool-',dir=str(Path(tempfile.gettempdir()).resolve())) as temporary:
            wheel, origin = download_implementation_tool(policy, Path(temporary))
            execute(args.implementation,args.source,args.revision,args.destination,wheel)
            (args.destination/'implementation-tool-origin.json').write_text(json.dumps(origin,indent=2)+'\n')


if __name__=='__main__':
    main()
