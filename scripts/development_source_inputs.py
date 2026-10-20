"""Produce review-only immutable Python development inputs; never admit or publish them."""
from __future__ import annotations

import argparse
import email.parser
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import shutil
import re
import subprocess
import sys
import tempfile
import tomllib
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen
import zipfile

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename

if __package__:
    from . import python_document_inputs as documentation
else:
    import python_document_inputs as documentation

REPOSITORY = "https://github.com/honua-io/honua-sdk-python"
PROFILES = {"core": (), "grpc": ("grpc",), "geopandas": ("geopandas",), "raster": ("raster",),
            "combined-sdk-admin": ("grpc", "geopandas", "raster")}
SCHEMA = "honua.python-development-inputs/v1"
INDEX = "https://pypi.org/simple"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(args: list[str], *, cwd: Path | None = None) -> bytes:
    # Pip's special PIP_CONFIG_FILE handling also applies in isolated mode.
    # No proxy/index/PYTHONPATH startup overrides enter a resolver or backend.
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "SYSTEMROOT") if key in os.environ}
    env.update(PIP_CONFIG_FILE=os.devnull, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.check_output(args, cwd=cwd, env=env, stderr=subprocess.PIPE)  # noqa: S603


def runtime(policy: dict) -> dict:
    observed = {"schema": "honua.python-development-runtime/v1", "python": platform.python_version(),
                "implementation": platform.python_implementation(), "system": platform.system(),
                "machine": platform.machine(), "pip": importlib.metadata.version("pip"),
                "packaging": importlib.metadata.version("packaging")}
    if observed != policy:
        raise ValueError("runtime differs from reviewed exact policy")
    tool_bytes = {}
    for name in ("pip", "packaging"):
        distribution = importlib.metadata.distribution(name)
        files = {str(path): digest(distribution.locate_file(path).read_bytes()) for path in distribution.files or []
                 if path.suffix != ".pyc" and distribution.locate_file(path).is_file()}
        if not files:
            raise ValueError("runtime tool bytes are uninspectable")
        tool_bytes[name] = digest(json.dumps(files, sort_keys=True).encode())
    return {**observed, "toolFilesSha256": tool_bytes, "executableSha256": digest(Path(sys.executable).resolve().read_bytes()),
            "policySha256": digest(json.dumps(policy, sort_keys=True).encode()),
            "executable": str(Path(sys.executable).resolve())}


def source(root: Path, revision: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("source requires full immutable revision")
    if run(["git", "rev-parse", "HEAD"], cwd=root).decode().strip() != revision:
        raise ValueError("wrong immutable checkout")
    if run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root).strip():
        raise ValueError("source checkout is dirty or has untracked inputs")
    origin = run(["git", "remote", "get-url", "origin"], cwd=root).decode().strip()
    if origin.removesuffix(".git") not in (REPOSITORY, "git@github.com:honua-io/honua-sdk-python"):
        raise ValueError("source repository differs")
    files = {}
    entries = run(["git", "ls-tree", "-rz", "--full-tree", revision], cwd=root).split(b"\0")
    tracked = {entry.split(b"\t", 1)[1].decode(): entry.split(b"\t", 1)[0].decode().split() for entry in entries if entry}
    for entry in entries:
        if not entry:
            continue
        meta, name = entry.split(b"\t", 1)
        mode, kind, blob = meta.decode().split()
        path = name.decode()
        if kind != "blob" or mode not in ("100644", "100755", "120000"):
            raise ValueError("unsupported source entry")
        link = None
        if mode == "120000":
            if (path != "CLAUDE.md" or not (root / path).is_symlink()
                    or os.readlink(root / path) != "AGENTS.md"
                    or tracked.get("AGENTS.md", [])[:2] != ["100644", "blob"]
                    or (root / "AGENTS.md").is_symlink()):
                raise ValueError("unreviewed or escaping source symlink")
            data = os.fsencode(os.readlink(root / path))
            target = (root / "AGENTS.md").read_bytes()
            target_blob = hashlib.sha1(b"blob " + str(len(target)).encode() + b"\0" + target).hexdigest()  # noqa: S324
            if target_blob != tracked["AGENTS.md"][2]:
                raise ValueError("symlink immutable target differs")
            link = {"linkTarget": "AGENTS.md", "targetGitBlob": target_blob, "targetSha256": digest(target)}
        else:
            if (root / path).is_symlink():
                raise ValueError("regular source replaced with symlink")
            data = (root / path).read_bytes()
        if hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != blob:  # noqa: S324
            raise ValueError("source input differs from immutable blob")
        files[path] = {"gitBlob": blob, "sha256": digest(data), "mode": mode, **(link or {})}
    packages = {}
    for name in ("honua-sdk", "honua-admin"):
        path = f"packages/{name}/pyproject.toml"
        spec = tomllib.loads((root / path).read_text())
        if spec["project"]["name"] != name or spec["build-system"] != {
                "requires": ["hatchling==1.30.1"], "build-backend": "hatchling.build"}:
            raise ValueError("unreviewed package or build backend")
        packages[name] = {"sourceSha": revision, "metadata": spec["project"], "buildSystem": spec["build-system"]}
    return {"repository": REPOSITORY, "sourceSha": revision, "files": files, "packages": packages}


def requirements(inputs: dict, profile: str) -> list[str]:
    if profile not in PROFILES:
        raise ValueError("unknown development profile")
    sdk = inputs["packages"]["honua-sdk"]["metadata"]
    result = list(sdk["dependencies"])
    for extra in PROFILES[profile]:
        result.extend(sdk["optional-dependencies"][extra])
    if profile == "combined-sdk-admin":
        for dependency in inputs["packages"]["honua-admin"]["metadata"]["dependencies"]:
            req = Requirement(dependency)
            if canonicalize_name(req.name) == "honua-sdk":
                if sdk["version"] not in req.specifier:
                    raise ValueError("source Admin dependency excludes source SDK")
            else:
                result.append(dependency)
    return sorted(set(result))


def canonical_origin(url: str) -> str:
    value = urlsplit(url)
    if (value.scheme != "https" or value.hostname != "files.pythonhosted.org" or value.port is not None
            or value.username or value.password or value.query or value.fragment
            or not value.path.startswith("/packages/") or not value.path.endswith(".whl")):
        raise ValueError("unsupported artifact origin")
    filename = unquote(value.path.rsplit("/", 1)[-1])
    if Path(filename).name != filename or "\\" in filename:
        raise ValueError("artifact filename is unsafe")
    parse_wheel_filename(filename)
    return filename


def wheel_metadata(data: bytes, filename: str) -> tuple[str, str, list[str]]:
    wheel_name, wheel_version, _, _ = parse_wheel_filename(filename)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        if len(names) != 1 or archive.testzip() is not None:
            raise ValueError("invalid wheel archive")
        metadata = email.parser.BytesParser().parsebytes(archive.read(names[0]))
    name, version = str(metadata["Name"]), str(metadata["Version"])
    if canonicalize_name(name) != wheel_name or version != str(wheel_version):
        raise ValueError("wheel identity mismatch")
    return canonicalize_name(name), version, metadata.get_all("Requires-Dist", [])


def validate_closure(artifacts: list[dict], requested: list[str], directory: Path) -> None:
    installed = {}
    for item in artifacts:
        if canonical_origin(item["origin"]) != item["filename"]:
            raise ValueError("artifact filename differs from origin")
        data = (directory / item["filename"]).read_bytes()
        if digest(data) != item["sha256"]:
            raise ValueError("artifact digest differs")
        name, version, dependencies = wheel_metadata(data, item["filename"])
        if name != item["name"] or version != item["version"] or dependencies != item["requiresDist"] or name in installed:
            raise ValueError("artifact metadata differs or duplicates")
        installed[name] = item
    pending = [(Requirement(value), "") for value in requested]
    seen = set()
    while pending:
        req, extra = pending.pop()
        if req.url:
            raise ValueError("direct dependency origin refused")
        if req.marker and not req.marker.evaluate({"extra": extra}):
            continue
        name = canonicalize_name(req.name)
        if name not in installed or installed[name]["version"] not in req.specifier:
            raise ValueError("incomplete dependency closure")
        extras = req.extras or {""}
        for selected in extras:
            if (name, selected) in seen:
                continue
            seen.add((name, selected))
            pending.extend((Requirement(value), selected) for value in installed[name]["requiresDist"])
    if {name for name, _ in seen} != set(installed):
        raise ValueError("unrequested artifacts in closure")


def scratch_identity(value: str, prefix: str) -> Path:
    path = Path(value)
    if (not path.is_absolute() or path != path.resolve() or path.parent != Path(tempfile.gettempdir()).resolve()
            or not re.fullmatch(re.escape(prefix) + r"[a-z0-9_]{8}", path.name)):
        raise ValueError("unbound private scratch identity")
    return path


def resolver_command(requested: list[str], scratch: Path) -> list[str]:
    return [sys.executable, "-m", "pip", "--isolated", "install", "--dry-run", "--ignore-installed",
            "--only-binary=:all:", "--index-url", INDEX, "--disable-pip-version-check", "--no-input",
            "--report", str(scratch / "pip-report.json"), *requested]


def download_artifacts(selections: list[dict], directory: Path) -> list[dict]:
    artifacts = []
    for selected in selections:
        info = selected["download_info"]
        url = info["url"]
        filename = canonical_origin(url)
        expected = info["archive_info"]["hashes"]["sha256"]
        metadata = selected["metadata"]
        registry_url = f'https://pypi.org/pypi/{canonicalize_name(metadata["name"])}/{metadata["version"]}/json'
        with urlopen(registry_url, timeout=60) as response:  # noqa: S310
            registry = json.load(response)
        if not any(x["url"] == url and x["filename"] == filename and x["digests"]["sha256"] == expected
                   for x in registry["urls"]):
            raise ValueError("artifact is not in canonical registry response")
        with urlopen(url, timeout=120) as response:  # noqa: S310
            if response.url != url:
                raise ValueError("artifact redirect refused")
            data = response.read()
        if digest(data) != expected:
            raise ValueError("download differs from resolver digest")
        name, version, dependencies = wheel_metadata(data, filename)
        if name != canonicalize_name(metadata["name"]) or version != metadata["version"]:
            raise ValueError("download metadata differs from original resolver")
        target = directory / filename
        if target.exists() and digest(target.read_bytes()) != expected:
            raise ValueError("artifact filename collision")
        target.write_bytes(data)
        artifacts.append({"name": name, "version": version, "filename": filename, "origin": url,
                          "sha256": expected, "requiresDist": dependencies})
    return artifacts


def resolve(requested: list[str], directory: Path) -> dict:
    directory.mkdir()
    # Raw output/report remain outside the public destination until every URL,
    # downloaded byte and dependency has been validated. Failed private data dies here.
    with tempfile.TemporaryDirectory(prefix="honua-development-resolve-", dir=str(Path(tempfile.gettempdir()).resolve())) as temporary:
        scratch = scratch_identity(temporary, "honua-development-resolve-")
        report = scratch / "pip-report.json"
        command = resolver_command(requested, scratch)
        stdout = run(command)
        observed = json.loads(report.read_bytes())
        if observed.get("version") != "1" or observed.get("pip_version") != importlib.metadata.version("pip"):
            raise ValueError("unreviewed resolver report")
        # Validate ALL origins before retaining even one report or artifact.
        for selected in observed["install"]:
            canonical_origin(selected["download_info"]["url"])
        artifacts = download_artifacts(observed["install"], directory)
        validate_closure(artifacts, requested, directory)
        shutil.copyfile(report, directory / "pip-report.json")
        (directory / "resolver.stdout").write_bytes(stdout)
        return {"requested": requested, "command": command, "scratchRoot": str(scratch),
                "reportSha256": digest(report.read_bytes()), "stdoutSha256": digest(stdout),
                "environment": observed["environment"], "artifacts": artifacts}


def build_commands(scratch: Path, destination: Path) -> tuple[list[str], list[str]]:
    python = scratch / "backend/bin/python"
    install = [sys.executable, "-m", "pip", "--isolated", "--python", str(python), "install", "--no-index",
               "--find-links", str(destination / "build"), "--require-hashes", "-r", str(scratch / "backend.lock")]
    build = [sys.executable, "-m", "pip", "--isolated", "--python", str(python), "wheel",
             "--no-build-isolation", "--no-deps", "--no-index", "--wheel-dir", str(destination / "source-wheels"),
             str(scratch / "source/packages/honua-sdk"), str(scratch / "source/packages/honua-admin")]
    return install, build


def build_source_wheels(inputs: dict, root: Path, destination: Path, build: dict) -> dict:
    """Build only immutable tracked bytes using the independently captured backend closure."""
    with tempfile.TemporaryDirectory(prefix="honua-development-build-", dir=str(Path(tempfile.gettempdir()).resolve())) as temporary:
        scratch = scratch_identity(temporary, "honua-development-build-")
        checkout = scratch / "source"
        for name in inputs["files"]:
            if name.startswith(("packages/honua-sdk/", "packages/honua-admin/")):
                target = checkout / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((root / name).read_bytes())
        environment = scratch / "backend"
        run([sys.executable, "-m", "venv", "--without-pip", str(environment)])
        python = environment / "bin/python"
        lock = scratch / "backend.lock"
        lock.write_text("\n".join(f'{x["name"]}=={x["version"]} --hash=sha256:{x["sha256"]}'
                                  for x in build["artifacts"]) + "\n")
        command, build_command = build_commands(scratch, destination)
        if inputs != source(root, inputs["sourceSha"]):
            raise ValueError("source changed before backend install")
        installed = run(command)
        inventory = json.loads(run([str(python), "-c", "import importlib.metadata,json; print(json.dumps({x.metadata['Name']:x.version for x in importlib.metadata.distributions()}))"]))
        expected = {x["name"]: x["version"] for x in build["artifacts"]}
        if {canonicalize_name(k): v for k, v in inventory.items()} != expected:
            raise ValueError("installed backend closure differs")
        output = run(build_command)
        wheels = []
        for path in sorted((destination / "source-wheels").glob("*.whl")):
            data = path.read_bytes()
            name, version, dependencies = wheel_metadata(data, path.name)
            if name not in inputs["packages"] or version != inputs["packages"][name]["metadata"]["version"]:
                raise ValueError("source-built package metadata differs")
            wheels.append({"name": name, "version": version, "filename": path.name, "sha256": digest(data),
                           "requiresDist": dependencies, "sourceSha": inputs["sourceSha"], "publishedIdentity": False})
        if {x["name"] for x in wheels} != set(inputs["packages"]):
            raise ValueError("incomplete source wheel build")
        (destination / "source-build.stdout").write_bytes(installed + output)
        return {"scratchRoot": str(scratch), "backendInstallCommand": command, "buildCommand": build_command, "backendLock": lock.read_text(),
                "stdoutSha256": digest(installed + output), "installedBackend": inventory, "wheels": wheels}


def implementation() -> dict:
    root = Path(__file__).resolve().parents[1]
    revision = run(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    inspected = source(root, revision)
    paths = ("scripts/development_source_inputs.py", "scripts/python_document_inputs.py")
    return {"repository": REPOSITORY, "sourceSha": revision,
            "files": {path: inspected["files"][path] for path in paths}}


def verify_resolution(value: dict, requested: list[str], directory: Path, policy: dict) -> None:
    if value["requested"] != requested:
        raise ValueError("profile requirements differ")
    scratch = scratch_identity(value["scratchRoot"], "honua-development-resolve-")
    expected_command = resolver_command(requested, scratch)
    if value["command"] != expected_command or value["environment"] != default_environment():
        raise ValueError("actual command or interpreter environment differs")
    validate_closure(value["artifacts"], requested, directory)
    if digest((directory / "pip-report.json").read_bytes()) != value["reportSha256"]:
        raise ValueError("original resolver report differs")
    raw = json.loads((directory / "pip-report.json").read_bytes())
    if raw.get("pip_version") != policy["pip"] or raw.get("environment") != value["environment"]:
        raise ValueError("original report runtime differs")
    selected = {}
    for item in raw["install"]:
        info = item["download_info"]
        filename = canonical_origin(info["url"])
        key = canonicalize_name(item["metadata"]["name"])
        if key in selected:
            raise ValueError("duplicate report artifact")
        selected[key] = (item["metadata"]["version"], filename, info["url"], info["archive_info"]["hashes"]["sha256"])
    expected = {x["name"]: (x["version"], x["filename"], x["origin"], x["sha256"]) for x in value["artifacts"]}
    if selected != expected or digest((directory / "resolver.stdout").read_bytes()) != value["stdoutSha256"]:
        raise ValueError("original resolver artifact/output join differs")


def verify_artifact_inputs(proposal: dict, root: Path, revision: str, directory: Path, policy: dict) -> dict:
    if proposal.get("schema") != SCHEMA or proposal.get("candidateQualified") is not False or proposal.get("sourceAdmitted") is not False or proposal.get("publishedWheelIdentity") is not False:
        raise ValueError("proposal is not review-only")
    if proposal.get("implementation") != implementation():
        raise ValueError("producer implementation binding differs")
    if proposal["source"] != source(root, revision) or proposal["runtime"] != runtime(policy):
        raise ValueError("source or runtime binding differs")
    if set(proposal["profiles"]) != set(PROFILES):
        raise ValueError("incomplete profile set")
    expected_build = ["hatchling==1.30.1"]
    for name, value in [("build", proposal["build"]), *proposal["profiles"].items()]:
        requested = expected_build if name == "build" else requirements(proposal["source"], name)
        verify_resolution(value, requested, directory / name, policy)
    built = proposal["sourceBuild"]
    scratch = scratch_identity(built["scratchRoot"], "honua-development-build-")
    expected_install, expected_build_command = build_commands(scratch, directory)
    if built["backendInstallCommand"] != expected_install or built["buildCommand"] != expected_build_command:
        raise ValueError("source build command input binding differs")
    expected_backend = {x["name"]: x["version"] for x in proposal["build"]["artifacts"]}
    if {canonicalize_name(k): v for k, v in built["installedBackend"].items()} != expected_backend:
        raise ValueError("backend installed identity differs")
    expected_lock = "\n".join(f'{x["name"]}=={x["version"]} --hash=sha256:{x["sha256"]}'
                              for x in proposal["build"]["artifacts"]) + "\n"
    if built["backendLock"] != expected_lock:
        raise ValueError("backend exact artifact lock differs")
    if {x["name"] for x in built["wheels"]} != {"honua-sdk", "honua-admin"}:
        raise ValueError("incomplete source-built package set")
    for item in built["wheels"]:
        data = (directory / "source-wheels" / item["filename"]).read_bytes()
        name, version, dependencies = wheel_metadata(data, item["filename"])
        if (digest(data) != item["sha256"] or item["sourceSha"] != revision or item["publishedIdentity"] is not False
                or name != item["name"] or version != proposal["source"]["packages"][name]["metadata"]["version"]
                or dependencies != item["requiresDist"]):
            raise ValueError("source-built wheel binding differs")
    if digest((directory / "source-build.stdout").read_bytes()) != built["stdoutSha256"]:
        raise ValueError("original source build output differs")
    return {"sourceSha": revision, "implementationSha": proposal["implementation"]["sourceSha"], "runtime": proposal["runtime"], "profiles": sorted(PROFILES),
            "proposalSha256": digest(json.dumps(proposal, sort_keys=True).encode()), "sourceAdmitted": False}


def verify_proposal(proposal: dict, root: Path, revision: str, directory: Path, policy: dict) -> dict:
    result = verify_artifact_inputs(proposal, root, revision, directory, policy)
    documentation.verify(sys.modules[__name__], proposal, root, directory)
    return {**result, "documentationContexts": len(proposal["documentationSequences"])}


def generate(root: Path, revision: str, destination: Path, policy: dict) -> dict:
    initial, actual_runtime = source(root, revision), runtime(policy)
    # Exclusive destination; no repo writes, version edits, adoption or publication.
    if destination.resolve().is_relative_to(root.resolve()):
        raise ValueError("proposal destination must stay outside immutable source")
    destination.mkdir(mode=0o700)
    try:
        proposal = {"schema": SCHEMA, "implementation": implementation(), "source": initial, "runtime": actual_runtime,
                    "sourceAdmitted": False, "candidateQualified": False, "publishedWheelIdentity": False,
                    "build": resolve(["hatchling==1.30.1"], destination / "build"), "profiles": {}}
        for name in PROFILES:
            proposal["profiles"][name] = resolve(requirements(initial, name), destination / name)
        if initial != source(root, revision) or actual_runtime != runtime(policy):
            raise ValueError("source/runtime changed before backend installation")
        proposal["sourceBuild"] = build_source_wheels(initial, root, destination, proposal["build"])
        proposal["documentationSequences"] = documentation.capture(sys.modules[__name__], proposal, root, destination)
        if initial != source(root, revision) or actual_runtime != runtime(policy):
            raise ValueError("source/runtime changed during generation")
        verify_proposal(proposal, root, revision, destination, policy)
        (destination / "proposal.json").write_text(json.dumps(proposal, indent=2) + "\n")
        return proposal
    except Exception as exc:
        (destination / "failure.json").write_text(json.dumps({"status": "FAIL", "errorType": type(exc).__name__,
                                                               "sourceAdmitted": False}) + "\n")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--runtime-policy", type=Path, default=Path(__file__).parent / "development-inputs/runtime.json")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        policy = json.loads(args.runtime_policy.read_text())
        if args.verify:
            verify_proposal(json.loads((args.destination / "proposal.json").read_text()), args.source,
                            args.revision, args.destination, policy)
        else:
            generate(args.source, args.revision, args.destination, policy)
    except Exception as exc:  # A refused proposal is nonzero, with URL-free public failure details.
        # Do not expose credentialized URLs or resolver stderr on refusal.
        parser.exit(1, f"development input proposal refused: {type(exc).__name__}\n")


if __name__ == "__main__":
    main()
