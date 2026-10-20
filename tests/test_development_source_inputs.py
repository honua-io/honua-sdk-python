"""Synthetic tamper controls; actual PyPI/build positive is a separate workflow artifact."""
from __future__ import annotations

import base64
from copy import deepcopy
import csv
import hashlib
import importlib.util
import marshal
import types
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import development_source_inputs as inputs
from scripts import python_document_inputs as documentation


class DevelopmentInputsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def wheel(self, name="dep", version="1.0", requires=()):
        filename = f"{name}-{version}-py3-none-any.whl"
        value = io.BytesIO()
        with zipfile.ZipFile(value, "w") as archive:
            metadata = f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n"
            metadata += "".join(f"Requires-Dist: {item}\n" for item in requires)
            archive.writestr(f"{name}-{version}.dist-info/METADATA", metadata)
        data = value.getvalue()
        (self.root / filename).write_bytes(data)
        return {"name": name, "version": version, "filename": filename,
                "origin": f"https://files.pythonhosted.org/packages/test/{filename}",
                "sha256": inputs.digest(data), "requiresDist": list(requires)}

    def test_complete_recursive_closure_positive(self):
        a = self.wheel("parent", requires=["child>=1"])
        b = self.wheel("child")
        inputs.validate_closure([a, b], ["parent>=1"], self.root)

    def test_missing_transitive_refuses(self):
        a = self.wheel("parent", requires=["child>=1"])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            inputs.validate_closure([a], ["parent>=1"], self.root)

    def test_artifact_changed_bytes_refuses(self):
        a = self.wheel()
        (self.root / a["filename"]).write_bytes(b"corrupt original wheel")
        with self.assertRaisesRegex(ValueError, "digest"):
            inputs.validate_closure([a], ["dep"], self.root)

    def test_coherent_metadata_substitution_refuses(self):
        a = self.wheel()
        a["version"] = "2.0"
        with self.assertRaisesRegex(ValueError, "metadata"):
            inputs.validate_closure([a], ["dep"], self.root)

    def test_unsupported_and_credentialized_origins_refuse(self):
        for origin in ["https://attacker.invalid/a.whl", "file:///tmp/a.whl", "https://user:secret@files.pythonhosted.org/packages/a.whl",
                       "https://files.pythonhosted.org/packages/a.whl?token=secret", "https://files.pythonhosted.org:443/packages/a.whl",
                       "https://files.pythonhosted.org/packages/a.tar.gz"]:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                inputs.canonical_origin(origin)

    def test_direct_dependency_refused(self):
        a = self.wheel()
        with self.assertRaisesRegex(ValueError, "direct dependency"):
            inputs.validate_closure([a], ["dep @ https://attacker.invalid/dep.whl"], self.root)

    def test_extra_and_marker_dependencies_are_required(self):
        a = self.wheel("parent", requires=['child>=1; extra == "optional"'])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            inputs.validate_closure([a], ["parent[optional]"], self.root)
        inputs.validate_closure([a], ["parent"], self.root)

    def test_unrequested_and_duplicate_artifacts_refused(self):
        a, b = self.wheel("first"), self.wheel("second")
        with self.assertRaisesRegex(ValueError, "unrequested"):
            inputs.validate_closure([a, b], ["first"], self.root)
        with self.assertRaisesRegex(ValueError, "duplicates"):
            inputs.validate_closure([a, a], ["first"], self.root)

    def test_all_original_profile_requirements_derive_from_metadata(self):
        sdk = {"version": "0.1.17", "dependencies": ["httpx>=0.27"],
               "optional-dependencies": {"grpc": ["grpcio>=1"], "geopandas": ["geopandas>=1"], "raster": ["rasterio>=1"]}}
        source = {"packages": {"honua-sdk": {"metadata": sdk}, "honua-admin": {"metadata": {"dependencies": ["honua-sdk>=0.1,<0.2"]}}}}
        self.assertEqual(set(inputs.PROFILES), {"core", "grpc", "geopandas", "raster", "combined-sdk-admin"})
        self.assertEqual(inputs.requirements(source, "combined-sdk-admin"), ["geopandas>=1", "grpcio>=1", "httpx>=0.27", "rasterio>=1"])
        for name in ["grpc", "geopandas", "raster"]:
            self.assertIn(sdk["optional-dependencies"][name][0], inputs.requirements(source, name))
        broken = deepcopy(source)
        broken["packages"]["honua-admin"]["metadata"]["dependencies"] = ["honua-sdk>=9"]
        with self.assertRaisesRegex(ValueError, "excludes"):
            inputs.requirements(broken, "combined-sdk-admin")

    def test_runtime_refusal_precedes_resolver_or_install(self):
        with patch.object(inputs, "source", return_value={}), patch.object(inputs, "resolve") as resolver:
            with self.assertRaisesRegex(ValueError, "runtime"):
                inputs.generate(self.root, "a" * 40, self.root / "output", {})
            resolver.assert_not_called()
            self.assertFalse((self.root / "output").exists())

    def test_wrong_source_refusal_precedes_resolver_or_install(self):
        with patch.object(inputs, "resolve") as resolver:
            with self.assertRaisesRegex(ValueError, "immutable revision"):
                inputs.generate(self.root, "trunk", self.root / "output", {})
            resolver.assert_not_called()

    def test_changed_source_refuses_before_backend_install(self):
        with patch.object(inputs, "source", side_effect=[{"sourceSha": "a"}, {"sourceSha": "b"}]), \
             patch.object(inputs, "runtime", return_value={}), patch.object(inputs, "resolve", return_value={}), \
             patch.object(inputs, "requirements", return_value=[]), patch.object(inputs, "build_source_wheels") as build, \
             patch.object(inputs, "implementation", return_value={}):
            with self.assertRaisesRegex(ValueError, "before backend"):
                inputs.generate(self.root / "source", "a", self.root / "output", {})
            build.assert_not_called()

    def complete_proposal(self):
        # Complete synthetic original-byte oracle vectors, never a live resolver result.
        revision = "a" * 40
        selected = {"sourceSha": revision, "packages": {
            "honua-sdk": {"metadata": {"version": "0.1.0", "dependencies": ["dep>=1"],
                        "optional-dependencies": {"grpc": ["dep>=1"], "geopandas": ["dep>=1"], "raster": ["dep>=1"]}}},
            "honua-admin": {"metadata": {"version": "0.1.0", "dependencies": ["honua-sdk>=0.1,<0.2"]}}}}
        proposal = {"schema": inputs.SCHEMA, "sourceAdmitted": False, "candidateQualified": False, "publishedWheelIdentity": False,
                    "implementation": {"sourceSha": "b" * 40, "synthetic": True}, "source": selected, "runtime": {"synthetic": True}, "profiles": {}}
        artifact = self.wheel()
        backend = self.wheel("hatchling", "1.30.1")
        for name in ["build", *inputs.PROFILES]:
            directory = self.root / name
            directory.mkdir()
            item = backend if name == "build" else artifact
            (directory / item["filename"]).write_bytes((self.root / item["filename"]).read_bytes())
            requested = ["hatchling==1.30.1"] if name == "build" else inputs.requirements(selected, name)
            scratch = Path(tempfile.gettempdir()).resolve() / "honua-development-resolve-abcdefgh"
            raw = {"version": "1", "pip_version": "26.2.1", "environment": inputs.default_environment(),
                   "install": [{"metadata": {"name": item["name"], "version": item["version"]},
                                "download_info": {"url": item["origin"], "archive_info": {"hashes": {"sha256": item["sha256"]}}}}]}
            report = json.dumps(raw).encode()
            (directory / "pip-report.json").write_bytes(report)
            (directory / "resolver.stdout").write_bytes(b"synthetic resolver output")
            value = {"requested": requested, "command": inputs.resolver_command(requested, scratch),
                     "scratchRoot": str(scratch), "environment": inputs.default_environment(), "artifacts": [deepcopy(item)],
                     "reportSha256": inputs.digest(report), "stdoutSha256": inputs.digest(b"synthetic resolver output")}
            if name == "build":
                proposal["build"] = value
            else:
                proposal["profiles"][name] = value
        (self.root / "source-wheels").mkdir()
        wheels = []
        for name in ["honua_sdk", "honua_admin"]:
            item = self.wheel(name, "0.1.0")
            (self.root / "source-wheels" / item["filename"]).write_bytes((self.root / item["filename"]).read_bytes())
            item.update(name=name.replace("_", "-"), sourceSha=revision, publishedIdentity=False)
            wheels.append(item)
        scratch = Path(tempfile.gettempdir()).resolve() / "honua-development-build-abcdefgh"
        install, build = inputs.build_commands(scratch, self.root)
        (self.root / "source-build.stdout").write_bytes(b"synthetic build output")
        proposal["sourceBuild"] = {"scratchRoot": str(scratch), "backendInstallCommand": install, "buildCommand": build,
                                   "installedBackend": {"hatchling": "1.30.1"},
                                   "backendLock": f'hatchling==1.30.1 --hash=sha256:{backend["sha256"]}\n',
                                   "stdoutSha256": inputs.digest(b"synthetic build output"), "wheels": wheels}
        return proposal

    def test_complete_artifact_stage_positive_and_every_original_binding_mutation(self):
        original = self.complete_proposal()
        def verify(value):
            with patch.object(inputs, "source", return_value=original["source"]), \
                 patch.object(inputs, "runtime", return_value=original["runtime"]), \
                 patch.object(inputs, "implementation", return_value=original["implementation"]):
                return inputs.verify_artifact_inputs(value, self.root, "a" * 40, self.root, {"pip": "26.2.1"})
        self.assertEqual(len(verify(original)["profiles"]), 5)
        for mutation in ["install-command", "build-command", "scratch", "source", "runtime", "profile", "origin", "digest",
                         "report", "source-wheel", "backend-lock", "backend-inventory", "published-identity", "top-level-published-identity", "admission"]:
            value = deepcopy(original)
            if mutation == "install-command":
                value["sourceBuild"]["backendInstallCommand"].remove("--require-hashes")
            elif mutation == "build-command":
                value["sourceBuild"]["buildCommand"].remove("--no-deps")
            elif mutation == "scratch":
                value["sourceBuild"]["scratchRoot"] = str(Path(tempfile.gettempdir()) / "other")
            elif mutation == "source":
                value["source"]["sourceSha"] = "f" * 40
            elif mutation == "runtime":
                value["runtime"] = {"synthetic": False}
            elif mutation == "profile":
                del value["profiles"]["raster"]
            elif mutation == "origin":
                value["profiles"]["core"]["artifacts"][0]["origin"] = "https://attacker.invalid/dep.whl"
            elif mutation == "digest":
                value["profiles"]["core"]["artifacts"][0]["sha256"] = "0" * 64
            elif mutation == "report":
                value["profiles"]["core"]["reportSha256"] = "0" * 64
            elif mutation == "source-wheel":
                value["sourceBuild"]["wheels"][0]["sha256"] = "0" * 64
            elif mutation == "backend-lock":
                value["sourceBuild"]["backendLock"] = "hatchling>=1\n"
            elif mutation == "backend-inventory":
                value["sourceBuild"]["installedBackend"]["hatchling"] = "9"
            elif mutation == "published-identity":
                value["sourceBuild"]["wheels"][0]["publishedIdentity"] = True
            elif mutation == "top-level-published-identity":
                value["publishedWheelIdentity"] = True
            elif mutation == "admission":
                value["sourceAdmitted"] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify(value)


    def test_rehashed_original_report_substitution_refuses(self):
        proposal = self.complete_proposal()
        report = self.root / "core/pip-report.json"
        raw = json.loads(report.read_bytes())
        raw["install"][0]["metadata"]["version"] = "9.0"
        report.write_text(json.dumps(raw))
        proposal["profiles"]["core"]["reportSha256"] = inputs.digest(report.read_bytes())
        with patch.object(inputs, "source", return_value=proposal["source"]), \
             patch.object(inputs, "runtime", return_value=proposal["runtime"]), \
             patch.object(inputs, "implementation", return_value=proposal["implementation"]), \
             self.assertRaisesRegex(ValueError, "artifact/output join"):
            inputs.verify_artifact_inputs(proposal, self.root, "a" * 40, self.root, {"pip": "26.2.1"})

    def test_failed_private_origin_never_persists_raw_output(self):
        private_reports = []
        def resolver(command):
            path = Path(command[command.index("--report") + 1])
            private_reports.append(path)
            path.write_text(json.dumps({"version": "1", "pip_version": "26.2.1", "install": [
                {"download_info": {"url": "https://user:secret@files.pythonhosted.org/packages/a.whl"}}]}))
            return b"secret private resolver output"
        with patch.object(inputs, "run", side_effect=resolver), patch.object(inputs, "urlopen") as network:
            with self.assertRaisesRegex(ValueError, "origin"):
                inputs.resolve(["dep"], self.root / "refused")
            network.assert_not_called()
        self.assertFalse(list((self.root / "refused").iterdir()))
        self.assertFalse(private_reports[0].exists())

    def test_real_pip_ignores_ambient_config_and_proxy_inputs(self):
        malicious = self.root / "pip.conf"
        malicious.write_text("[global]\nextra-index-url=https://user:secret@attacker.invalid/simple\n")
        with patch.dict(os.environ, {"PIP_CONFIG_FILE": str(malicious), "PIP_INDEX_URL": "https://user:secret@attacker.invalid",
                                     "HTTPS_PROXY": "https://secret@attacker.invalid", "PYTHONPATH": "untrusted"}):
            observed = inputs.run([inputs.sys.executable, "-m", "pip", "--isolated", "config", "list"]).decode()
        self.assertNotIn("secret", observed)
        self.assertNotIn("attacker", observed)
        self.assertNotIn("extra-index", observed)


    def test_producer_workflow_requires_string_run_values_and_block_scalars(self):
        path = Path(__file__).resolve().parents[1] / ".github/workflows/development-source-inputs.yml"
        text = path.read_text()
        values = [line.split("run:", 1)[1].strip() for line in text.splitlines() if line.strip().startswith("run:")]
        self.assertEqual(values, ["|", "|", "|"])
        self.assertIn("yaml.safe_load(path.read_text())", text)
        self.assertIn("assert isinstance(step['run'], str)", text)
        self.assertIn("--require-hashes --only-binary=:all:", text)


    def test_actual_clean_git_source_positive_and_dirty_wrong_source_negative(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)  # noqa: S603, S607
        def git(*args):
            return subprocess.check_output(["git", "-C", str(self.root), *args]).decode().strip()  # noqa: S603, S607
        git("config", "core.autocrlf", "false")
        git("config", "user.name", "Fixture")
        git("config", "user.email", "fixture@example.invalid")
        git("remote", "add", "origin", inputs.REPOSITORY)
        for name in ["honua-sdk", "honua-admin"]:
            path = self.root / "packages" / name / "pyproject.toml"
            path.parent.mkdir(parents=True)
            path.write_text(f'[build-system]\nrequires=["hatchling==1.30.1"]\nbuild-backend="hatchling.build"\n[project]\nname="{name}"\nversion="0.1.0"\ndependencies=[]\n')
        git("add", ".")
        git("commit", "-qm", "fixture")
        revision = git("rev-parse", "HEAD")
        observed = inputs.source(self.root, revision)
        self.assertEqual(len(observed["files"]), 2)
        with self.assertRaisesRegex(ValueError, "wrong immutable"):
            inputs.source(self.root, "f" * 40)
        path.write_text(path.read_text() + "# changed input\n")
        with self.assertRaisesRegex(ValueError, "dirty"):
            inputs.source(self.root, revision)

    def test_actual_reviewed_git_symlink_and_independent_refusals(self):
        self.test_actual_clean_git_source_positive_and_dirty_wrong_source_negative()
        def git(*args):
            return subprocess.check_output(["git", "-C", str(self.root), *args]).decode().strip()  # noqa: S603, S607
        git("restore", "packages/honua-admin/pyproject.toml")
        (self.root / "AGENTS.md").write_text("Immutable source instructions\n")
        alias = self.root / "CLAUDE.md"
        if os.name == "nt":
            # Windows checkouts without link privileges must refuse inspectability;
            # the reviewed production runtime is Linux and runs the real link positive.
            alias.write_text("AGENTS.md")
            blob = git("hash-object", "-w", str(alias))
            git("add", "AGENTS.md")
            git("update-index", "--add", "--cacheinfo", "120000," + blob + ",CLAUDE.md")
            git("commit", "-qm", "uninspectable link fixture")
            with self.assertRaises(ValueError):
                inputs.source(self.root, git("rev-parse", "HEAD"))
            return
        alias.symlink_to("AGENTS.md")
        git("add", ".")
        git("commit", "-qm", "reviewed alias fixture")
        observed = inputs.source(self.root, git("rev-parse", "HEAD"))
        self.assertEqual(observed["files"]["CLAUDE.md"]["linkTarget"], "AGENTS.md")
        self.assertEqual(observed["files"]["CLAUDE.md"]["targetSha256"], observed["files"]["AGENTS.md"]["sha256"])
        for case in ["changed", "foreign", "escaping", "package", "changed-target"]:
            # Every negative starts from a separately revalidated clean positive.
            inputs.source(self.root, git("rev-parse", "HEAD"))
            extra = None
            if case in ["changed", "escaping"]:
                alias.unlink()
                alias.symlink_to("./AGENTS.md" if case == "changed" else "../AGENTS.md")
            elif case == "foreign":
                extra = self.root / "foreign.md"
                extra.symlink_to("AGENTS.md")
            elif case == "package":
                extra = self.root / "packages/honua-sdk/foreign.py"
                extra.symlink_to("../../AGENTS.md")
            else:
                (self.root / "AGENTS.md").write_text("changed immutable target\n")
            if case != "changed-target":
                git("add", ".")
                git("commit", "-qm", "negative link fixture")
            with self.subTest(case=case), self.assertRaises(ValueError):
                inputs.source(self.root, git("rev-parse", "HEAD"))
            if extra:
                extra.unlink()
            if alias.is_symlink():
                alias.unlink()
            alias.symlink_to("AGENTS.md")
            (self.root / "AGENTS.md").write_text("Immutable source instructions\n")
            git("add", ".")
            if git("status", "--porcelain"):
                git("commit", "-qm", "restored clean link fixture")


    def test_finite_editable_source_census_refuses_extra_module_and_symlink(self):
        checkout = self.root / "copy"
        expected = {}
        for name in ("honua-sdk", "honua-admin"):
            target = checkout / "packages" / name / "module.py"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"VALUE = 1\n")
            expected[target.relative_to(checkout).as_posix()] = {"sha256": inputs.digest(target.read_bytes())}
        source = {"files": expected}
        self.assertEqual(documentation.source_hashes(inputs, source, checkout), {k: v["sha256"] for k, v in expected.items()})
        extra = checkout / "packages/honua-sdk/extra.py"
        extra.write_bytes(b"MUTATION = True\n")
        with self.assertRaisesRegex(ValueError, "finite tracked"):
            documentation.source_hashes(inputs, source, checkout)
        extra.unlink()
        extra.symlink_to("module.py")
        with self.assertRaisesRegex(ValueError, "symlink"):
            documentation.source_hashes(inputs, source, checkout)
        extra.unlink()
        (extra.parent / "empty-extra").mkdir()
        with self.assertRaisesRegex(ValueError, "finite tracked"):
            documentation.source_hashes(inputs, source, checkout)

    def test_original_document_plan_matches_independent_governed_block_inventory(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/python_source_install_blocks.json").read_text())
        source = {"files": {name: {"gitBlob": item["gitBlob"]} for name, item in fixture["documents"].items()}}
        for name, item in fixture["documents"].items():
            (self.root / name).write_text(item["text"])
        actual = documentation.plan(inputs, self.root, source)
        self.assertEqual(len(actual), 3)
        self.assertEqual(sum(len(item["invocations"]) for item in actual), 12)
        for observed, expected in zip(actual, fixture["expectedBlocks"], strict=True):
            self.assertEqual((observed["document"], observed["blockIndex"], observed["blockSha256"]),
                             (expected["document"], expected["index"], expected["sha256"]))
            self.assertEqual([item["command"] for item in observed["invocations"]], expected["commands"])
            self.assertEqual([item["ordinal"] for item in observed["invocations"]], list(range(len(expected["commands"]))))
        self.assertEqual(actual[1]["invocations"][0]["editable"], [True])
        self.assertEqual(actual[1]["invocations"][2]["requested"], ["pytest", "pytest-cov", "ruff", "mypy"])
        original = fixture["documents"]["README.md"]["text"]
        for replacement in ("pip install --extra-index-url https://foreign.invalid packages/honua-sdk",
                            "pip install -e /foreign/source", "pip install packages/honua-sdk --no-compile"):
            (self.root / "README.md").write_text(original.replace("pip install ./packages/honua-sdk", replacement, 1))
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                documentation.plan(inputs, self.root, source)

    def test_actual_default_pip_generated_file_positive_and_extra_cache_script_mutants(self):
        if os.name == "nt":
            # This production input policy is Linux-only; Windows must refuse it
            # before attempting the POSIX installed-file transformation model.
            policy = json.loads((Path(inputs.__file__).parent / "development-inputs/runtime.json").read_text())
            with self.assertRaisesRegex(ValueError, "runtime differs"):
                inputs.runtime(policy)
            return
        directory = self.root / "wheelhouse"
        directory.mkdir()
        metadata_dir = "finite_probe-1.0.dist-info"
        members = {"finite_probe.py": b"def main():\n    return 0\n",
                   metadata_dir + "/METADATA": b"Metadata-Version: 2.3\nName: finite-probe\nVersion: 1.0\n",
                   metadata_dir + "/WHEEL": b"Wheel-Version: 1.0\nGenerator: owned-control\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
                   metadata_dir + "/entry_points.txt": b"[console_scripts]\nfinite-probe = finite_probe:main\n"}
        record = io.StringIO(newline="")
        writer = csv.writer(record)
        for name, content in members.items():
            digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
            writer.writerow([name, "sha256=" + digest, len(content)])
        writer.writerow([metadata_dir + "/RECORD", "", ""])
        members[metadata_dir + "/RECORD"] = record.getvalue().encode()
        archive = directory / "finite_probe-1.0-py3-none-any.whl"
        with zipfile.ZipFile(archive, "w") as wheel:
            for name, content in members.items():
                wheel.writestr(name, content)
        environment = self.root / "environment"
        inputs.run([inputs.sys.executable, "-m", "venv", "--without-pip", str(environment)])
        python = environment / "bin/python"
        inputs.run([inputs.sys.executable, "-m", "pip", "--isolated", "--python", str(python), "install", "--no-index", "--no-deps", str(archive)])
        observed = documentation.inventory(inputs, python)["finite-probe"]
        try:
            documentation.installed_wheel_bytes(inputs, observed, archive)
        except ValueError:
            # Retain only this authored synthetic wheel's original bytes on the
            # hosted failure path. The real verifier refusal remains unchanged.
            filename = str(Path(observed["sitePackages"]) / "finite_probe.py")
            cache = str(Path(importlib.util.cache_from_source(filename)).relative_to(observed["sitePackages"]))
            raw = base64.b64decode(observed["generated"][cache], validate=True)
            actual = marshal.loads(raw[16:])  # noqa: S302 -- only the authored synthetic wheel compiled by owned pip
            expected = compile(members["finite_probe.py"], filename, "exec", dont_inherit=True, optimize=0)
            fields = ["co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals", "co_stacksize", "co_flags",
                      "co_code", "co_consts", "co_names", "co_varnames", "co_filename", "co_name", "co_qualname",
                      "co_firstlineno", "co_linetable", "co_exceptiontable", "co_freevars", "co_cellvars"]
            def differences(left, right, prefix=""):
                result = []
                for field in fields:
                    first, second = getattr(left, field), getattr(right, field)
                    if field == "co_consts":
                        if len(first) != len(second):
                            result.append(prefix + field + ".length")
                        for ordinal, (a, b) in enumerate(zip(first, second, strict=False)):
                            if isinstance(a, types.CodeType) and isinstance(b, types.CodeType):
                                result.extend(differences(a, b, prefix + "constant" + str(ordinal) + "."))
                            elif type(a) is not type(b) or a != b:
                                result.append(prefix + field + "." + str(ordinal))
                    elif type(first) is not type(second) or first != second:
                        result.append(prefix + field)
                return result
            diagnostic = {"actualFilename": actual.co_filename, "expectedFilename": filename,
                          "codeObjectEqual": actual == expected, "fieldDifferences": differences(actual, expected),
                          "actualMarshalSha256": inputs.digest(raw[16:]), "expectedMarshalSha256": inputs.digest(marshal.dumps(expected)),
                          "actualRemarshalEqual": marshal.dumps(actual) == marshal.dumps(expected), "header": raw[:16].hex()}
            print("ORIGINAL_PIP_BYTECODE_DIAGNOSTIC " + json.dumps(diagnostic, sort_keys=True), flush=True)
            if os.environ.get("RUNNER_TEMP"):
                output = Path(os.environ["RUNNER_TEMP"]) / "development-pip-control"
                output.mkdir(exist_ok=True)
                (output / "original.pyc").write_bytes(raw)
                (output / "expected.marshal").write_bytes(marshal.dumps(expected))
                (output / "verified-source.py").write_bytes(members["finite_probe.py"])
                (output / "diagnostic.json").write_text(json.dumps(diagnostic, indent=2) + "\n")
            raise
        for mutation in ("extra", "cache", "script", "record", "installer"):
            value = deepcopy(observed)
            if mutation == "extra":
                value["files"]["unmodeled.py"] = inputs.digest(b"EXTRA=True\n")
                value["sizes"]["unmodeled.py"] = 11
            else:
                key = next(k for k in value["generated"] if
                           (k.endswith(".pyc") if mutation == "cache" else
                            k.startswith("../") if mutation == "script" else
                            k.endswith("/RECORD") if mutation == "record" else k.endswith("/INSTALLER")))
                data = base64.b64decode(value["generated"][key]) + b"MUTATION"
                value["generated"][key] = base64.b64encode(data).decode()
                value["files"][key] = inputs.digest(data)
                value["sizes"][key] = len(data)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                documentation.installed_wheel_bytes(inputs, value, archive)
        site = Path(observed["sitePackages"])
        (site / "unrecorded_extra.py").write_bytes(b"EXTRA = True\n")
        with self.assertRaises(subprocess.CalledProcessError):
            documentation.inventory(inputs, python)


if __name__ == "__main__":
    unittest.main()
