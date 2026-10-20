"""Synthetic tamper controls; actual PyPI/build positive is a separate workflow artifact."""
from __future__ import annotations

from copy import deepcopy
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


class DevelopmentInputsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

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
             patch.object(inputs, "requirements", return_value=[]), patch.object(inputs, "build_source_wheels") as build:
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
        proposal = {"schema": inputs.SCHEMA, "sourceAdmitted": False, "candidateQualified": False,
                    "source": selected, "runtime": {"synthetic": True}, "profiles": {}}
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

    def test_complete_proposal_positive_and_every_original_binding_mutation(self):
        original = self.complete_proposal()
        def verify(value):
            with patch.object(inputs, "source", return_value=original["source"]), \
                 patch.object(inputs, "runtime", return_value=original["runtime"]):
                return inputs.verify_proposal(value, self.root, "a" * 40, self.root, {"pip": "26.2.1"})
        self.assertEqual(len(verify(original)["profiles"]), 5)
        for mutation in ["install-command", "build-command", "scratch", "source", "runtime", "profile", "origin", "digest",
                         "report", "source-wheel", "backend-lock", "backend-inventory", "published-identity", "admission"]:
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
             self.assertRaisesRegex(ValueError, "artifact/output join"):
            inputs.verify_proposal(proposal, self.root, "a" * 40, self.root, {"pip": "26.2.1"})

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


    def test_actual_clean_git_source_positive_and_dirty_wrong_source_negative(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)  # noqa: S603, S607
        def git(*args):
            return subprocess.check_output(["git", "-C", str(self.root), *args]).decode().strip()  # noqa: S603, S607
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


if __name__ == "__main__":
    unittest.main()
