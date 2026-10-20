"""Offline daemon projection/failure controls; actual image execution is separate."""
from __future__ import annotations

from copy import deepcopy
from functools import partial
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


if __name__ == "__main__":
    unittest.main()
