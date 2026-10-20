"""Offline daemon projection/failure controls; actual image execution is separate."""
from __future__ import annotations

from copy import deepcopy
from functools import partial
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_governed_source_inputs as runner


class GovernedExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.container, self.owner, self.image = "a" * 64, "b" * 32, "sha256:" + "c" * 64
        self.arguments = ["/usr/local/bin/python3.12", "-I", "/implementation/scripts/governed_source_inputs_bootstrap.py"]
        self.mounts = [(self.root / "implementation", "/implementation", True),
                       (self.root / "subject", "/subject", True),
                       (self.root / "packaging.whl", "/implementation-tools/packaging.whl", True),
                       (self.root / "output", "/output", False)]
        self.tmpfs = "/tmp:rw,exec,mode=0700,uid=1000,gid=1000"  # noqa: S108 -- offline private daemon model
        self.observed = {"id": self.container, "ownerNonce": self.owner, "user": "1000:1000", "imageId": self.image,
                         "declaredImage": runner.IMAGE, "readonlyRootfs": True, "path": self.arguments[0], "args": self.arguments[1:],
                         "tmpfs": {"/tmp": self.tmpfs.split(":", 1)[1]},  # noqa: S108 -- offline daemon model
                         "mounts": [{"Type": "bind", "Source": str(source), "Destination": target, "RW": not readonly}
                                    for source, target, readonly in self.mounts],
                         "exitCode": 0, "status": "created", "running": False,
                         "startedAt": "0001-01-01T00:00:00Z", "finishedAt": "0001-01-01T00:00:00Z"}
        self.validate = partial(runner.validate_container, owner=self.owner, image_id=self.image,
                                arguments=self.arguments, mounts=self.mounts, user="1000:1000", tmpfs=self.tmpfs)

    def terminal(self, code=0):
        observed = deepcopy(self.observed)
        observed.update(status="exited", running=False, exitCode=code,
                        startedAt="2026-10-20T00:00:00Z", finishedAt="2026-10-20T00:01:00Z")
        return observed

    def live(self):
        observed = deepcopy(self.observed)
        observed.update(status="running", running=True, startedAt="2026-10-20T00:00:00Z")
        return observed

    def test_full_projection_positive_legacy_and_explicit_tmpfs_and_independent_refusals(self):
        self.validate(self.observed, self.container)
        explicit = deepcopy(self.observed)
        explicit["mounts"].append({"Type": "tmpfs", "Source": "", "Destination": "/tmp", "RW": True})  # noqa: S108 -- offline daemon model
        self.validate(explicit, self.container)
        for mutation in ("owner", "image", "readonly", "command", "user", "source", "extra", "typed-rw", "tmpfs", "duplicate-tmpfs"):
            observed = deepcopy(explicit)
            if mutation == "owner":
                observed["ownerNonce"] = "foreign"
            elif mutation == "image":
                observed["imageId"] = "sha256:" + "d" * 64
            elif mutation == "readonly":
                observed["readonlyRootfs"] = False
            elif mutation == "command":
                observed["args"] += ["--foreign"]
            elif mutation == "user":
                observed["user"] = "0:0"
            elif mutation == "source":
                observed["mounts"][0]["Source"] = str(self.root / "foreign")
            elif mutation == "extra":
                observed["mounts"].append({"Type": "volume", "Source": "foreign", "Destination": "/foreign", "RW": True})
            elif mutation == "typed-rw":
                observed["mounts"][0]["RW"] = 0
            elif mutation == "tmpfs":
                observed["tmpfs"] = {}
            else:
                observed["mounts"].append(deepcopy(observed["mounts"][-1]))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.validate(observed, self.container)

    def test_original_failure_stdout_stderr_and_terminal_state_retained_before_refusal(self):
        result = subprocess.CompletedProcess(["docker"], 1, b"original failure stdout", b"original failure stderr")
        with patch.object(runner.subprocess, "run", return_value=result), patch.object(runner, "inspect_container", return_value=self.terminal(1)):
            with self.assertRaisesRegex(ValueError, "original streams and terminal state retained"):
                runner.capture_action(self.container, "generate", self.root, self.validate)
        self.assertEqual((self.root / "generate.stdout").read_bytes(), result.stdout)
        self.assertEqual((self.root / "generate.stderr").read_bytes(), result.stderr)
        self.assertEqual(json.loads((self.root / "generate.container-after.json").read_bytes())["exitCode"], 1)
        self.assertEqual(json.loads((self.root / "generate.attach.json").read_bytes())["returnCode"], 1)

    def test_safe_original_state_retained_before_identity_refusal(self):
        result = subprocess.CompletedProcess(["docker"], 0, b"original stdout", b"original stderr")
        foreign = self.terminal()
        foreign["ownerNonce"] = "foreign"
        with patch.object(runner.subprocess, "run", return_value=result), patch.object(runner, "inspect_container", return_value=foreign):
            with self.assertRaisesRegex(ValueError, "actual container identity"):
                runner.capture_action(self.container, "generate", self.root, self.validate)
        self.assertEqual((self.root / "generate.stdout").read_bytes(), result.stdout)
        self.assertEqual((self.root / "generate.stderr").read_bytes(), result.stderr)
        self.assertEqual(json.loads((self.root / "generate.container-after.json").read_bytes())["ownerNonce"], "foreign")

    def test_transport_failure_waits_for_live_work_and_remains_failure_after_terminal(self):
        result = subprocess.CompletedProcess(["docker"], 1, b"partial original stdout", b"transport lost")
        with patch.object(runner.subprocess, "run", return_value=result) as command, \
             patch.object(runner, "inspect_container", side_effect=[self.live(), self.live(), self.terminal()]) as inspect, \
             patch.object(runner.time, "sleep"):
            with self.assertRaisesRegex(ValueError, "original streams and terminal state retained"):
                runner.capture_action(self.container, "generate", self.root, self.validate)
        self.assertEqual(inspect.call_count, 3)
        self.assertEqual(command.call_args.args[0], ["docker", "start", "--attach", self.container])
        self.assertTrue(json.loads((self.root / "generate.pending.json").read_bytes())["container"]["running"])
        self.assertEqual(json.loads((self.root / "generate.container-after.json").read_bytes())["status"], "exited")
        self.assertEqual((self.root / "generate.stdout").read_bytes(), result.stdout)

    def test_owned_live_cleanup_waits_then_normal_removes_exact_terminal_identity(self):
        def command(arguments):
            if arguments[:2] == ["docker", "ps"]:
                return (self.container + "\n").encode()
            self.assertEqual(arguments, ["docker", "rm", self.container])
            self.assertEqual(inspect.call_count, 2)
            return (self.container + "\n").encode()
        with patch.object(runner, "run", side_effect=command), \
             patch.object(runner, "inspect_container", side_effect=[self.live(), self.terminal()]) as inspect, \
             patch.object(runner.time, "sleep"):
            result = runner.cleanup_owned(self.owner, "generate", self.root, self.validate)
        self.assertTrue(result["removed"])
        self.assertFalse(result["sourceAdmitted"])
        self.assertEqual(result["originalState"]["status"], "exited")

    def test_foreign_owner_cleanup_never_mutates(self):
        foreign = self.terminal()
        foreign["ownerNonce"] = "foreign"
        with patch.object(runner, "run", return_value=(self.container + "\n").encode()) as command, \
             patch.object(runner, "inspect_container", return_value=foreign):
            with self.assertRaisesRegex(ValueError, "actual container identity"):
                runner.cleanup_owned(self.owner, "generate", self.root, self.validate)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[0][:2], ["docker", "ps"])
        self.assertEqual(json.loads((self.root / "generate.cleanup-observed.json").read_bytes())["ownerNonce"], "foreign")

    def test_created_never_started_cleanup_is_normal_and_unknown_state_refuses(self):
        def command(arguments):
            self.assertNotIn("--force", arguments)
            return (self.container + "\n").encode()
        with patch.object(runner, "run", side_effect=command), patch.object(runner, "inspect_container", return_value=self.observed):
            self.assertTrue(runner.cleanup_owned(self.owner, "generate", self.root, self.validate)["removed"])
        unknown = deepcopy(self.observed)
        unknown["status"] = "unknown"
        with patch.object(runner, "run", side_effect=command) as invoke, patch.object(runner, "inspect_container", return_value=unknown):
            with self.assertRaisesRegex(ValueError, "terminal or never-started"):
                runner.cleanup_owned(self.owner, "verify", self.root, self.validate)
        self.assertEqual(invoke.call_count, 1)

    def outer_vector(self):
        """Complete offline original-byte vector; never a candidate/runtime claim."""
        policy = json.loads((Path(runner.__file__).parent / 'development-inputs/governed-runtime.json').read_bytes())
        binding = policy['executionBinding']
        image = {'id': self.image, 'repoDigests': ['python@'+runner.IMAGE.split('@')[1]], 'declaredImage': runner.IMAGE}
        context = {'mountSources': {'implementation': str(self.root/'implementation'), 'subject': str(self.root/'subject'),
                   'tool': str(self.root/binding['implementationPackagingFilename']), 'output': str(self.root/'output')},
                   'user': '1000:1000', 'tmpfs': self.tmpfs, 'image': image}
        declarations = []
        for number, count in enumerate((3, 3, 6)):
            declarations.append({'document': 'README.md' if number < 2 else 'INSTALL.md', 'blockIndex': number,
                'blockSha256': str(number)*64, 'invocations': [
                    {'ordinal': ordinal, 'command': f'pip install fixture-{number}-{ordinal}',
                     'commandSha256': hashlib.sha256(f'pip install fixture-{number}-{ordinal}'.encode()).hexdigest(),
                     'requested': [f'fixture-{number}-{ordinal}'], 'editable': [False]} for ordinal in range(count)]})
        runtime = {key: value for key, value in policy.items() if key != 'executionBinding'}
        runtime.update(policySha256=hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest(),
                       executableSha256=binding['pythonExecutableSha256'], toolFilesSha256={'pip': binding['pipToolFilesSha256']},
                       executionBinding=deepcopy(binding))
        proposal = {'source': {'sourceSha': 'e'*40}, 'implementation': {'sourceSha': 'f'*40}, 'runtime': runtime,
                    'sourceAdmitted': False, 'candidateQualified': False, 'publishedWheelIdentity': False,
                    'documentationSequences': [{**item, 'steps': deepcopy(item['invocations'])} for item in declarations]}
        proposal_bytes = json.dumps(proposal).encode()
        receipt = {'schema': 'honua.python-governed-input-execution/v1', 'implementationSha': 'f'*40, 'subjectSourceSha': 'e'*40,
                   'image': image, 'implementationPackaging': {'filename': binding['implementationPackagingFilename'],
                   'sha256': binding['implementationPackagingSha256'], 'installed': False}, 'commands': [], 'containers': [],
                   'innerProposalSha256': hashlib.sha256(proposal_bytes).hexdigest(),
                   'sourceAdmitted': False, 'candidateQualified': False, 'publishedWheelIdentity': False}
        stdout_values = {'probe': json.dumps(runtime).encode(), 'generate': b'', 'verify': b'',
            'probe-refusals': json.dumps({'actualRefusals': ['wheel-bytes', 'wheel-name', 'image', 'interpreter', 'pip',
                'pip-entrypoint', 'wheel-policy'], 'sourceAdmitted': False, 'candidateQualified': False}).encode(),
            'mutations': json.dumps({'completeOriginalPositive': 'PASS', 'mutationsRejected': ['context-loss', 'step-loss',
                'step-reorder', 'ordinal', 'command', 'block', 'extras-superset', 'editable', 'source-before', 'source-resolved',
                'source-after', 'installed-before', 'installed-after', 'derived-command', 'install-command', 'raw-report',
                'backend-command', 'editable-identity', 'published', 'admitted', 'candidate'],
                'sourceAdmitted': False, 'candidateQualified': False, 'publishedWheelIdentity': False}).encode()}
        files = {}
        for number, action in enumerate(runner.ACTIONS, 1):
            arguments, mounts, user, tmpfs = runner.action_inputs(action, 'e'*40, context, policy)
            before = deepcopy(self.observed)
            before.update(id=str(number)*64, ownerNonce=str(number)*32, path=arguments[0], args=arguments[1:],
                          mounts=[{'Type': 'bind', 'Source': source, 'Destination': target, 'RW': not readonly}
                                  for source, target, readonly in mounts])
            after = deepcopy(before)
            after.update(status='exited', running=False, startedAt='2026-10-20T00:00:00Z', finishedAt='2026-10-20T00:01:00Z')
            cleanup = {'ownedContainerId': before['id'], 'ownerNonce': before['ownerNonce'],
                       'originalState': after, 'removed': True, 'sourceAdmitted': False}
            originals = {'stdout': stdout_values[action], 'stderr': b'',
                'attach.json': json.dumps({'returnCode': 0, 'sourceAdmitted': False}).encode(),
                'container-before.json': json.dumps(before).encode(), 'container-after.json': json.dumps(after).encode(),
                'cleanup-observed.json': json.dumps(after).encode(), 'cleanup.json': json.dumps(cleanup).encode()}
            files.update({action+'.'+suffix: value for suffix, value in originals.items()})
            receipt['commands'].append({'action': action, 'command': runner.create_command(before['ownerNonce'], arguments, mounts, user, tmpfs),
                'stdoutSha256': hashlib.sha256(originals['stdout']).hexdigest(), 'stderrSha256': hashlib.sha256(originals['stderr']).hexdigest()})
            receipt['containers'].append({'action': action, 'before': before, 'after': after, 'cleanup': cleanup})
        return receipt, {'implementation_sha': 'f'*40, 'subject_sha': 'e'*40, 'policy': policy, 'proposal_bytes': proposal_bytes,
                         'expected_documentation': declarations, 'execution_context': context, 'original_files': files}

    def test_complete_outer_original_bytes_positive_and_finite_mutations(self):
        receipt, arguments = self.outer_vector()
        result = runner.verify_execution_receipt(receipt, **arguments)
        self.assertTrue(result['innerArtifactVerificationRequired'])
        self.assertFalse(result['sourceAdmitted'])
        cases = ('missing-file', 'extra-file', 'action-loss', 'action-order', 'foreign-subject', 'foreign-implementation',
                 'foreign-image', 'foreign-mount', 'command', 'owner', 'terminal', 'cleanup', 'stream', 'coherent-probe',
                 'coherent-refusals', 'coherent-mutants', 'coherent-proposal', 'coherent-step', 'published', 'attach',
                 'unsafe-projection', 'typed-attach')
        for case in cases:
            value, inputs = deepcopy(receipt), deepcopy(arguments)
            if case == 'missing-file':
                del inputs['original_files']['probe.stdout']
            elif case == 'extra-file':
                inputs['original_files']['foreign.stdout'] = b''
            elif case == 'action-loss':
                value['containers'].pop()
            elif case == 'action-order':
                value['commands'].reverse()
            elif case == 'foreign-subject':
                value['subjectSourceSha'] = 'a'*40
            elif case == 'foreign-implementation':
                value['implementationSha'] = 'a'*40
            elif case == 'foreign-image':
                value['image']['id'] = 'sha256:'+'a'*64
            elif case == 'foreign-mount':
                value['containers'][0]['before']['mounts'][0]['Source'] += '-foreign'
            elif case == 'command':
                value['commands'][0]['command'].append('--foreign')
            elif case == 'owner':
                value['containers'][0]['before']['ownerNonce'] = '0'*32
            elif case == 'terminal':
                value['containers'][0]['after']['running'] = True
            elif case == 'cleanup':
                value['containers'][0]['cleanup']['removed'] = False
            elif case == 'stream':
                inputs['original_files']['probe.stderr'] = b'foreign-original'
            elif case.startswith('coherent-') and case not in ('coherent-proposal', 'coherent-step'):
                action = {'coherent-probe': 'probe', 'coherent-refusals': 'probe-refusals', 'coherent-mutants': 'mutations'}[case]
                inputs['original_files'][action+'.stdout'] = b'{}'
                next(item for item in value['commands'] if item['action'] == action)['stdoutSha256'] = hashlib.sha256(b'{}').hexdigest()
            elif case in ('coherent-proposal', 'coherent-step'):
                proposal = json.loads(inputs['proposal_bytes'])
                if case == 'coherent-proposal':
                    proposal['source']['sourceSha'] = 'a'*40
                else:
                    proposal['documentationSequences'][0]['steps'][0]['requested'] = ['foreign']
                inputs['proposal_bytes'] = json.dumps(proposal).encode()
                value['innerProposalSha256'] = hashlib.sha256(inputs['proposal_bytes']).hexdigest()
            elif case == 'published':
                value['publishedWheelIdentity'] = True
            elif case == 'unsafe-projection':
                value['containers'][0]['before']['environment'] = []
            elif case == 'typed-attach':
                inputs['original_files']['probe.attach.json'] = b'{"returnCode":false,"sourceAdmitted":false}'
            else:
                inputs['original_files']['probe.attach.json'] = b'{"returnCode":1,"sourceAdmitted":false}'
            with self.subTest(case=case), self.assertRaises(ValueError):
                runner.verify_execution_receipt(value, **inputs)
        runner.verify_execution_receipt(receipt, **arguments)


if __name__ == "__main__":
    unittest.main()
