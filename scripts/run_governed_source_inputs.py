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
ACTIONS = ('probe', 'probe-refusals', 'generate', 'verify', 'mutations')


def action_inputs(action: str, revision: str, context: dict, policy: dict) -> tuple:
    """Derive the fixed invocation from separately trusted execution context."""
    if action not in ACTIONS or set(context) != {'mountSources', 'user', 'tmpfs', 'image'}:
        raise ValueError('incomplete governed execution context')
    binding = policy['executionBinding']
    sources = context['mountSources']
    if set(sources) != {'implementation', 'subject', 'tool', 'output'}:
        raise ValueError('incomplete governed mount context')
    if any(not isinstance(value, str) or not Path(value).is_absolute() or str(Path(value)) != value
           for value in sources.values()) or len(set(sources.values())) != 4:
        raise ValueError('governed mount context is not finite and absolute')
    user = context['user']
    parts = user.split(':') if isinstance(user, str) else []
    if len(parts) != 2 or any(not item.isdecimal() for item in parts):
        raise ValueError('governed execution user differs')
    tmpfs = f'/tmp:rw,exec,mode=0700,uid={parts[0]},gid={parts[1]}'  # noqa: S108 -- fixed private container tmpfs
    if context['tmpfs'] != tmpfs or binding['containerImage'] != IMAGE:
        raise ValueError('governed private runtime context differs')
    arguments = ['/usr/local/bin/python3.12', '-I', '/implementation/scripts/governed_source_inputs_bootstrap.py',
        '--implementation-packaging-wheel', '/implementation-tools/'+binding['implementationPackagingFilename'],
        '--action', action, '--source', '/subject', '--revision', revision, '--destination', '/output/proposal',
        '--runtime-policy', '/implementation/scripts/development-inputs/governed-runtime.json']
    mounts = [(sources['implementation'], '/implementation', True), (sources['subject'], '/subject', True),
              (sources['tool'], '/implementation-tools/'+binding['implementationPackagingFilename'], True),
              (sources['output'], '/output', False)]
    return arguments, mounts, user, tmpfs


def create_command(owner: str, arguments: list, mounts: list, user: str, tmpfs: str) -> list:
    command = ['docker', 'create', '--label', 'io.honua.development-input-owner='+owner, '--read-only', '--user', user,
               '--workdir', '/implementation', '--env', 'HOME=/tmp', '--env', 'PYTHONDONTWRITEBYTECODE=1', '--tmpfs', tmpfs]
    for source_path, target, readonly in mounts:
        command.extend(['--mount', 'type=bind,src='+str(source_path)+',dst='+target+(',readonly' if readonly else '')])
    return [*command, IMAGE, *arguments]


def verify_execution_receipt(receipt: dict, *, implementation_sha: str, subject_sha: str, policy: dict,
                             proposal_bytes: bytes, expected_documentation: list, execution_context: dict,
                             original_files: dict[str, bytes]) -> dict:
    """Rejudge public original bytes only; never run commands or grant admission.

    The caller authenticates implementation, subject, expected documentation and
    execution_context independently. None is inferred from this receipt.
    Inner artifact verification remains mandatory in the actual original runtime.
    """
    binding = policy['executionBinding']
    expected_fields = {'schema', 'implementationSha', 'subjectSourceSha', 'image', 'implementationPackaging',
                       'commands', 'containers', 'innerProposalSha256', 'sourceAdmitted', 'candidateQualified', 'publishedWheelIdentity'}
    if (set(receipt) != expected_fields or receipt['schema'] != 'honua.python-governed-input-execution/v1'
            or receipt['implementationSha'] != implementation_sha or receipt['subjectSourceSha'] != subject_sha
            or any(receipt[key] is not False for key in ('sourceAdmitted', 'candidateQualified', 'publishedWheelIdentity'))):
        raise ValueError('governed receipt source or review-only identity differs')
    image = execution_context['image']
    if (set(image) != {'id', 'repoDigests', 'declaredImage'} or image['declaredImage'] != IMAGE
            or not isinstance(image['id'], str) or len(image['id']) != 71 or not image['id'].startswith('sha256:')
            or any(c not in '0123456789abcdef' for c in image['id'][7:])
            or not any(item in {'python@'+IMAGE.split('@')[1], 'docker.io/library/python@'+IMAGE.split('@')[1]}
                       for item in image['repoDigests']) or receipt['image'] != image):
        raise ValueError('governed original image identity differs')
    expected_tool = {'filename': binding['implementationPackagingFilename'],
                     'sha256': binding['implementationPackagingSha256'], 'installed': False}
    if receipt['implementationPackaging'] != expected_tool or receipt['implementationPackaging']['installed'] is not False:
        raise ValueError('governed implementation tool identity differs')
    if receipt['innerProposalSha256'] != hashlib.sha256(proposal_bytes).hexdigest():
        raise ValueError('governed original inner proposal bytes differ')
    proposal = json.loads(proposal_bytes)
    runtime = proposal['runtime']
    if (proposal['source']['sourceSha'] != subject_sha or proposal['implementation']['sourceSha'] != implementation_sha
            or any(proposal[key] is not False for key in ('sourceAdmitted', 'candidateQualified', 'publishedWheelIdentity'))
            or runtime['policySha256'] != hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
            or runtime['executableSha256'] != binding['pythonExecutableSha256']
            or runtime['toolFilesSha256']['pip'] != binding['pipToolFilesSha256']
            or any(runtime.get(key) != value for key, value in policy.items() if key != 'executionBinding')
            or any(runtime['executionBinding'].get(key) != value for key, value in binding.items())):
        raise ValueError('governed inner source or original runtime differs')
    sequences = proposal['documentationSequences']
    if (len(sequences) != len(expected_documentation) or len(expected_documentation) != 3
            or sum(len(item['invocations']) for item in expected_documentation) != 12):
        raise ValueError('governed documentation context census differs')
    for sequence, expected in zip(sequences, expected_documentation, strict=True):
        if any(sequence.get(key) != value for key, value in expected.items()) or len(sequence['steps']) != len(expected['invocations']):
            raise ValueError('governed original documentation declarations differ')
        for step, invocation in zip(sequence['steps'], expected['invocations'], strict=True):
            if any(step.get(key) != value for key, value in invocation.items()):
                raise ValueError('governed original ordered invocation differs')
    suffixes = ('stdout', 'stderr', 'attach.json', 'container-before.json', 'container-after.json', 'cleanup-observed.json', 'cleanup.json')
    if set(original_files) != {action+'.'+suffix for action in ACTIONS for suffix in suffixes} or any(type(value) is not bytes for value in original_files.values()):
        raise ValueError('governed original public file census differs')
    if (len(receipt['commands']) != len(ACTIONS) or len(receipt['containers']) != len(ACTIONS)
            or [item.get('action') for item in receipt['commands']] != list(ACTIONS)
            or [item.get('action') for item in receipt['containers']] != list(ACTIONS)):
        raise ValueError('governed original action order differs')
    ids, owners = set(), set()
    for action, command, states in zip(ACTIONS, receipt['commands'], receipt['containers'], strict=True):
        if set(command) != {'action', 'command', 'stdoutSha256', 'stderrSha256'} or set(states) != {'action', 'before', 'after', 'cleanup'}:
            raise ValueError('governed action field census differs')
        before, after, cleanup = states['before'], states['after'], states['cleanup']
        owner, container = before['ownerNonce'], before['id']
        if (not isinstance(owner, str) or len(owner) != 32 or any(c not in '0123456789abcdef' for c in owner)
                or not isinstance(container, str) or len(container) != 64 or any(c not in '0123456789abcdef' for c in container)
                or owner in owners or container in ids):
            raise ValueError('governed original action ownership differs')
        ids.add(container); owners.add(owner)
        arguments, mounts, user, tmpfs = action_inputs(action, subject_sha, execution_context, policy)
        validate = partial(validate_container, owner=owner, image_id=image['id'], arguments=arguments, mounts=mounts, user=user, tmpfs=tmpfs)
        for observed in (before, after, cleanup['originalState']):
            if set(observed) != {'id', 'imageId', 'declaredImage', 'path', 'args', 'user', 'readonlyRootfs', 'mounts',
                                 'tmpfs', 'exitCode', 'status', 'running', 'startedAt', 'finishedAt', 'ownerNonce'}:
                raise ValueError('governed safe daemon projection census differs')
            validate(observed, container)
        if (before['status'] != 'created' or before['running'] is not False or not before['startedAt'].startswith('0001-')
                or not before['finishedAt'].startswith('0001-') or not exited(after) or after['exitCode'] != 0
                or cleanup != {'ownedContainerId': container, 'ownerNonce': owner, 'originalState': after, 'removed': True, 'sourceAdmitted': False}
                or cleanup['removed'] is not True or cleanup['sourceAdmitted'] is not False
                or command['command'] != create_command(owner, arguments, mounts, user, tmpfs)):
            raise ValueError('governed action terminal state or normal owned cleanup differs')
        originals = {suffix: original_files[action+'.'+suffix] for suffix in suffixes}
        if (json.loads(originals['container-before.json']) != before or json.loads(originals['container-after.json']) != after
                or json.loads(originals['cleanup-observed.json']) != after or json.loads(originals['cleanup.json']) != cleanup
                or json.loads(originals['attach.json']) != {'returnCode': 0, 'sourceAdmitted': False}
                or type(json.loads(originals['attach.json'])['returnCode']) is not int
                or json.loads(originals['attach.json'])['sourceAdmitted'] is not False
                or any(command[label+'Sha256'] != hashlib.sha256(originals[label]).hexdigest() for label in ('stdout', 'stderr'))):
            raise ValueError('governed original action streams or state bytes differ')
        if action == 'probe' and json.loads(originals['stdout']) != runtime:
            raise ValueError('governed original probe runtime differs')
        if action in ('generate', 'verify') and originals['stdout'] != b'':
            raise ValueError('governed original producer output differs')
        if action == 'probe-refusals' and json.loads(originals['stdout']) != {
                'actualRefusals': ['wheel-bytes', 'wheel-name', 'image', 'interpreter', 'pip', 'pip-entrypoint', 'wheel-policy'],
                'sourceAdmitted': False, 'candidateQualified': False}:
            raise ValueError('governed original runtime refusals differ')
        if action == 'mutations' and json.loads(originals['stdout']) != {
                'completeOriginalPositive': 'PASS', 'mutationsRejected': ['context-loss', 'step-loss', 'step-reorder',
                    'ordinal', 'command', 'block', 'extras-superset', 'editable', 'source-before', 'source-resolved',
                    'source-after', 'installed-before', 'installed-after', 'derived-command', 'install-command',
                    'raw-report', 'backend-command', 'editable-identity', 'published', 'admitted', 'candidate'],
                'sourceAdmitted': False, 'candidateQualified': False, 'publishedWheelIdentity': False}:
            raise ValueError('governed original complete-proposal controls differ')
    return {'implementationSha': implementation_sha, 'subjectSourceSha': subject_sha,
            'innerProposalSha256': receipt['innerProposalSha256'], 'actions': list(ACTIONS),
            'innerArtifactVerificationRequired': True,
            'sourceAdmitted': False, 'candidateQualified': False, 'publishedWheelIdentity': False}


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
        context = {'mountSources': {'implementation': str(producer_copy), 'subject': str(subject_copy),
                   'tool': str(wheel), 'output': str(destination)}, 'user': str(os.getuid())+':'+str(os.getgid()),
                   'tmpfs': f'/tmp:rw,exec,mode=0700,uid={os.getuid()},gid={os.getgid()}', 'image': image_receipt}  # noqa: S108 -- private tmpfs
        for action in ACTIONS:
            arguments, mounts, user, tmpfs = action_inputs(action, revision, context, policy)
            owner = secrets.token_hex(16)
            command = create_command(owner, arguments, mounts, user, tmpfs)
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
        'commands':commands,'containers':containers,
        'innerProposalSha256':hashlib.sha256((destination/'proposal/proposal.json').read_bytes()).hexdigest(),
        'sourceAdmitted':False,'candidateQualified':False,'publishedWheelIdentity':False}
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
